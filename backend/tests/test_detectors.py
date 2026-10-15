"""Unit tests for CCPA Rule Detectors."""

import pytest
from app.analysis.detectors import (
    detect_drip_pricing_indicators,
    detect_basket_sneaking_indicators,
    detect_false_urgency_indicators,
)


def test_drip_pricing_flagged_for_late_disclosure():
    run_bundle = {
        "id": "run_late",
        "audit_id": "aud_1",
        "stage_captures": [
            {"step_name": "product", "snapshot_id": "snap_prod_01"},
            {"step_name": "checkout_summary", "snapshot_id": "snap_chk_02"},
        ],
    }
    diffs = [
        {
            "id": "diff_01",
            "run_a_id": "run_late",
            "type": "LATE_DISCLOSURE",
            "detail": {
                "label": "Handling fee",
                "canonical_label": "handling",
                "amount_minor": 500,
                "charge_stage": "checkout_summary",
                "expected_stage": "product",
            },
        }
    ]

    findings = detect_drip_pricing_indicators(diffs, run_bundle)
    assert len(findings) == 1
    assert findings[0]["category"] == "drip_pricing"
    assert "₹5.00" in findings[0]["explanation"]
    assert "heuristic" in findings[0]["heuristic_note"].lower()
    assert "snap_prod_01" in findings[0]["evidence_ids"]


def test_upfront_fee_not_flagged():
    # If the diff engine produced no LATE_DISCLOSURE (because fee was disclosed upfront),
    # then no drip pricing findings are flagged!
    run_bundle = {"id": "run_clean", "audit_id": "aud_1"}
    diffs = []
    findings = detect_drip_pricing_indicators(diffs, run_bundle)
    assert len(findings) == 0


def test_basket_sneaking_preselected_addon():
    run_bundle = {
        "id": "run_sneak",
        "audit_id": "aud_1",
        "stage_captures": [{"step_name": "cart", "snapshot_id": "snap_cart_01"}],
        "preselected_addons": [
            {
                "label": "Transit Insurance",
                "amount_minor": 1500,
                "default_selected": True,
                "user_modified": False,
                "in_total": True,
                "step": "cart",
            }
        ],
    }

    findings = detect_basket_sneaking_indicators(run_bundle)
    assert len(findings) == 1
    assert findings[0]["category"] == "basket_sneaking"
    assert "Transit Insurance" in findings[0]["explanation"]
    assert "snap_cart_01" in findings[0]["evidence_ids"]


def test_optional_addon_not_flagged():
    # User had to opt in (not default selected)
    run_bundle = {
        "id": "run_opt_in",
        "audit_id": "aud_1",
        "stage_captures": [],
        "preselected_addons": [
            {
                "label": "Gift Wrap",
                "amount_minor": 5000,
                "default_selected": False,  # Not checked by default!
                "user_modified": False,
                "in_total": False,
                "step": "cart",
            }
        ],
    }

    findings = detect_basket_sneaking_indicators(run_bundle)
    assert len(findings) == 0


def test_false_urgency_timer_reset():
    urgency_t0 = {"observed_seconds_remaining": 300, "step": "cart", "timestamp": "2026-10-14T01:00:00Z"}
    urgency_t1 = {"observed_seconds_remaining": 600, "step": "checkout_summary", "timestamp": "2026-10-14T01:00:20Z"}

    finding = detect_false_urgency_indicators(urgency_t0, urgency_t1, elapsed_seconds=20, audit_id="aud_1")
    assert finding is not None
    assert finding["category"] == "false_urgency"
    assert "cross-stage observation" in finding["explanation"]


def test_false_urgency_same_page_controlled_procedure():
    """
    v4 Specification requirement:
    Controlled countdown procedure holding page, session, and cart state fixed.
    Observations at t0 (570s) and t1 (599s) after 30 measured wall-clock seconds.
    """
    from app.analysis.detectors import detect_run_false_urgency_indicators

    run_bundle = {
        "id": "run_urgency_controlled",
        "audit_id": "aud_1",
        "stage_captures": [{"step_name": "product", "snapshot_id": "snap_prod_01"}],
        "urgency_indicators": [
            {
                "text": "FLASH SALE: Claim ends in 09:30 minutes!",
                "type": "countdown",
                "claimed_deadline": "09:30",
                "observed_seconds_remaining": 570,
                "step": "product",
                "timestamp": "2026-10-14T01:00:00Z",
            },
            {
                "text": "FLASH SALE: Claim ends in 09:59 minutes!",
                "type": "countdown",
                "claimed_deadline": "09:59",
                "observed_seconds_remaining": 599,
                "step": "product",
                "timestamp": "2026-10-14T01:00:30Z",
                "elapsed_seconds": 30,
            },
        ],
    }

    findings = detect_run_false_urgency_indicators(run_bundle)
    assert len(findings) == 1
    f = findings[0]
    assert f["category"] == "false_urgency"
    assert f["severity"] == "high"
    assert f["confidence"] == 0.95
    assert "same-page controlled test" in f["explanation"]
    assert "30s measured elapsed wall-clock time" in f["explanation"]
    assert "holding session and page state fixed without navigation" in f["explanation"]


