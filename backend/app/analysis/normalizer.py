"""Normalizer for Currency, Fee Labels, and Event Sequences.

Key principles:
1. All money is normalized to integer minor units (e.g., INR 5 -> 500 paise).
2. Fee labels are canonicalized to a deterministic set.
3. first_charge_step and first_disclosure_step are DERIVED from the event sequence,
   never stored or taken as authoritative from the model.
"""

import re
from typing import Dict, Any, List, Optional, Tuple

STAGE_ORDER = ["product", "cart", "checkout_summary"]
STAGE_INDEX_MAP = {stage: idx for idx, stage in enumerate(STAGE_ORDER)}

CANONICAL_LABEL_PATTERNS = [
    ("handling", re.compile(r"handling|convenience|processing|service fee", re.I)),
    ("delivery", re.compile(r"delivery|shipping|freight|courier", re.I)),
    ("platform", re.compile(r"platform|marketplace|tech fee", re.I)),
    ("small_cart", re.compile(r"small[- ]?cart|below[- ]?min|minimum order fee", re.I)),
    ("surge", re.compile(r"surge|demand|rain|peak hour", re.I)),
    ("packaging", re.compile(r"packag|bag charge|wrapping", re.I)),
]


def canonicalize_label(raw_label: str) -> str:
    """Map arbitrary merchant fee labels to canonical categories."""
    clean = raw_label.strip()
    for canonical, pattern in CANONICAL_LABEL_PATTERNS:
        if pattern.search(clean):
            return canonical
    return clean.lower().replace(" ", "_")


def parse_to_minor_units(amount: Any, currency: str = "INR") -> int:
    """Convert amount (float, int, or string) to integer minor units."""
    if isinstance(amount, int):
        return amount
    if isinstance(amount, float):
        return int(round(amount * 100))
    if isinstance(amount, str):
        # Strip currency symbols and whitespace
        cleaned = re.sub(r"[^\d.-]", "", amount.replace(",", ""))
        if not cleaned:
            return 0
        return int(round(float(cleaned) * 100))
    return 0


def derive_first_seen_steps(
    charges: List[Dict[str, Any]],
    disclosures: List[Dict[str, Any]],
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Derive the earliest stage where a charge and its disclosure were observed.
    
    Returns:
        (first_charge_step_by_label, first_disclosure_step_by_label)
    """
    first_charge: Dict[str, Tuple[int, str]] = {}
    for c in charges:
        label = c.get("canonical_label") or canonicalize_label(c["label"])
        step = c.get("step", "checkout_summary")
        idx = STAGE_INDEX_MAP.get(step, 99)
        if label not in first_charge or idx < first_charge[label][0]:
            first_charge[label] = (idx, step)

    first_disclosure: Dict[str, Tuple[int, str]] = {}
    for d in disclosures:
        if d.get("state") == "observed":
            label = canonicalize_label(d.get("charge_label", ""))
            step = d.get("step", "checkout_summary")
            idx = STAGE_INDEX_MAP.get(step, 99)
            if label not in first_disclosure or idx < first_disclosure[label][0]:
                first_disclosure[label] = (idx, step)

    derived_charges = {lbl: val[1] for lbl, val in first_charge.items()}
    derived_disclosures = {lbl: val[1] for lbl, val in first_disclosure.items()}
    return derived_charges, derived_disclosures
