"""Unit tests for Monetary Reconciler."""

import pytest
from app.analysis.reconciler import reconcile_totals


def test_reconcile_totals_success():
    # ₹799.00 subtotal + ₹40.00 delivery + ₹5.00 handling = ₹844.00 payable
    is_rec, diff, detail = reconcile_totals(
        subtotal_minor=79900,
        charges_minor=4500,
        taxes_minor=0,
        discounts_minor=0,
        final_payable_minor=84400,
    )
    assert is_rec is True
    assert diff == 0
    assert detail["is_reconciled"] is True


def test_reconcile_totals_mismatch():
    # Inconsistent extraction: reported payable doesn't match equation
    is_rec, diff, detail = reconcile_totals(
        subtotal_minor=79900,
        charges_minor=4500,
        taxes_minor=0,
        discounts_minor=0,
        final_payable_minor=85000,
    )
    assert is_rec is False
    assert diff == -600  # calculated (84400) - reported (85000)
    assert detail["is_reconciled"] is False


def test_reconcile_totals_tax_inclusive_gst():
    # GST / MRP model: ₹1,999.00 subtotal (taxes ₹304.93 included) + ₹0 charges = ₹1,999.00 payable
    is_rec, diff, detail = reconcile_totals(
        subtotal_minor=199900,
        charges_minor=0,
        taxes_minor=30493,
        discounts_minor=0,
        final_payable_minor=199900,
    )
    assert is_rec is True
    assert diff == 0
    assert detail["is_reconciled"] is True
    assert detail["tax_model"] == "inclusive"


def test_reconcile_totals_tax_inclusive_preserves_late_mandatory_charges():
    # GST / MRP model with late mandatory charge:
    # ₹1,999.00 subtotal (taxes ₹304.93 included) + ₹50.00 late mandatory fee = ₹2,049.00 payable
    is_rec, diff, detail = reconcile_totals(
        subtotal_minor=199900,
        charges_minor=5000,
        taxes_minor=30493,
        discounts_minor=0,
        final_payable_minor=204900,
    )
    assert is_rec is True
    assert diff == 0
    assert detail["charges_minor"] == 5000
    assert detail["calculated_final_payable_minor"] == 204900
    assert detail["tax_model"] == "inclusive"

    # If reported payable omitted the charge, it must fail reconciliation
    is_rec_fail, diff_fail, _ = reconcile_totals(
        subtotal_minor=199900,
        charges_minor=5000,
        taxes_minor=30493,
        discounts_minor=0,
        final_payable_minor=199900,
    )
    assert is_rec_fail is False
    assert diff_fail == 5000


