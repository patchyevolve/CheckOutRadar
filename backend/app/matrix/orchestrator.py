"""Matrix Orchestrator: Expands audit into condition runs.

Presets:
- Quick (4 runs):
  1. Reference: Pincode A, fresh, above_threshold
  2. Location B: Pincode B, fresh, above_threshold
  3. Location C: Pincode C, fresh, above_threshold
  4. Cart Below: Pincode A, fresh, below_threshold
- Full (12 runs):
  3 pincodes x 2 sessions x 2 cart tiers = 12 runs.

Comparison invariant:
Separates Recipe Family from Instantiated Cart.
Matched pairs differ in exactly one dimension.
"""

from typing import Dict, Any, List, Optional
from ..db import crud


PINCODE_A = "110001"  # New Delhi (Tier-1, Reference)
PINCODE_B = "560001"  # Bengaluru (Tier-1 comparison)
PINCODE_C = "492001"  # Raipur (Tier-2/3 comparison)


def get_default_cart_recipe() -> Dict[str, Any]:
    """
    Deterministic Cart Recipe Family.
    Target subtotal:
    - Above threshold: 2 units -> ₹998.00 (99800 minor units) > ₹500.00
    - Below threshold: 1 unit  -> ₹499.00 (49900 minor units) < ₹500.00
    """
    return {
        "recipe_family_id": "rf_standard_item",
        "threshold_minor": 50000,  # ₹500.00
        "items": [
            {
                "product_id": "prod_coffee_beans",
                "product_name": "Artisan Whole Bean Coffee (500g)",
                "variant": "medium_roast",
                "unit_price_minor": 49900,  # ₹499.00
            }
        ],
        "mechanism": "unit_count",  # 1 unit for below threshold, 2 units for above
    }


def expand_matrix(
    audit_id: str,
    preset: str = "quick",
    cart_recipe: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Expand audit into conditions and runs, and enqueue jobs.
    Returns the list of created conditions.
    """
    recipe = cart_recipe or get_default_cart_recipe()

    pincodes = [PINCODE_A, PINCODE_B, PINCODE_C]
    sessions = ["fresh", "returning"]
    cart_tiers = ["above_threshold", "below_threshold"]

    conditions_to_create = []

    if preset.lower() == "full":
        # 12 conditions
        for p in pincodes:
            for s in sessions:
                for ct in cart_tiers:
                    is_ref = (p == PINCODE_A and s == "fresh" and ct == "above_threshold")
                    key = f"pin:{p}|sess:{s}|cart:{ct}"
                    req = {"pincode": p, "session": s, "cart_tier": ct, "recipe_family_id": recipe["recipe_family_id"]}
                    conditions_to_create.append((key, req, is_ref))
    else:
        # Quick preset (4 runs):
        # 1. Reference: Pincode A, fresh, above
        conditions_to_create.append(
            (f"pin:{PINCODE_A}|sess:fresh|cart:above_threshold",
             {"pincode": PINCODE_A, "session": "fresh", "cart_tier": "above_threshold", "recipe_family_id": recipe["recipe_family_id"]},
             True)
        )
        # 2. Location B: Pincode B, fresh, above
        conditions_to_create.append(
            (f"pin:{PINCODE_B}|sess:fresh|cart:above_threshold",
             {"pincode": PINCODE_B, "session": "fresh", "cart_tier": "above_threshold", "recipe_family_id": recipe["recipe_family_id"]},
             False)
        )
        # 3. Location C: Pincode C, fresh, above
        conditions_to_create.append(
            (f"pin:{PINCODE_C}|sess:fresh|cart:above_threshold",
             {"pincode": PINCODE_C, "session": "fresh", "cart_tier": "above_threshold", "recipe_family_id": recipe["recipe_family_id"]},
             False)
        )
        # 4. Cart Below: Pincode A, fresh, below
        conditions_to_create.append(
            (f"pin:{PINCODE_A}|sess:fresh|cart:below_threshold",
             {"pincode": PINCODE_A, "session": "fresh", "cart_tier": "below_threshold", "recipe_family_id": recipe["recipe_family_id"]},
             False)
        )

    created = []
    for key, req, is_ref in conditions_to_create:
        cond_id = crud.create_condition(
            audit_id=audit_id,
            condition_key=key,
            requested=req,
            is_reference=is_ref,
            supported=True,
        )
        # Create run attempt 1
        run_id = crud.create_run(
            condition_id=cond_id,
            requested=req,
            attempt=1,
            profile_id=None,
        )
        # Enqueue job in durable queue
        crud.enqueue_job(run_id=run_id)

        created.append({
            "condition_id": cond_id,
            "condition_key": key,
            "run_id": run_id,
            "requested": req,
            "is_reference": is_ref,
        })

    crud.emit_event(
        audit_id=audit_id,
        event_type="matrix_expanded",
        payload={"preset": preset, "conditions_count": len(created)},
    )
    return created
