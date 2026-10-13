"""Mock TinyFish Client for local execution without API keys.

Replays deterministic responses covering the 5 harness merchant variants and real site fallbacks.
All operations log to provider_calls to maintain identical auditability.
"""

import uuid
import base64
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from .adapter import TinyFishAdapter
from ..db import crud

# 1x1 Minimal valid JPEG for mock screenshots
TINY_JPEG_BYTES = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08"
    b"\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00"
    b"\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00"
    b"\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08"
    b"\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
)
TINY_JPEG_B64 = "data:image/jpeg;base64," + base64.b64encode(TINY_JPEG_BYTES).decode("ascii")


class MockTinyFishClient(TinyFishAdapter):
    def __init__(self):
        self._runs: Dict[str, Dict[str, Any]] = {}
        self._profiles: Dict[str, str] = {}

    def search(self, query: str, audit_id: str, purpose: Optional[str] = None) -> List[Dict[str, Any]]:
        req_at = datetime.now(timezone.utc).isoformat()
        results = [
            {
                "position": 1,
                "title": f"Demo Merchant — Search Result for {query}",
                "url": "http://harness:8001/variant/late_disclosure",
                "snippet": "Official checkout radar demo store with controlled variant conditions.",
            },
            {
                "position": 2,
                "title": "Terms of Service & Return Policy",
                "url": "http://harness:8001/policy/refund",
                "snippet": "Orders eligible for return within 7 days. Standard shipping rates apply.",
            },
        ]
        crud.log_provider_call(
            audit_id=audit_id,
            operation="search",
            response_status=200,
            result_usable=True,
            requested_at=req_at,
        )
        return results

    def fetch(self, urls: List[str], audit_id: str, ttl: int = 0, purpose: Optional[str] = None) -> Dict[str, Any]:
        req_at = datetime.now(timezone.utc).isoformat()
        results = []
        for u in urls:
            results.append({
                "url": u,
                "status": 200,
                "content": (
                    "# Terms and Conditions\n\n"
                    "- Delivery fee: Free for orders above ₹500, else ₹40.\n"
                    "- Orders may be cancelled within 1 hour.\n"
                    "- Returns accepted within 7 days."
                ),
            })
        crud.log_provider_call(
            audit_id=audit_id,
            operation="fetch",
            response_status=200,
            result_usable=True,
            requested_at=req_at,
        )
        return {"results": results, "errors": []}

    def submit_agent_run(
        self,
        url: str,
        goal: str,
        audit_id: str,
        run_id: str,
        output_schema: Dict[str, Any],
        browser_profile: str = "lite",
        use_profile: bool = False,
        profile_id: Optional[str] = None,
    ) -> str:
        req_at = datetime.now(timezone.utc).isoformat()
        prov_run_id = f"mock_run_{uuid.uuid4().hex[:12]}"

        # Identify target merchant variant from url
        variant = "late_disclosure"
        for v in ["clean", "late_disclosure", "addon_countdown", "upfront_fee", "legitimate_threshold"]:
            if v in url:
                variant = v
                break

        self._runs[prov_run_id] = {
            "variant": variant,
            "url": url,
            "goal": goal,
            "audit_id": audit_id,
            "run_id": run_id,
            "use_profile": use_profile,
            "profile_id": profile_id,
            "created_at": req_at,
        }

        crud.log_provider_call(
            audit_id=audit_id,
            run_id=run_id,
            operation="agent_submit",
            provider_request_id=prov_run_id,
            response_status=200,
            result_usable=True,
            requested_at=req_at,
        )
        return prov_run_id

    def poll_agent_run(self, provider_run_id: str, audit_id: str, run_id: Optional[str] = None) -> Dict[str, Any]:
        req_at = datetime.now(timezone.utc).isoformat()
        run_meta = self._runs.get(provider_run_id, {})
        variant = run_meta.get("variant", "late_disclosure")

        # Construct synthetic result according to the variant
        result_data = self._build_synthetic_result(variant, run_meta)

        steps = [
            {
                "id": "step_prod_01",
                "timestamp": req_at,
                "status": "COMPLETED",
                "action": "Inspect product page and visible disclosures",
                "screenshot": TINY_JPEG_B64,
                "duration": "1.2s",
            },
            {
                "id": "step_cart_02",
                "timestamp": req_at,
                "status": "COMPLETED",
                "action": "Add items to cart and check add-ons",
                "screenshot": TINY_JPEG_B64,
                "duration": "1.4s",
            },
            {
                "id": "step_chk_03",
                "timestamp": req_at,
                "status": "COMPLETED",
                "action": "Navigate to checkout summary and itemize charges",
                "screenshot": TINY_JPEG_B64,
                "duration": "1.5s",
            },
        ]

        crud.log_provider_call(
            audit_id=audit_id,
            run_id=run_id,
            operation="agent_poll",
            provider_request_id=provider_run_id,
            response_status=200,
            result_usable=True,
            requested_at=req_at,
        )

        return {
            "run_id": provider_run_id,
            "status": "COMPLETED",
            "goal": run_meta.get("goal", ""),
            "created_at": run_meta.get("created_at"),
            "finished_at": req_at,
            "num_of_steps": 3,
            "result": result_data,
            "steps": steps,
        }

    def _build_synthetic_result(self, variant: str, run_meta: Dict[str, Any]) -> Dict[str, Any]:
        """Construct realistic structured output for each of the 5 variants."""
        # Check requested condition from run in DB if possible
        run_id = run_meta.get("run_id")
        requested_pincode = "110001"
        requested_tier = "above_threshold"
        requested_session = "fresh"

        if run_id:
            db_run = crud.get_run(run_id)
            if db_run and db_run.get("requested"):
                requested_pincode = db_run["requested"].get("pincode", "110001")
                requested_tier = db_run["requested"].get("cart_tier", "above_threshold")
                requested_session = db_run["requested"].get("session", "fresh")

        is_above = (requested_tier == "above_threshold")
        subtotal = 99800 if is_above else 49900

        # Variant 1: Clean (Every fee disclosed upfront on product page)
        if variant == "clean":
            return {
                "status": "ok",
                "requested": {"pincode": requested_pincode, "session": requested_session, "cart_tier": requested_tier},
                "observed": {"pincode": requested_pincode, "subtotal_minor": subtotal, "currency": "INR"},
                "stage_captures": [
                    {"step_name": "product", "step_index": 1, "provider_step_id": "step_prod_01", "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "snap_prod"},
                    {"step_name": "cart", "step_index": 2, "provider_step_id": "step_cart_02", "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "snap_cart"},
                    {"step_name": "checkout_summary", "step_index": 3, "provider_step_id": "step_chk_03", "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "snap_chk"},
                ],
                "charges": [
                    {"label": "Standard Delivery", "amount_minor": 4000, "currency": "INR", "step": "checkout_summary", "mandatory": "yes"},
                ],
                "disclosures": [
                    {"charge_label": "Standard Delivery", "step": "product", "state": "observed", "visible_text": "Delivery: ₹40", "amount_minor": 4000, "condition_text": None},
                    {"charge_label": "Standard Delivery", "step": "cart", "state": "observed", "visible_text": "Delivery: ₹40", "amount_minor": 4000, "condition_text": None},
                    {"charge_label": "Standard Delivery", "step": "checkout_summary", "state": "observed", "visible_text": "Standard Delivery ₹40", "amount_minor": 4000, "condition_text": None},
                ],
                "totals": {
                    "subtotal_minor": subtotal,
                    "charges_minor": 4000,
                    "taxes_minor": 0,
                    "discounts_minor": 0,
                    "final_payable_minor": subtotal + 4000,
                    "currency": "INR",
                },
                "preselected_addons": [],
                "urgency_indicators": [],
                "policy_links": {"refund": "http://harness:8001/policy/refund", "cancellation": None, "shipping": None},
            }

        # Variant 2: Late disclosure (Handling fee ₹5 hidden until checkout summary)
        if variant == "late_disclosure":
            return {
                "status": "ok",
                "requested": {"pincode": requested_pincode, "session": requested_session, "cart_tier": requested_tier},
                "observed": {"pincode": requested_pincode, "subtotal_minor": subtotal, "currency": "INR"},
                "stage_captures": [
                    {"step_name": "product", "step_index": 1, "provider_step_id": "step_prod_01", "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "snap_prod"},
                    {"step_name": "cart", "step_index": 2, "provider_step_id": "step_cart_02", "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "snap_cart"},
                    {"step_name": "checkout_summary", "step_index": 3, "provider_step_id": "step_chk_03", "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "snap_chk"},
                ],
                "charges": [
                    {"label": "Handling fee", "amount_minor": 500, "currency": "INR", "step": "checkout_summary", "mandatory": "yes"},
                ],
                "disclosures": [
                    {"charge_label": "Handling fee", "step": "product", "state": "not_observed_verified", "visible_text": None, "amount_minor": None, "condition_text": None},
                    {"charge_label": "Handling fee", "step": "cart", "state": "not_observed_verified", "visible_text": None, "amount_minor": None, "condition_text": None},
                    {"charge_label": "Handling fee", "step": "checkout_summary", "state": "observed", "visible_text": "Order Handling Fee: ₹5.00", "amount_minor": 500, "condition_text": None},
                ],
                "totals": {
                    "subtotal_minor": subtotal,
                    "charges_minor": 500,
                    "taxes_minor": 0,
                    "discounts_minor": 0,
                    "final_payable_minor": subtotal + 500,
                    "currency": "INR",
                },
                "preselected_addons": [],
                "urgency_indicators": [],
                "policy_links": {"refund": None, "cancellation": None, "shipping": None},
            }

        # Variant 3: Preselected add-on (₹15 Package Insurance) + Resetting Countdown
        if variant == "addon_countdown":
            now_dt = datetime.now(timezone.utc)
            t0_dt = now_dt - timedelta(seconds=30)
            t1_dt = now_dt
            t2_dt = now_dt + timedelta(seconds=15)
            t0_iso = t0_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            t1_iso = t1_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            t2_iso = t2_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

            return {
                "status": "ok",
                "requested": {"pincode": requested_pincode, "session": requested_session, "cart_tier": requested_tier},
                "observed": {"pincode": requested_pincode, "subtotal_minor": subtotal, "currency": "INR"},
                "stage_captures": [
                    {"step_name": "product", "step_index": 1, "provider_step_id": "step_prod_01", "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "snap_prod"},
                    {"step_name": "cart", "step_index": 2, "provider_step_id": "step_cart_02", "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "snap_cart"},
                    {"step_name": "checkout_summary", "step_index": 3, "provider_step_id": "step_chk_03", "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "snap_chk"},
                ],
                "charges": [],
                "disclosures": [],
                "totals": {
                    "subtotal_minor": subtotal,
                    "charges_minor": 1500,  # Insurance added to total!
                    "taxes_minor": 0,
                    "discounts_minor": 0,
                    "final_payable_minor": subtotal + 1500,
                    "currency": "INR",
                },
                "preselected_addons": [
                    {
                        "label": "Transit Protection Guarantee",
                        "amount_minor": 1500,
                        "default_selected": True,
                        "user_modified": False,
                        "in_total": True,
                        "step": "cart",
                    }
                ],
                "urgency_indicators": [
                    {
                        "text": "FLASH SALE: Claim ends in 09:30 minutes! (t0 observation)",
                        "type": "countdown",
                        "claimed_deadline": "09:30",
                        "observed_seconds_remaining": 570,
                        "step": "product",
                        "timestamp": t0_iso,
                        "evidence_ids": ["snap_prod"],
                        "provenance": "synthetic_mock_fixture",
                    },
                    {
                        "text": "FLASH SALE: Claim ends in 09:59 minutes! (t1 observation, 30s elapsed on same page)",
                        "type": "countdown",
                        "claimed_deadline": "09:59",
                        "observed_seconds_remaining": 599,
                        "step": "product",
                        "timestamp": t1_iso,
                        "elapsed_seconds": 30,
                        "evidence_ids": ["snap_prod"],
                        "provenance": "synthetic_mock_fixture",
                    },
                    {
                        "text": "Complete checkout within 09:59 minutes to hold your items! (cross-stage observation)",
                        "type": "countdown",
                        "claimed_deadline": "09:59",
                        "observed_seconds_remaining": 599,
                        "step": "checkout_summary",
                        "timestamp": t2_iso,
                        "elapsed_seconds": 15,
                        "evidence_ids": ["snap_chk"],
                        "provenance": "synthetic_mock_fixture",
                    },
                ],
                "policy_links": {"refund": None, "cancellation": None, "shipping": None},
            }

        # Variant 4: Negative control, upfront fee (fee disclosed on product page)
        if variant == "upfront_fee":
            return {
                "status": "ok",
                "requested": {"pincode": requested_pincode, "session": requested_session, "cart_tier": requested_tier},
                "observed": {"pincode": requested_pincode, "subtotal_minor": subtotal, "currency": "INR"},
                "stage_captures": [
                    {"step_name": "product", "step_index": 1, "provider_step_id": "step_prod_01", "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "snap_prod"},
                    {"step_name": "cart", "step_index": 2, "provider_step_id": "step_cart_02", "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "snap_cart"},
                    {"step_name": "checkout_summary", "step_index": 3, "provider_step_id": "step_chk_03", "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "snap_chk"},
                ],
                "charges": [
                    {"label": "Convenience fee", "amount_minor": 2000, "currency": "INR", "step": "checkout_summary", "mandatory": "yes"},
                ],
                "disclosures": [
                    {"charge_label": "Convenience fee", "step": "product", "state": "observed", "visible_text": "Convenience Fee: ₹20", "amount_minor": 2000, "condition_text": None},
                    {"charge_label": "Convenience fee", "step": "cart", "state": "observed", "visible_text": "Convenience Fee: ₹20", "amount_minor": 2000, "condition_text": None},
                    {"charge_label": "Convenience fee", "step": "checkout_summary", "state": "observed", "visible_text": "Convenience Fee ₹20", "amount_minor": 2000, "condition_text": None},
                ],
                "totals": {
                    "subtotal_minor": subtotal,
                    "charges_minor": 2000,
                    "taxes_minor": 0,
                    "discounts_minor": 0,
                    "final_payable_minor": subtotal + 2000,
                    "currency": "INR",
                },
                "preselected_addons": [],
                "urgency_indicators": [],
                "policy_links": {},
            }

        # Variant 5: Negative control, legitimate threshold (free delivery above ₹500, ₹40 below)
        # When above threshold: no delivery fee. When below threshold: ₹40 delivery fee.
        delivery_fee = 0 if is_above else 4000
        charges = []
        disclosures = []
        if not is_above:
            charges.append({"label": "Delivery fee", "amount_minor": 4000, "currency": "INR", "step": "cart", "mandatory": "yes"})
            disclosures.append({"charge_label": "Delivery fee", "step": "cart", "state": "observed", "visible_text": "Standard Delivery: ₹40 (Free above ₹500)", "amount_minor": 4000, "condition_text": "Below ₹500"})

        return {
            "status": "ok",
            "requested": {"pincode": requested_pincode, "session": requested_session, "cart_tier": requested_tier},
            "observed": {"pincode": requested_pincode, "subtotal_minor": subtotal, "currency": "INR"},
            "stage_captures": [
                {"step_name": "product", "step_index": 1, "provider_step_id": "step_prod_01", "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "snap_prod"},
                {"step_name": "cart", "step_index": 2, "provider_step_id": "step_cart_02", "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "snap_cart"},
                {"step_name": "checkout_summary", "step_index": 3, "provider_step_id": "step_chk_03", "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "snap_chk"},
            ],
            "charges": charges,
            "disclosures": disclosures,
            "totals": {
                "subtotal_minor": subtotal,
                "charges_minor": delivery_fee,
                "taxes_minor": 0,
                "discounts_minor": 0,
                "final_payable_minor": subtotal + delivery_fee,
                "currency": "INR",
            },
            "preselected_addons": [],
            "urgency_indicators": [],
            "policy_links": {},
        }

    def download_screenshot(self, provider_run_id: str, step_id: str, audit_id: str, run_id: Optional[str] = None) -> bytes:
        req_at = datetime.now(timezone.utc).isoformat()
        crud.log_provider_call(
            audit_id=audit_id,
            run_id=run_id,
            operation="screenshot",
            provider_request_id=f"{provider_run_id}/{step_id}",
            response_status=200,
            result_usable=True,
            requested_at=req_at,
        )
        return TINY_JPEG_BYTES

    def create_browser_profile(self, name: str, audit_id: str) -> str:
        req_at = datetime.now(timezone.utc).isoformat()
        prof_id = f"prof_mock_{uuid.uuid4().hex[:12]}"
        self._profiles[prof_id] = name
        crud.log_provider_call(
            audit_id=audit_id,
            operation="profile_create",
            provider_request_id=prof_id,
            response_status=201,
            result_usable=True,
            requested_at=req_at,
        )
        return prof_id

    def delete_browser_profile(self, profile_id: str, audit_id: str) -> None:
        req_at = datetime.now(timezone.utc).isoformat()
        if profile_id in self._profiles:
            del self._profiles[profile_id]
        crud.log_provider_call(
            audit_id=audit_id,
            operation="profile_delete",
            provider_request_id=profile_id,
            response_status=200,
            result_usable=True,
            requested_at=req_at,
        )
