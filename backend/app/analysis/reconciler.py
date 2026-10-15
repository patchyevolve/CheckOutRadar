"""Monetary Reconciler for Extracted Checkout Figures.

Equation:
Subtotal + Charges + Taxes - Discounts == Final payable

All values in integer minor units. If the equation fails, the run is flagged
extraction_inconsistent and excluded from diffs.
"""

from typing import Dict, Any, Tuple


def reconcile_totals(
    subtotal_minor: int,
    charges_minor: int,
    taxes_minor: int,
    discounts_minor: int,
    final_payable_minor: int,
) -> Tuple[bool, int, Dict[str, Any]]:
    """
    Reconcile monetary components.

    Supports both tax-exclusive:
        subtotal + charges + taxes - discounts == final_payable
    and tax-inclusive (e.g. GST/VAT where taxes are already inside subtotal):
        subtotal + charges - discounts == final_payable

    Returns:
        (is_reconciled, discrepancy_minor, detail_dict)
    """
    calc_exclusive = subtotal_minor + charges_minor + taxes_minor - discounts_minor
    calc_inclusive = subtotal_minor + charges_minor - discounts_minor

    if calc_exclusive == final_payable_minor:
        is_reconciled = True
        calculated_payable = calc_exclusive
        discrepancy = 0
        tax_model = "exclusive"
    elif calc_inclusive == final_payable_minor:
        is_reconciled = True
        calculated_payable = calc_inclusive
        discrepancy = 0
        tax_model = "inclusive"
    else:
        is_reconciled = False
        calculated_payable = calc_exclusive
        discrepancy = calc_exclusive - final_payable_minor
        tax_model = "mismatch"

    detail = {
        "subtotal_minor": subtotal_minor,
        "charges_minor": charges_minor,
        "taxes_minor": taxes_minor,
        "discounts_minor": discounts_minor,
        "reported_final_payable_minor": final_payable_minor,
        "calculated_final_payable_minor": calculated_payable,
        "discrepancy_minor": discrepancy,
        "is_reconciled": is_reconciled,
        "tax_model": tax_model,
    }
    return is_reconciled, discrepancy, detail