def test_false_urgency_expired_timer_still_active():
    """Timer stated 10s remaining at t0. After 30s elapsed, timer says 5s remaining."""
    from app.analysis.detectors import detect_run_false_urgency_indicators

    run_bundle = {
        "id": "run_urgency_expired",
        "audit_id": "aud_1",
        "stage_captures": [{"step_name": "product", "snapshot_id": "snap_prod_01"}],
        "urgency_indicators": [
            {
                "text": "FLASH DEAL: Ends in 10s!",
                "type": "countdown",
                "claimed_deadline": "00:10",
                "observed_seconds_remaining": 10,
                "step": "product",
                "timestamp": "2026-10-14T01:00:00Z",
            },
            {
                "text": "FLASH DEAL: Ends in 5s!",
                "type": "countdown",
                "claimed_deadline": "00:05",
                "observed_seconds_remaining": 5,
                "step": "product",
                "timestamp": "2026-10-14T01:00:30Z",
                "elapsed_seconds": 30,
            },
        ],
    }

    findings = detect_run_false_urgency_indicators(run_bundle)
    assert len(findings) == 1
    f = findings[0]
    assert f["category"] == "false_urgency"
    assert "controlled expiry test" in f["explanation"]
    assert "timer of 10s expired after 30s" in f["explanation"]


def test_single_countdown_is_not_treated_as_false_urgency():
    """A single countdown screenshot must not be treated as proof that urgency is false."""
    from app.analysis.detectors import detect_run_false_urgency_indicators

    run_bundle = {
        "id": "run_single_countdown",
        "audit_id": "aud_1",
        "stage_captures": [{"step_name": "product", "snapshot_id": "snap_prod_01"}],
        "urgency_indicators": [
            {
                "text": "Sale ends in 15 minutes!",
                "type": "countdown",
                "claimed_deadline": "15:00",
                "observed_seconds_remaining": 900,
                "step": "product",
            }
        ],
    }

    findings = detect_run_false_urgency_indicators(run_bundle)
    assert len(findings) == 0, "Single countdown observation must NEVER trigger false urgency finding"


def test_assess_audit_outcome_distinctions():
    """Verify clean vs inconclusive vs potential indicators distinction."""
    from app.analysis.detectors import assess_audit_outcome

    # 1. Potential indicators detected
    res_ind = assess_audit_outcome(
        runs=[{"id": "r1", "outcome": "ok"}],
        findings=[{"category": "drip_pricing", "explanation": "test"}],
    )
    assert res_ind["status"] == "potential_indicators_detected"
    assert res_ind["is_clean"] is False
    assert res_ind["is_inconclusive"] is False

    # 2. Verified clean
    res_clean = assess_audit_outcome(
        runs=[
            {
                "id": "r1",
                "outcome": "ok",
                "stage_captures": [
                    {"step_name": "product", "capture_status": "verified", "inspection_status": "inspected"},
                    {"step_name": "cart", "capture_status": "verified", "inspection_status": "inspected"},
                    {"step_name": "checkout_summary", "capture_status": "verified", "inspection_status": "inspected"},
                ],
                "charges": [],
                "disclosures": [],
                "urgency_indicators": [],
            }
        ],
        findings=[],
    )
    assert res_clean["status"] == "clean"
    assert res_clean["is_clean"] is True
    assert res_clean["is_inconclusive"] is False

    # 3. Inconclusive: Blocked by login
    res_blocked = assess_audit_outcome(
        runs=[{"id": "r1", "outcome": "blocked_by_login"}],
        findings=[],
    )
    assert res_blocked["status"] == "inconclusive"
    assert res_blocked["is_clean"] is False
    assert res_blocked["is_inconclusive"] is True
    assert any("blocked_by_login" in r for r in res_blocked["inconclusive_reasons"])

    # 4. Inconclusive: Failed stage capture
    res_failed_cap = assess_audit_outcome(
        runs=[
            {
                "id": "r1",
                "outcome": "ok",
                "stage_captures": [
                    {"step_name": "product", "capture_status": "failed", "inspection_status": "uninspected"},
                ],
            }
        ],
        findings=[],
    )
    assert res_failed_cap["status"] == "inconclusive"
    assert any("not fully verified" in r for r in res_failed_cap["inconclusive_reasons"])

    # 5. Inconclusive: Single countdown observation
    res_single_urg = assess_audit_outcome(
        runs=[
            {
                "id": "r1",
                "outcome": "ok",
                "stage_captures": [
                    {"step_name": "product", "capture_status": "verified", "inspection_status": "inspected"},
                ],
                "urgency_indicators": [{"text": "Limited offer", "step": "product"}],
            }
        ],
        findings=[],
    )
    assert res_single_urg["status"] == "inconclusive"
    assert any("second observation was not performed" in r for r in res_single_urg["inconclusive_reasons"])

    # 6. Inconclusive: Zero stage captures recorded
    res_zero_stages = assess_audit_outcome(
        runs=[
            {
                "id": "r1",
                "outcome": "ok",
                "stage_captures": [],
            }
        ],
        findings=[],
    )
    assert res_zero_stages["status"] == "inconclusive"
    assert any("zero stage captures" in r for r in res_zero_stages["inconclusive_reasons"])


