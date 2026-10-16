"""Deterministic Diff Engine for Checkout Radar.

Principles:
1. Matched Pairs Only: Two runs differing in exactly one requested dimension,
   or two observations across time of the same condition key.
2. Recipe Family vs Cart Instance:
   Quantity differences in cart-tier pairs do NOT trigger PRICE_VARIANCE.
   Equivalent unit prices and normalized fee components are compared.
3. Verified Negative Disclosures:
   LATE_DISCLOSURE requires the earlier stage to be a verified capture AND inspected
   (not_observed_verified). Unknown stages never trigger findings.
4. Five Diff Types:
   - PRICE_VARIANCE
   - LATE_DISCLOSURE
   - UNDISCLOSED_AT_STAGE
   - SMALL_CART_RULE
   - TEMPORAL_DRIFT
"""

from typing import Dict, Any, List, Optional, Tuple
from .normalizer import canonicalize_label, STAGE_INDEX_MAP, STAGE_ORDER, derive_first_seen_steps


def is_matched_pair(
    cond_a: Dict[str, Any],
    cond_b: Dict[str, Any],
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Check if two runs differ in exactly one requested dimension.
    
    Returns:
        (is_matched, differing_dimension, matching_key)
    """
    req_a = cond_a.get("requested", {})
    req_b = cond_b.get("requested", {})

    diff_keys = []
    matching_parts = []

    for key in ["pincode", "session", "cart_tier"]:
        val_a = req_a.get(key)
        val_b = req_b.get(key)
        if val_a != val_b:
            diff_keys.append(key)
        else:
            matching_parts.append(f"{key}:{val_a}")

    if len(diff_keys) == 1:
        return True, diff_keys[0], "|".join(sorted(matching_parts))
    return False, None, None


class DiffEngine:
    def __init__(self, expected_disclosure_stage: str = "product"):
        self.expected_disclosure_stage = expected_disclosure_stage

    def compute_single_run_diffs(self, run_bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Compute stage-level disclosure diffs within a single run.
        (LATE_DISCLOSURE and UNDISCLOSED_AT_STAGE).
        """
        diffs = []
        run_id = run_bundle["id"]
        audit_id = run_bundle.get("audit_id", "")
        charges = run_bundle.get("charges", [])
        disclosures = run_bundle.get("disclosures", [])
        stage_captures = {sc["step_name"]: sc for sc in run_bundle.get("stage_captures", [])}

        derived_charges, derived_disclosures = derive_first_seen_steps(charges, disclosures)

        # Build disclosure states map by (label, step)
        disc_state_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for d in disclosures:
            lbl = canonicalize_label(d.get("charge_label", ""))
            st = d.get("step", "")
            disc_state_map[(lbl, st)] = d

        for c in charges:
            label = canonicalize_label(c["label"])
            first_chg_step = derived_charges.get(label, c.get("step", "checkout_summary"))
            first_disc_step = derived_disclosures.get(label)

            # 1. LATE_DISCLOSURE
            # Mandatory fee whose disclosure is first seen later than expected stage,
            # where the expected stage was captured and inspected (not_observed_verified).
            expected_idx = STAGE_INDEX_MAP.get(self.expected_disclosure_stage, 0)
            chg_idx = STAGE_INDEX_MAP.get(first_chg_step, 2)

            expected_disc_record = disc_state_map.get((label, self.expected_disclosure_stage))
            expected_capture = stage_captures.get(self.expected_disclosure_stage)

            if c.get("mandatory", "yes") == "yes":
                if first_disc_step is not None:
                    disc_idx = STAGE_INDEX_MAP.get(first_disc_step, 2)
                    if disc_idx > expected_idx:
                        # Check whether expected stage was verified not observed
                        if expected_disc_record and expected_disc_record.get("state") == "not_observed_verified":
                            if expected_capture and expected_capture.get("capture_status") == "verified" and expected_capture.get("inspection_status") == "inspected":
                                diffs.append({
                                    "audit_id": audit_id,
                                    "type": "LATE_DISCLOSURE",
                                    "run_a_id": run_id,
                                    "run_b_id": None,
                                    "matching_key": f"single_run:{run_id}",
                                    "detail": {
                                        "label": c["label"],
                                        "canonical_label": label,
                                        "amount_minor": c["amount_minor"],
                                        "expected_stage": self.expected_disclosure_stage,
                                        "observed_disclosure_stage": first_disc_step,
                                        "charge_stage": first_chg_step,
                                        "earlier_stage_state": "not_observed_verified",
                                        "heuristic_rationale": "Configurable project heuristic: mandatory charges are expected upfront on the product page.",
                                    },
                                    "dedup_key": f"late_disc:{run_id}:{label}:{first_disc_step}",
                                })

                # 2. UNDISCLOSED_AT_STAGE
                # Mandatory charge observed at step S, but no disclosure observed at S or earlier
                if first_disc_step is None:
                    # Verified not observed across captured stages
                    all_earlier_verified = True
                    for st in STAGE_ORDER:
                        st_idx = STAGE_INDEX_MAP.get(st, 0)
                        if st_idx <= chg_idx:
                            rec = disc_state_map.get((label, st))
                            if not rec or rec.get("state") != "not_observed_verified":
                                all_earlier_verified = False
                                break
                    if all_earlier_verified:
                        diffs.append({
                            "audit_id": audit_id,
                            "type": "UNDISCLOSED_AT_STAGE",
                            "run_a_id": run_id,
                            "run_b_id": None,
                            "matching_key": f"single_run:{run_id}",
                            "detail": {
                                "label": c["label"],
                                "canonical_label": label,
                                "amount_minor": c["amount_minor"],
                                "charge_step": first_chg_step,
                                "verified_absence_up_to": first_chg_step,
                            },
                            "dedup_key": f"undisclosed:{run_id}:{label}:{first_chg_step}",
                        })

        return diffs

    def compute_pairwise_diffs(
        self,
        run_a: Dict[str, Any],
        run_b: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Compare two runs in a matched pair.
        """
        diffs = []
        is_matched, diff_dim, matching_key = is_matched_pair(run_a, run_b)
        if not is_matched:
            return diffs

        audit_id = run_a.get("audit_id", "")
        charges_a = {canonicalize_label(c["label"]): c for c in run_a.get("charges", [])}
        charges_b = {canonicalize_label(c["label"]): c for c in run_b.get("charges", [])}

        all_charge_labels = set(charges_a.keys()).union(set(charges_b.keys()))

        # Cart tier matched pair comparison (Cart-threshold effect)
        if diff_dim == "cart_tier":
            # Invariant: Recipe family fixed. Quantity differences do NOT trigger PRICE_VARIANCE.
            # Compare per-unit product prices (never grand totals).
            subtotal_a = run_a.get("observed", {}).get("subtotal_minor", 0)
            subtotal_b = run_b.get("observed", {}).get("subtotal_minor", 0)

            # Look for fee components present only on below-threshold side (SMALL_CART_RULE)
            below_run = run_a if run_a.get("requested", {}).get("cart_tier") == "below_threshold" else run_b
            above_run = run_b if below_run == run_a else run_a

            below_charges = {canonicalize_label(c["label"]): c for c in below_run.get("charges", [])}
            above_charges = {canonicalize_label(c["label"]): c for c in above_run.get("charges", [])}

            for lbl in set(below_charges.keys()).union(set(above_charges.keys())):
                in_below = lbl in below_charges
                in_above = lbl in above_charges

                if in_below and not in_above:
                    # Legitimate or standard threshold fee (e.g. delivery fee or small-cart fee below threshold)
                    diffs.append({
                        "audit_id": audit_id,
                        "type": "SMALL_CART_RULE",
                        "run_a_id": run_a["id"],
                        "run_b_id": run_b["id"],
                        "matching_key": matching_key,
                        "detail": {
                            "label": below_charges[lbl]["label"],
                            "canonical_label": lbl,
                            "amount_minor": below_charges[lbl]["amount_minor"],
                            "below_run_id": below_run["id"],
                            "above_run_id": above_run["id"],
                            "subtotal_below_minor": below_run.get("observed", {}).get("subtotal_minor", 0),
                            "subtotal_above_minor": above_run.get("observed", {}).get("subtotal_minor", 0),
                            "explanation": "Fee applied below threshold; absent above threshold. Reported as a policy rule, not an unfair drip pricing finding.",
                        },
                        "dedup_key": f"small_cart:{run_a['id']}:{run_b['id']}:{lbl}",
                    })
                elif in_below and in_above:
                    # Both have the fee: compare fee variance
                    amt_below = below_charges[lbl]["amount_minor"]
                    amt_above = above_charges[lbl]["amount_minor"]
                    if amt_below != amt_above:
                        diffs.append({
                            "audit_id": audit_id,
                            "type": "PRICE_VARIANCE",
                            "run_a_id": run_a["id"],
                            "run_b_id": run_b["id"],
                            "matching_key": matching_key,
                            "detail": {
                                "dimension": diff_dim,
                                "canonical_label": lbl,
                                "amount_a_minor": amt_below,
                                "amount_b_minor": amt_above,
                                "delta_minor": amt_below - amt_above,
                            },
                            "dedup_key": f"pvar:{run_a['id']}:{run_b['id']}:{lbl}",
                        })
            return diffs

        # Location or Session effect comparisons
        for lbl in all_charge_labels:
            chg_a = charges_a.get(lbl)
            chg_b = charges_b.get(lbl)
            if chg_a and chg_b:
                if chg_a["amount_minor"] != chg_b["amount_minor"]:
                    diffs.append({
                        "audit_id": audit_id,
                        "type": "PRICE_VARIANCE",
                        "run_a_id": run_a["id"],
                        "run_b_id": run_b["id"],
                        "matching_key": matching_key,
                        "detail": {
                            "dimension": diff_dim,
                            "canonical_label": lbl,
                            "amount_a_minor": chg_a["amount_minor"],
                            "amount_b_minor": chg_b["amount_minor"],
                            "delta_minor": chg_b["amount_minor"] - chg_a["amount_minor"],
                        },
                        "dedup_key": f"pvar:{run_a['id']}:{run_b['id']}:{lbl}",
                    })
            elif (chg_a and not chg_b) or (chg_b and not chg_a):
                present_run = run_a if chg_a else run_b
                present_chg = chg_a or chg_b
                diffs.append({
                    "audit_id": audit_id,
                    "type": "PRICE_VARIANCE",
                    "run_a_id": run_a["id"],
                    "run_b_id": run_b["id"],
                    "matching_key": matching_key,
                    "detail": {
                        "dimension": diff_dim,
                        "canonical_label": lbl,
                        "present_in_run_id": present_run["id"],
                        "amount_minor": present_chg["amount_minor"],
                    },
                    "dedup_key": f"pvar_presence:{run_a['id']}:{run_b['id']}:{lbl}",
                })

        return diffs

    def compute_temporal_diff(
        self,
        run_t0: Dict[str, Any],
        run_t1: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Compare same condition key across two points in time.
        """
        diffs = []
        cond_t0 = run_t0.get("requested", {})
        cond_t1 = run_t1.get("requested", {})

        # Temporal diff requires identical requested conditions
        if cond_t0 != cond_t1:
            return diffs

        audit_id = run_t0.get("audit_id", "")
        charges_t0 = {canonicalize_label(c["label"]): c["amount_minor"] for c in run_t0.get("charges", [])}
        charges_t1 = {canonicalize_label(c["label"]): c["amount_minor"] for c in run_t1.get("charges", [])}

        all_lbls = set(charges_t0.keys()).union(set(charges_t1.keys()))
        for lbl in all_lbls:
            amt_0 = charges_t0.get(lbl)
            amt_1 = charges_t1.get(lbl)
            if amt_0 != amt_1:
                diffs.append({
                    "audit_id": audit_id,
                    "type": "TEMPORAL_DRIFT",
                    "run_a_id": run_t0["id"],
                    "run_b_id": run_t1["id"],
                    "matching_key": f"temporal:{run_t0['id']}:{run_t1['id']}",
                    "detail": {
                        "canonical_label": lbl,
                        "amount_t0_minor": amt_0,
                        "amount_t1_minor": amt_1,
                        "delta_minor": (amt_1 or 0) - (amt_0 or 0),
                        "t0_time": run_t0.get("finished_at"),
                        "t1_time": run_t1.get("finished_at"),
                    },
                    "dedup_key": f"drift:{run_t0['id']}:{run_t1['id']}:{lbl}",
                })
        return diffs
