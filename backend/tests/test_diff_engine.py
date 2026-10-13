"""Unit tests for Deterministic Diff Engine."""

import pytest
from app.analysis.diff_engine import DiffEngine, is_matched_pair


def test_is_matched_pair():
    # Differs only in pincode -> matched pair
    cond_a = {"requested": {"pincode": "110001", "session": "fresh", "cart_tier": "above_threshold"}}
    cond_b = {"requested": {"pincode": "560001", "session": "fresh", "cart_tier": "above_threshold"}}
    matched, dim, key = is_matched_pair(cond_a, cond_b)
    assert matched is True
    assert dim == "pincode"
    assert "session:fresh" in key

    # Differs in pincode AND session -> NOT a matched pair (confounded)
    cond_c = {"requested": {"pincode": "560001", "session": "returning", "cart_tier": "above_threshold"}}
    matched2, dim2, _ = is_matched_pair(cond_a, cond_c)
    assert matched2 is False
    assert dim2 is None


def test_cart_tier_quantity_change_does_not_trigger_price_variance():
    """
    Critical specification test:
    Changing cart quantity (1 unit vs 2 units) moves subtotal across threshold.
    This must NOT trigger PRICE_VARIANCE on product unit price or grand totals!
    Instead, delivery fee differences are reported as SMALL_CART_RULE.
    """
    engine = DiffEngine()

    run_below = {
        "id": "run_below",
        "audit_id": "aud_1",
        "requested": {"pincode": "110001", "session": "fresh", "cart_tier": "below_threshold"},
        "observed": {"subtotal_minor": 49900, "currency": "INR"},
        "charges": [
            {"label": "Delivery fee", "amount_minor": 4000, "currency": "INR", "step": "cart"},
        ],
    }

    run_above = {
        "id": "run_above",
        "audit_id": "aud_1",
        "requested": {"pincode": "110001", "session": "fresh", "cart_tier": "above_threshold"},
        "observed": {"subtotal_minor": 99800, "currency": "INR"},  # 2 units of the same item
        "charges": [],  # Free delivery above threshold!
    }

    diffs = engine.compute_pairwise_diffs(run_below, run_above)

    # Must NOT produce PRICE_VARIANCE for the cart value change
    pvar_diffs = [d for d in diffs if d["type"] == "PRICE_VARIANCE"]
    assert len(pvar_diffs) == 0

    # Must produce SMALL_CART_RULE for the delivery fee policy
    rule_diffs = [d for d in diffs if d["type"] == "SMALL_CART_RULE"]
    assert len(rule_diffs) == 1
    assert rule_diffs[0]["detail"]["canonical_label"] == "delivery"
    assert rule_diffs[0]["detail"]["amount_minor"] == 4000


def test_location_matched_pair_price_variance():
    engine = DiffEngine()

    run_delhi = {
        "id": "run_delhi",
        "audit_id": "aud_1",
        "requested": {"pincode": "110001", "session": "fresh", "cart_tier": "above_threshold"},
        "charges": [
            {"label": "Delivery fee", "amount_minor": 3000, "currency": "INR", "step": "cart"},
        ],
    }

    run_remote = {
        "id": "run_remote",
        "audit_id": "aud_1",
        "requested": {"pincode": "795001", "session": "fresh", "cart_tier": "above_threshold"},
        "charges": [
            {"label": "Delivery fee", "amount_minor": 7000, "currency": "INR", "step": "cart"},
        ],
    }

    diffs = engine.compute_pairwise_diffs(run_delhi, run_remote)
    assert len(diffs) == 1
    assert diffs[0]["type"] == "PRICE_VARIANCE"
    assert diffs[0]["detail"]["dimension"] == "pincode"
    assert diffs[0]["detail"]["delta_minor"] == 4000


def test_late_disclosure_requires_verified_negative_capture():
    engine = DiffEngine(expected_disclosure_stage="product")

    # Case A: Earlier stage was verified and inspected with no disclosure -> LATE_DISCLOSURE triggered
    run_verified = {
        "id": "run_v",
        "audit_id": "aud_1",
        "stage_captures": [
            {"step_name": "product", "step_index": 1, "capture_status": "verified", "inspection_status": "inspected"},
            {"step_name": "checkout_summary", "step_index": 3, "capture_status": "verified", "inspection_status": "inspected"},
        ],
        "charges": [
            {"label": "Handling fee", "amount_minor": 500, "currency": "INR", "step": "checkout_summary", "mandatory": "yes"},
        ],
        "disclosures": [
            {"charge_label": "Handling fee", "step": "product", "state": "not_observed_verified"},
            {"charge_label": "Handling fee", "step": "checkout_summary", "state": "observed"},
        ],
    }

    diffs_v = engine.compute_single_run_diffs(run_verified)
    assert len(diffs_v) == 1
    assert diffs_v[0]["type"] == "LATE_DISCLOSURE"
    assert diffs_v[0]["detail"]["canonical_label"] == "handling"

    # Case B: Earlier stage was unknown/failed -> NO late disclosure finding!
    run_unknown = {
        "id": "run_u",
        "audit_id": "aud_1",
        "stage_captures": [
            {"step_name": "product", "step_index": 1, "capture_status": "failed", "inspection_status": "uninspected"},
            {"step_name": "checkout_summary", "step_index": 3, "capture_status": "verified", "inspection_status": "inspected"},
        ],
        "charges": [
            {"label": "Handling fee", "amount_minor": 500, "currency": "INR", "step": "checkout_summary", "mandatory": "yes"},
        ],
        "disclosures": [
            {"charge_label": "Handling fee", "step": "product", "state": "unknown"},
            {"charge_label": "Handling fee", "step": "checkout_summary", "state": "observed"},
        ],
    }

    diffs_u = engine.compute_single_run_diffs(run_unknown)
    assert len(diffs_u) == 0  # Crucial: unknown never triggers LATE_DISCLOSURE finding!


def test_temporal_drift():
    engine = DiffEngine()

    run_t0 = {
        "id": "run_t0",
        "audit_id": "aud_1",
        "requested": {"pincode": "110001", "session": "fresh", "cart_tier": "above_threshold"},
        "finished_at": "2026-10-14T10:00:00Z",
        "charges": [
            {"label": "Platform fee", "amount_minor": 300, "currency": "INR"},
        ],
    }

    run_t1 = {
        "id": "run_t1",
        "audit_id": "aud_1",
        "requested": {"pincode": "110001", "session": "fresh", "cart_tier": "above_threshold"},
        "finished_at": "2026-10-14T18:00:00Z",
        "charges": [
            {"label": "Platform fee", "amount_minor": 600, "currency": "INR"},
        ],
    }

    diffs = engine.compute_temporal_diff(run_t0, run_t1)
    assert len(diffs) == 1
    assert diffs[0]["type"] == "TEMPORAL_DRIFT"
    assert diffs[0]["detail"]["delta_minor"] == 300
