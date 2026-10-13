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
    urgency_t0 = {"observed_seconds_remaining": 300, "step": "product"}
    urgency_t1 = {"observed_seconds_remaining": 600, "step": "product"}  # Reset back to 10m!

    finding = detect_false_urgency_indicators(urgency_t0, urgency_t1, elapsed_seconds=30, audit_id="aud_1")
    assert finding is not None
    assert finding["category"] == "false_urgency"
    assert "restarted or reset" in finding["explanation"]
