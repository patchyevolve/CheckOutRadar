"""Rule Detectors for CCPA 2023 Dark Pattern Categories.

Demonstrated Categories:
1. Drip Pricing (CCPA 2023 Annex 1.8)
2. Basket Sneaking (CCPA 2023 Annex 1.2)
3. False Urgency (CCPA 2023 Annex 1.1)

Crucial principles:
- Upfront disclosed fees are NOT flagged.
- An add-on that is NOT selected by default is NOT flagged.
- A single countdown view is a candidate only; false urgency requires verified reset/restart across observations.
- All outputs are 'potential indicators', never legal verdicts.
"""

from typing import Dict, Any, List, Optional


def detect_drip_pricing_indicators(
    diffs: List[Dict[str, Any]],
    run_bundle: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Detect potential drip pricing indicators from LATE_DISCLOSURE and UNDISCLOSED_AT_STAGE diffs.
    """
    findings = []
    run_id = run_bundle["id"]
    audit_id = run_bundle.get("audit_id", "")

    # Look for diffs in this run
    for d in diffs:
        if d.get("run_a_id") == run_id and d.get("type") in ["LATE_DISCLOSURE", "UNDISCLOSED_AT_STAGE"]:
            det = d["detail"]
            label = det.get("label", "Mandatory Fee")
            amt_minor = det.get("amount_minor", 0)

            # Retrieve supporting evidence IDs (stage capture or snapshot refs)
            evidence_ids = []
            for sc in run_bundle.get("stage_captures", []):
                if sc.get("snapshot_id"):
                    evidence_ids.append(sc["snapshot_id"])
                elif sc.get("screenshot_ref"):
                    evidence_ids.append(sc["screenshot_ref"])

            explanation = (
                f"Potential drip pricing indicator: mandatory charge '{label}' (₹{amt_minor / 100:.2f}) "
                f"was first observed at {det.get('charge_stage', 'checkout_summary')}, while disclosure was "
                f"verified absent at {det.get('expected_stage', 'product')} stage."
            )

            heuristic_note = (
                "Configurable detector heuristic: mandatory charges are evaluated for upfront disclosure "
                "at product page stage. This is a heuristic test, not a statutory mandate of CCPA 2023."
            )

            findings.append({
                "audit_id": audit_id,
                "diff_id": d.get("id"),
                "category": "drip_pricing",
                "severity": "high" if amt_minor > 1000 else "medium",
                "confidence": 0.90 if d.get("type") == "LATE_DISCLOSURE" else 0.85,
                "explanation": explanation,
                "evidence_ids": evidence_ids,
                "source": "rule",
                "dedup_key": f"finding_drip:{run_id}:{det.get('canonical_label')}",
                "heuristic_note": heuristic_note,
            })
    return findings


def detect_basket_sneaking_indicators(run_bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Detect pre-selected add-ons or options checked by default that increase the total payable.
    """
    findings = []
    run_id = run_bundle["id"]
    audit_id = run_bundle.get("audit_id", "")
    addons = run_bundle.get("preselected_addons", [])

    for addon in addons:
        # Must be default selected and included in total without explicit opt-in
        if addon.get("default_selected") and addon.get("in_total") and not addon.get("user_modified"):
            label = addon.get("label", "Add-on")
            amt_minor = addon.get("amount_minor", 0)

            evidence_ids = []
            for sc in run_bundle.get("stage_captures", []):
                if sc.get("step_name") in ["cart", "checkout_summary"]:
                    if sc.get("snapshot_id"):
                        evidence_ids.append(sc["snapshot_id"])
                    elif sc.get("screenshot_ref"):
                        evidence_ids.append(sc["screenshot_ref"])

            explanation = (
                f"Potential basket sneaking indicator: pre-selected item/service '{label}' (₹{amt_minor / 100:.2f}) "
                f"was selected by default at {addon.get('step', 'cart')} and included in the total payable "
                f"without prior affirmative opt-in by the user."
            )

            findings.append({
                "audit_id": audit_id,
                "diff_id": None,
                "category": "basket_sneaking",
                "severity": "high" if amt_minor > 2000 else "medium",
                "confidence": 0.95,
                "explanation": explanation,
                "evidence_ids": evidence_ids,
                "source": "rule",
                "dedup_key": f"finding_basket:{run_id}:{label.lower().replace(' ', '_')}",
                "heuristic_note": "Evaluated against CCPA 2023 Annex 1.2: inclusion of additional items without express consent.",
            })
    return findings


def detect_false_urgency_indicators(
    urgency_t0: Dict[str, Any],
    urgency_t1: Dict[str, Any],
    elapsed_seconds: int,
    audit_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Compare urgency observations across time interval.
    If countdown restarted or persisted past stated deadline:
    """
    rem_0 = urgency_t0.get("observed_seconds_remaining")
    rem_1 = urgency_t1.get("observed_seconds_remaining")

    if rem_0 is not None and rem_1 is not None:
        # Case A: Timer restarted or increased despite time passing
        if rem_1 >= rem_0:
            return {
                "audit_id": audit_id,
                "diff_id": None,
                "category": "false_urgency",
                "severity": "high",
                "confidence": 0.92,
                "explanation": (
                    f"Potential false urgency indicator: countdown timer restarted or reset from "
                    f"{rem_0}s to {rem_1}s after {elapsed_seconds}s elapsed wall-clock time while holding "
                    f"session and offer state fixed."
                ),
                "evidence_ids": [],
                "source": "rule",
                "dedup_key": f"finding_urgency_reset:{urgency_t0.get('step')}",
                "heuristic_note": "Evaluated under controlled countdown observation procedure (CCPA 2023 Annex 1.1).",
            }
        # Case B: Wall-clock elapsed time exceeded stated deadline, but offer still active
        if elapsed_seconds > rem_0 and rem_1 > 0:
            return {
                "audit_id": audit_id,
                "diff_id": None,
                "category": "false_urgency",
                "severity": "high",
                "confidence": 0.90,
                "explanation": (
                    f"Potential false urgency indicator: offer timer of {rem_0}s expired after {elapsed_seconds}s "
                    f"elapsed time, but the claim continues with {rem_1}s remaining."
                ),
                "evidence_ids": [],
                "source": "rule",
                "dedup_key": f"finding_urgency_expired:{urgency_t0.get('step')}",
                "heuristic_note": "Evaluated under controlled countdown observation procedure (CCPA 2023 Annex 1.1).",
            }
    return None
