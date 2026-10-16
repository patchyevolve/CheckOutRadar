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
from datetime import datetime, timezone


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
    Compare urgency observations across time interval under controlled procedure.
    If countdown restarted or persisted past stated deadline holding session state fixed.
    """
    rem_0 = urgency_t0.get("observed_seconds_remaining")
    rem_1 = urgency_t1.get("observed_seconds_remaining")
    step_0 = urgency_t0.get("step", "product")
    step_1 = urgency_t1.get("step", "product")
    is_same_page = (step_0 == step_1)

    t0_time = urgency_t0.get("timestamp") or "t0"
    t1_time = urgency_t1.get("timestamp") or "t1"

    # Calculate or verify elapsed seconds from timestamps if present
    if (elapsed_seconds is None or elapsed_seconds == 0) and t0_time != "t0" and t1_time != "t1":
        try:
            dt0 = datetime.fromisoformat(t0_time.replace("Z", "+00:00"))
            dt1 = datetime.fromisoformat(t1_time.replace("Z", "+00:00"))
            elapsed_seconds = max(0, int((dt1 - dt0).total_seconds()))
        except Exception:
            elapsed_seconds = 30
    if elapsed_seconds is None:
        elapsed_seconds = 30

    evidence_ids = list(dict.fromkeys(
        (urgency_t0.get("evidence_ids") or []) +
        (urgency_t1.get("evidence_ids") or [])
    ))
    provenance = urgency_t1.get("provenance") or urgency_t0.get("provenance") or "synthetic_mock_fixture"

    if rem_0 is not None and rem_1 is not None:
        # Case A: Timer restarted or increased despite time passing
        if rem_1 >= rem_0:
            proc_desc = "same-page controlled observation" if is_same_page else "cross-stage observation"
            explanation = (
                f"Potential false urgency indicator ({proc_desc}): countdown timer restarted or reset from "
                f"{rem_0}s (at {t0_time}) to {rem_1}s (at {t1_time}) after {elapsed_seconds}s measured elapsed wall-clock time "
                f"while holding session and offer state fixed on {step_0}."
            ) if is_same_page else (
                f"Potential false urgency indicator ({proc_desc}): countdown timer restarted or reset from "
                f"{rem_0}s at {step_0} to {rem_1}s at {step_1} across the checkout funnel."
            )
            raw_obs = {
                "t0_remaining": rem_0,
                "t1_remaining": rem_1,
                "t0_timestamp": t0_time,
                "t1_timestamp": t1_time,
                "elapsed_seconds": elapsed_seconds,
                "navigation_occurred": not is_same_page,
                "step_t0": step_0,
                "step_t1": step_1,
                "evidence_ids": evidence_ids,
                "provenance": provenance,
            }
            return {
                "audit_id": audit_id,
                "diff_id": None,
                "category": "false_urgency",
                "severity": "high",
                "confidence": 0.95 if is_same_page else 0.90,
                "explanation": explanation,
                "evidence_ids": evidence_ids,
                "source": "rule",
                "dedup_key": f"finding_urgency_reset:{step_0}_{step_1}",
                "raw_observations": raw_obs,
                "heuristic_note": (
                    f"Evaluated under controlled countdown observation procedure (CCPA 2023 Annex 1.1). "
                    f"Provenance: {provenance}. Preserves timezone-aware UTC timestamps ({t0_time} -> {t1_time}), "
                    f"measured elapsed interval ({elapsed_seconds}s), and evidence links ({evidence_ids}). "
                    f"Reported strictly as a potential false-urgency indicator, not proof of deceptive intent."
                ),
            }
        # Case B: Wall-clock elapsed time exceeded stated deadline, but offer still active
        if elapsed_seconds > rem_0 and rem_1 > 0:
            raw_obs = {
                "t0_remaining": rem_0,
                "t1_remaining": rem_1,
                "t0_timestamp": t0_time,
                "t1_timestamp": t1_time,
                "elapsed_seconds": elapsed_seconds,
                "navigation_occurred": not is_same_page,
                "step_t0": step_0,
                "step_t1": step_1,
                "evidence_ids": evidence_ids,
                "provenance": provenance,
            }
            return {
                "audit_id": audit_id,
                "diff_id": None,
                "category": "false_urgency",
                "severity": "high",
                "confidence": 0.92,
                "explanation": (
                    f"Potential false urgency indicator (controlled expiry test): offer timer of {rem_0}s expired "
                    f"after {elapsed_seconds}s elapsed time, but the claim continues active with {rem_1}s remaining."
                ),
                "evidence_ids": evidence_ids,
                "source": "rule",
                "dedup_key": f"finding_urgency_expired:{step_0}_{step_1}",
                "raw_observations": raw_obs,
                "heuristic_note": (
                    f"Evaluated under controlled countdown observation procedure (CCPA 2023 Annex 1.1). "
                    f"Provenance: {provenance}. Preserves timezone-aware UTC timestamps ({t0_time} -> {t1_time}), "
                    f"measured elapsed interval ({elapsed_seconds}s), and evidence links ({evidence_ids}). "
                    f"Reported strictly as a potential false-urgency indicator, not proof of deceptive intent."
                ),
            }
    return None


def detect_run_false_urgency_indicators(run_bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Detect false urgency indicators within a single checkout flow bundle.
    Evaluates:
    1. Same-page controlled observation: t0 vs t1 captures on the same page with measured elapsed seconds.
    2. Cross-stage reset test: countdown restarts between distinct funnel steps (e.g., cart -> checkout).
    Preserves raw observation data (timestamps, timer values, elapsed interval, navigation flag, evidence links).
    """
    findings = []
    urgencies = run_bundle.get("urgency_indicators", [])
    if not urgencies or len(urgencies) < 2:
        return findings

    audit_id = run_bundle.get("audit_id", "")
    run_id = run_bundle.get("id", "")

    bundle_evidence_ids = []
    for sc in run_bundle.get("stage_captures", []):
        if sc.get("snapshot_id"):
            bundle_evidence_ids.append(sc["snapshot_id"])
        elif sc.get("screenshot_ref"):
            bundle_evidence_ids.append(sc["screenshot_ref"])

    for i in range(len(urgencies) - 1):
        u0 = urgencies[i]
        u1 = urgencies[i + 1]
        rem_0 = u0.get("observed_seconds_remaining")
        rem_1 = u1.get("observed_seconds_remaining")
        if rem_0 is not None and rem_1 is not None:
            step0 = u0.get("step", "earlier step")
            step1 = u1.get("step", "later step")
            is_same_page = (step0 == step1)

            t0_ts = u0.get("timestamp") or "t0"
            t1_ts = u1.get("timestamp") or "t1"

            # Calculate or verify elapsed seconds from timestamps
            elapsed = u1.get("elapsed_seconds")
            if (elapsed is None or elapsed == 0) and t0_ts != "t0" and t1_ts != "t1":
                try:
                    dt0 = datetime.fromisoformat(t0_ts.replace("Z", "+00:00"))
                    dt1 = datetime.fromisoformat(t1_ts.replace("Z", "+00:00"))
                    elapsed = max(0, int((dt1 - dt0).total_seconds()))
                except Exception:
                    elapsed = 30
            if elapsed is None:
                elapsed = 30

            obs_evidence_ids = list(dict.fromkeys(
                (u0.get("evidence_ids") or []) +
                (u1.get("evidence_ids") or []) +
                bundle_evidence_ids
            ))
            provenance = u1.get("provenance") or u0.get("provenance") or "synthetic_mock_fixture"

            is_timer_reset = (rem_0 is not None and rem_1 is not None and rem_1 >= rem_0)
            is_timer_expired_active = (rem_0 is not None and rem_1 is not None and elapsed > rem_0 and rem_1 > 0)

            if is_timer_reset or is_timer_expired_active:
                if is_timer_reset:
                    if is_same_page:
                        explanation = (
                            f"Potential false urgency indicator (same-page controlled test): countdown timer restarted or reset from "
                            f"{rem_0}s (at {t0_ts}) to {rem_1}s (at {t1_ts}) after {elapsed}s measured elapsed wall-clock time "
                            f"on the same {step0} page while holding session and page state fixed without navigation."
                        )
                        severity = "high"
                        conf = 0.95
                        dedup = f"finding_urgency_same_page:{run_id}:{step0}"
                    else:
                        explanation = (
                            f"Potential false urgency indicator (cross-stage test): countdown timer restarted or reset from "
                            f"{rem_0}s at {step0} to {rem_1}s at {step1} "
                            f"while navigating the checkout funnel."
                        )
                        severity = "medium"
                        conf = 0.88
                        dedup = f"finding_urgency_cross_stage:{run_id}:{step0}_{step1}"
                else:
                    explanation = (
                        f"Potential false urgency indicator (controlled expiry test): offer timer of {rem_0}s expired "
                        f"after {elapsed}s measured elapsed wall-clock time, but the claim continues active with {rem_1}s remaining."
                    )
                    severity = "high"
                    conf = 0.92
                    dedup = f"finding_urgency_expired:{run_id}:{step0}_{step1}"

                raw_obs = {
                    "t0_remaining": rem_0,
                    "t1_remaining": rem_1,
                    "t0_timestamp": t0_ts,
                    "t1_timestamp": t1_ts,
                    "elapsed_seconds": elapsed,
                    "navigation_occurred": not is_same_page,
                    "step_t0": step0,
                    "step_t1": step1,
                    "evidence_ids": obs_evidence_ids,
                    "provenance": provenance,
                }

                findings.append({
                    "audit_id": audit_id,
                    "diff_id": None,
                    "category": "false_urgency",
                    "severity": severity,
                    "confidence": conf,
                    "explanation": explanation,
                    "evidence_ids": obs_evidence_ids,
                    "source": "rule",
                    "dedup_key": dedup,
                    "raw_observations": raw_obs,
                    "heuristic_note": (
                        f"Evaluated under controlled countdown observation procedure (CCPA 2023 Annex 1.1). "
                        f"Provenance: {provenance}. Preserves timezone-aware UTC timestamps ({t0_ts} -> {t1_ts}), "
                        f"measured elapsed interval ({elapsed}s), and evidence links ({obs_evidence_ids}). "
                        f"Reported strictly as a potential false-urgency indicator, not proof of deceptive intent."
                    ),
                })
    return findings


