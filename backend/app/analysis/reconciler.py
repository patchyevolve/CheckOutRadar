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
    
    Returns:
        (is_reconciled, discrepancy_minor, detail_dict)
    """
    calculated_payable = subtotal_minor + charges_minor + taxes_minor - discounts_minor
    discrepancy = calculated_payable - final_payable_minor
    is_reconciled = (discrepancy == 0)

    detail = {
        "subtotal_minor": subtotal_minor,
        "charges_minor": charges_minor,
        "taxes_minor": taxes_minor,
        "discounts_minor": discounts_minor,
        "reported_final_payable_minor": final_payable_minor,
        "calculated_final_payable_minor": calculated_payable,
        "discrepancy_minor": discrepancy,
        "is_reconciled": is_reconciled,
    }
    return is_reconciled, discrepancy, detail
