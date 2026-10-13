"""Unit tests for Normalizer."""

import pytest
from app.analysis.normalizer import (
    canonicalize_label,
    parse_to_minor_units,
    derive_first_seen_steps,
)


def test_canonicalize_label():
    assert canonicalize_label("Order Handling Charge") == "handling"
    assert canonicalize_label("Delivery fee") == "delivery"
    assert canonicalize_label("Standard Shipping") == "delivery"
    assert canonicalize_label("Platform convenience fee") == "handling"  # matches handling/convenience
    assert canonicalize_label("Small cart fee") == "small_cart"
    assert canonicalize_label("Rain surge fee") == "surge"
    assert canonicalize_label("Eco Bag Packaging") == "packaging"
    assert canonicalize_label("Custom Gift Card") == "custom_gift_card"


def test_parse_to_minor_units():
    assert parse_to_minor_units(100) == 100
    assert parse_to_minor_units(5.50) == 550
    assert parse_to_minor_units("₹ 799.00") == 79900
    assert parse_to_minor_units("₹5") == 500
    assert parse_to_minor_units("1,250.75") == 125075
    assert parse_to_minor_units(None) == 0


def test_derive_first_seen_steps():
    charges = [
        {"label": "Handling fee", "step": "checkout_summary", "amount_minor": 500},
        {"label": "Delivery fee", "step": "cart", "amount_minor": 4000},
    ]
    disclosures = [
        {"charge_label": "Delivery fee", "step": "cart", "state": "observed"},
        {"charge_label": "Handling fee", "step": "product", "state": "not_observed_verified"},
        {"charge_label": "Handling fee", "step": "cart", "state": "not_observed_verified"},
        {"charge_label": "Handling fee", "step": "checkout_summary", "state": "observed"},
    ]

    first_chg, first_disc = derive_first_seen_steps(charges, disclosures)

    assert first_chg["handling"] == "checkout_summary"
    assert first_chg["delivery"] == "cart"
    assert first_disc["delivery"] == "cart"
    assert first_disc["handling"] == "checkout_summary"