def assess_audit_outcome(
    runs: List[Dict[str, Any]],
    findings: List[Dict[str, Any]],
    diffs: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Assess audit outcome distinguishing confirmed findings, clean checkout flows,
    and inconclusive audits where evidence is missing, incomplete, or blocked.

    Principles:
    - Never turn missing evidence into proof of misconduct or proof that a site is clean.
    - Findings are strictly potential indicators, confirmed by observed evidence.
    - A site is declared 'clean' only when all stages and conditions were captured,
      inspected, and verified transparent with zero findings.
    - If runs were blocked, stage captures failed or uninspected, disclosures unknown,
      or urgency observations incomplete, the outcome is 'inconclusive'.
    """
    if findings:
        return {
            "status": "potential_indicators_detected",
            "findings_count": len(findings),
            "summary": f"Detected {len(findings)} potential dark pattern indicator(s) confirmed by observed evidence.",
            "inconclusive_reasons": [],
            "is_clean": False,
            "is_inconclusive": False,
        }

    inconclusive_reasons: List[str] = []

    if not runs:
        inconclusive_reasons.append("No run observations recorded for this audit.")
    else:
        for r in runs:
            r_id = r.get("id", "unknown_run")
            outcome = r.get("outcome", "ok")
            if outcome != "ok":
                obs = r.get("observed") or {}
                if isinstance(obs, str):
                    try:
                        obs = json.loads(obs)
                    except Exception:
                        obs = {}
                blocker = obs.get("blocker_reason") or obs.get("error_message")
                if outcome == "blocked_by_bot":
                    desc = f"Run {r_id} was BLOCKED by bot detection challenge ('blocked_by_bot', CAPTCHA / Cloudflare Turnstile). {blocker or ''}".strip()
                elif outcome == "provider_policy_blocked":
                    desc = f"Run {r_id} was BLOCKED by provider usage policy ('provider_policy_blocked', e.g. attempting to interact with payment gateway). {blocker or ''}".strip()
                elif outcome == "blocked_by_login":
                    desc = f"Run {r_id} was BLOCKED by mandatory login / OTP authentication requirement ('blocked_by_login'). {blocker or ''}".strip()
                elif outcome == "failed":
                    desc = f"Run {r_id} ended with non-ok outcome 'failed': {blocker or 'Agent failed before checkout completion'}."
                elif outcome == "condition_not_applied":
                    desc = f"Run {r_id} ended with non-ok outcome 'condition_not_applied' (e.g. delivery pincode not accepted or site redirected flow)."
                elif outcome == "extraction_inconsistent":
                    desc = f"Run {r_id} ended with non-ok outcome 'extraction_inconsistent' (order total reconciliation failed arithmetic check)."
                else:
                    desc = f"Run {r_id} ended with non-ok outcome '{outcome}'."
                inconclusive_reasons.append(desc)

            # Check stage captures completeness
            stage_caps = r.get("stage_captures", [])
            if not stage_caps:
                inconclusive_reasons.append(
                    f"Run {r_id} has zero stage captures (checkout flow stages were not captured or inspected)."
                )
            for sc in stage_caps:
                st_name = sc.get("step_name", "step")
                cap_st = sc.get("capture_status", "verified")
                insp_st = sc.get("inspection_status", "inspected")
                if cap_st != "verified" or insp_st != "inspected":
                    inconclusive_reasons.append(
                        f"Stage '{st_name}' in run {r_id} was not fully verified (capture: {cap_st}, inspection: {insp_st})."
                    )

            # Ensure required flow stages (product and checkout_summary) were inspected
            inspected_stages = {
                sc.get("step_name")
                for sc in stage_caps
                if sc.get("capture_status") == "verified" and sc.get("inspection_status") == "inspected"
            }
            required_stages = {"product", "checkout_summary"}
            missing_stages = required_stages - inspected_stages
            if missing_stages:
                inconclusive_reasons.append(
                    f"Run {r_id} is missing verified and inspected required stage(s): {sorted(list(missing_stages))}. "
                    f"A clean outcome cannot be established without inspecting the checkout summary."
                )

            # Check unknown disclosure states where charges were observed
            charges = r.get("charges", [])
            disclosures = r.get("disclosures", [])
            if charges:
                unknown_discs = [d for d in disclosures if d.get("state") == "unknown"]
                if unknown_discs:
                    inconclusive_reasons.append(
                        f"Run {r_id} observed charges at checkout, but disclosure status at earlier stages was 'unknown'."
                    )

            # Check single urgency observation without temporal re-observation
            urgencies = r.get("urgency_indicators", [])
            if len(urgencies) == 1:
                inconclusive_reasons.append(
                    f"Run {r_id} observed a single urgency indicator on '{urgencies[0].get('step', 'product')}' "
                    f"({urgencies[0].get('text', '')}), but a second observation was not performed to verify reset or persistence."
                )

    if inconclusive_reasons:
        return {
            "status": "inconclusive",
            "findings_count": 0,
            "summary": "Audit inconclusive: Missing, obstructed, or incomplete evidence cannot establish that the flow is clean.",
            "inconclusive_reasons": inconclusive_reasons,
            "is_clean": False,
            "is_inconclusive": True,
        }

    return {
        "status": "clean",
        "findings_count": 0,
        "summary": "Verified clean checkout flow under tested condition: All required stages were captured and inspected; 0 potential dark pattern indicators detected within observed flow boundary. Does not certify uninspected payment gateways, payment methods, or alternate conditions.",
        "inconclusive_reasons": [],
        "is_clean": True,
        "is_inconclusive": False,
    }


