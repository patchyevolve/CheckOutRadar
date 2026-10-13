"""Formal Output JSON Schema sent to TinyFish and local validation contracts.

Reflecting v4 review corrections:
1. first_charge_step and first_disclosure_step are NOT in the schema; they are derived.
2. stage_captures explicitly track step_name, step_index, capture_status, and inspection_status.
3. Preselected addons, urgency indicators, and monetary totals are typed normalized structures.
4. Disclosure states include: 'observed', 'not_observed_verified', 'unknown'.
"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, model_validator


# Supported JSON Schema for TinyFish output_schema parameter
TINYFISH_AGENT_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": [
                "ok",
                "blocked_by_login",
                "blocked_by_bot",
                "condition_not_applied",
                "extraction_inconsistent",
                "unsupported",
                "failed",
            ],
        },
        "requested": {
            "type": "object",
            "properties": {
                "pincode": {"type": "string", "nullable": True},
                "session": {"type": "string", "enum": ["fresh", "returning"]},
                "cart_tier": {"type": "string", "enum": ["above_threshold", "below_threshold"]},
            },
            "required": ["session", "cart_tier"],
        },
        "observed": {
            "type": "object",
            "properties": {
                "pincode": {"type": "string", "nullable": True},
                "subtotal_minor": {"type": "integer"},
                "currency": {"type": "string"},
            },
            "required": ["subtotal_minor", "currency"],
        },
        "stage_captures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step_name": {
                        "type": "string",
                        "enum": ["product", "cart", "checkout_summary", "other"],
                    },
                    "step_index": {"type": "integer"},
                    "provider_step_id": {"type": "string", "nullable": True},
                    "capture_status": {
                        "type": "string",
                        "enum": ["verified", "failed", "incomplete"],
                    },
                    "inspection_status": {
                        "type": "string",
                        "enum": ["inspected", "uninspected"],
                    },
                    "screenshot_ref": {"type": "string", "nullable": True},
                },
                "required": ["step_name", "step_index", "capture_status", "inspection_status"],
            },
        },
        "charges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "amount_minor": {"type": "integer"},
                    "currency": {"type": "string"},
                    "step": {
                        "type": "string",
                        "enum": ["product", "cart", "checkout_summary"],
                    },
                    "mandatory": {
                        "type": "string",
                        "enum": ["yes", "no", "unknown"],
                    },
                },
                "required": ["label", "amount_minor", "currency", "step", "mandatory"],
            },
        },
        "disclosures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "charge_label": {"type": "string"},
                    "step": {
                        "type": "string",
                        "enum": ["product", "cart", "checkout_summary"],
                    },
                    "state": {
                        "type": "string",
                        "enum": ["observed", "not_observed_verified", "unknown"],
                    },
                    "visible_text": {"type": "string", "nullable": True},
                    "amount_minor": {"type": "integer", "nullable": True},
                    "condition_text": {"type": "string", "nullable": True},
                },
                "required": ["charge_label", "step", "state"],
            },
        },
        "preselected_addons": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "amount_minor": {"type": "integer"},
                    "default_selected": {"type": "boolean"},
                    "user_modified": {"type": "boolean"},
                    "in_total": {"type": "boolean"},
                    "step": {"type": "string"},
                },
                "required": ["label", "amount_minor", "default_selected", "in_total"],
            },
        },
        "urgency_indicators": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["countdown", "scarcity", "social_proof", "other"],
                    },
                    "claimed_deadline": {"type": "string", "nullable": True},
                    "observed_seconds_remaining": {"type": "integer", "nullable": True},
                    "step": {"type": "string"},
                },
                "required": ["text", "type", "step"],
            },
        },
        "totals": {
            "type": "object",
            "properties": {
                "subtotal_minor": {"type": "integer"},
                "charges_minor": {"type": "integer"},
                "taxes_minor": {"type": "integer"},
                "discounts_minor": {"type": "integer"},
                "final_payable_minor": {"type": "integer"},
                "currency": {"type": "string"},
            },
            "required": [
                "subtotal_minor",
                "charges_minor",
                "taxes_minor",
                "discounts_minor",
                "final_payable_minor",
                "currency",
            ],
        },
        "policy_links": {
            "type": "object",
            "properties": {
                "refund": {"type": "string", "nullable": True},
                "cancellation": {"type": "string", "nullable": True},
                "shipping": {"type": "string", "nullable": True},
            },
        },
    },
    "required": [
        "status",
        "requested",
        "observed",
        "stage_captures",
        "charges",
        "disclosures",
        "totals",
    ],
}


# Representative Example Result used in tests and verification
EXAMPLE_AGENT_RESULT: Dict[str, Any] = {
    "status": "ok",
    "requested": {
        "pincode": "110001",
        "session": "fresh",
        "cart_tier": "above_threshold",
    },
    "observed": {
        "pincode": "110001",
        "subtotal_minor": 79900,
        "currency": "INR",
    },
    "stage_captures": [
        {
            "step_name": "product",
            "step_index": 1,
            "provider_step_id": "evt_prod_01",
            "capture_status": "verified",
            "inspection_status": "inspected",
            "screenshot_ref": "snap_01",
        },
        {
            "step_name": "cart",
            "step_index": 2,
            "provider_step_id": "evt_cart_02",
            "capture_status": "verified",
            "inspection_status": "inspected",
            "screenshot_ref": "snap_02",
        },
        {
            "step_name": "checkout_summary",
            "step_index": 3,
            "provider_step_id": "evt_chk_03",
            "capture_status": "verified",
            "inspection_status": "inspected",
            "screenshot_ref": "snap_03",
        },
    ],
    "charges": [
        {
            "label": "Handling fee",
            "amount_minor": 500,
            "currency": "INR",
            "step": "checkout_summary",
            "mandatory": "yes",
        },
        {
            "label": "Delivery fee",
            "amount_minor": 4000,
            "currency": "INR",
            "step": "cart",
            "mandatory": "yes",
        },
    ],
    "disclosures": [
        {
            "charge_label": "Delivery fee",
            "step": "cart",
            "state": "observed",
            "visible_text": "Standard Delivery: ₹40",
            "amount_minor": 4000,
            "condition_text": None,
        },
        {
            "charge_label": "Handling fee",
            "step": "product",
            "state": "not_observed_verified",
            "visible_text": None,
            "amount_minor": None,
            "condition_text": None,
        },
        {
            "charge_label": "Handling fee",
            "step": "cart",
            "state": "not_observed_verified",
            "visible_text": None,
            "amount_minor": None,
            "condition_text": None,
        },
        {
            "charge_label": "Handling fee",
            "step": "checkout_summary",
            "state": "observed",
            "visible_text": "Order Handling Charge: ₹5.00",
            "amount_minor": 500,
            "condition_text": None,
        },
    ],
    "totals": {
        "subtotal_minor": 79900,
        "charges_minor": 4500,
        "taxes_minor": 0,
        "discounts_minor": 0,
        "final_payable_minor": 84400,
        "currency": "INR",
    },
    "preselected_addons": [
        {
            "label": "Package Protection Insurance",
            "amount_minor": 1500,
            "default_selected": True,
            "user_modified": False,
            "in_total": True,
            "step": "cart",
        }
    ],
    "urgency_indicators": [
        {
            "text": "Flash deal ends in 09:59 minutes!",
            "type": "countdown",
            "claimed_deadline": "09:59",
            "observed_seconds_remaining": 599,
            "step": "product",
        }
    ],
    "policy_links": {
        "refund": "https://example.com/refund-policy",
        "cancellation": "https://example.com/cancellation",
        "shipping": None,
    },
}
