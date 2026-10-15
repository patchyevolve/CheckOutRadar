"""Regression tests for Observation Idempotency and Stage-to-Snapshot Linkage.

Verifies:
1. Observation idempotency: Worker retries or lease recovery do not duplicate database records.
2. Stage-to-snapshot linkage: Explicit provider references and screenshot refs take precedence
   over generic stage name fallbacks.
3. Cart stage protection: Pre-cart transition actions (e.g. "click add to cart" on product page)
   do not shadow or overwrite the settled cart drawer snapshot.
"""

import pytest
import base64
from datetime import datetime, timezone
from app.db import crud, connection
from app.worker.job_runner import JobRunner
from app.tinyfish.adapter import TinyFishAdapter

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


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test_pipeline.db"
    test_ev = tmp_path / "evidence"
    monkeypatch.setenv("SQLITE_DB_PATH", str(test_db))
    monkeypatch.setenv("EVIDENCE_DIR", str(test_ev))
    monkeypatch.setenv("MOCK_TINYFISH", "true")
    connection.init_db()


class ControlledPipelineAdapter(TinyFishAdapter):
    """Adapter with controlled steps and outputs to test linkage and retry behavior."""

    def __init__(self, poll_data):
        self.poll_data = poll_data

    def search(self, query, audit_id, purpose=None):
        return []

    def fetch(self, urls, audit_id, ttl=0, purpose=None):
        return {}

    def submit_agent_run(self, url, goal, audit_id, run_id, output_schema, **kwargs):
        return "mock_controlled_run_01"

    def poll_agent_run(self, provider_run_id, audit_id, run_id=None):
        return self.poll_data

    def download_screenshot(self, provider_run_id, step_id, audit_id, run_id=None):
        return TINY_JPEG_BYTES

    def create_browser_profile(self, name, audit_id):
        return "prof_test"

    def delete_browser_profile(self, profile_id, audit_id):
        pass


def test_observation_idempotency_on_retry():
    """
    Verifies that re-executing a run (e.g. after worker crash or lease recovery)
    does not create duplicate rows in observation tables.
    """
    audit_id = crud.create_audit(input_url="http://test.com/product", merchant="Idempotent Store", preset="quick")
    cond_id = crud.create_condition(
        audit_id=audit_id,
        condition_key="test_key",
        requested={"session": "fresh", "cart_tier": "above_threshold"},
    )
    run_id = crud.create_run(condition_id=cond_id, requested={"session": "fresh", "cart_tier": "above_threshold"})

    poll_payload = {
        "status": "COMPLETED",
        "steps": [
            {"id": "step_1", "action": "View product details", "screenshot": TINY_JPEG_B64},
            {"id": "step_2", "action": "Inspect cart drawer", "screenshot": TINY_JPEG_B64},
            {"id": "step_3", "action": "Checkout summary review", "screenshot": TINY_JPEG_B64},
        ],
        "result": {
            "status": "ok",
            "requested": {"session": "fresh", "cart_tier": "above_threshold"},
            "observed": {"subtotal_minor": 1000, "currency": "INR"},
            "stage_captures": [
                {"step_name": "product", "step_index": 1, "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "step_1"},
                {"step_name": "cart", "step_index": 2, "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "step_2"},
                {"step_name": "checkout_summary", "step_index": 3, "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "step_3"},
            ],
            "charges": [
                {"label": "Delivery fee", "amount_minor": 50, "currency": "INR", "step": "checkout_summary", "mandatory": "yes"},
            ],
            "disclosures": [
                {"charge_label": "Delivery fee", "step": "checkout_summary", "state": "observed", "visible_text": "Delivery: ₹0.50", "amount_minor": 50},
            ],
            "preselected_addons": [
                {"label": "Package Care", "amount_minor": 10, "default_selected": True, "user_modified": False, "in_total": True, "step": "cart"},
            ],
            "urgency_indicators": [
                {"text": "Only 3 left!", "type": "scarcity", "claimed_deadline": None, "observed_seconds_remaining": None, "step": "product"},
            ],
            "totals": {
                "subtotal_minor": 1000,
                "charges_minor": 50,
                "taxes_minor": 0,
                "discounts_minor": 0,
                "final_payable_minor": 1050,
            },
        },
    }

    adapter = ControlledPipelineAdapter(poll_payload)
    runner = JobRunner(worker_id="test_worker_1", adapter=adapter)

    # First execution pass
    crud.enqueue_job(run_id=run_id)
    assert runner.run_one_cycle() is True

    conn = connection.get_connection()
    try:
        chg_count_1 = conn.execute("SELECT count(*) FROM charge_observations WHERE run_id = ?", (run_id,)).fetchone()[0]
        disc_count_1 = conn.execute("SELECT count(*) FROM disclosure_observations WHERE run_id = ?", (run_id,)).fetchone()[0]
        sc_count_1 = conn.execute("SELECT count(*) FROM stage_captures WHERE run_id = ?", (run_id,)).fetchone()[0]
        rec_count_1 = conn.execute("SELECT count(*) FROM total_reconciliations WHERE run_id = ?", (run_id,)).fetchone()[0]
        add_count_1 = conn.execute("SELECT count(*) FROM addon_observations WHERE run_id = ?", (run_id,)).fetchone()[0]
        urg_count_1 = conn.execute("SELECT count(*) FROM urgency_observations WHERE run_id = ?", (run_id,)).fetchone()[0]
    finally:
        conn.close()

    assert chg_count_1 == 1
    assert disc_count_1 == 1
    assert sc_count_1 == 3
    assert rec_count_1 == 1
    assert add_count_1 == 1
    assert urg_count_1 == 1

    # Second execution pass (simulating worker lease retry or recovery)
    crud.enqueue_job(run_id=run_id)
    assert runner.run_one_cycle() is True

    conn = connection.get_connection()
    try:
        chg_count_2 = conn.execute("SELECT count(*) FROM charge_observations WHERE run_id = ?", (run_id,)).fetchone()[0]
        disc_count_2 = conn.execute("SELECT count(*) FROM disclosure_observations WHERE run_id = ?", (run_id,)).fetchone()[0]
        sc_count_2 = conn.execute("SELECT count(*) FROM stage_captures WHERE run_id = ?", (run_id,)).fetchone()[0]
        rec_count_2 = conn.execute("SELECT count(*) FROM total_reconciliations WHERE run_id = ?", (run_id,)).fetchone()[0]
        add_count_2 = conn.execute("SELECT count(*) FROM addon_observations WHERE run_id = ?", (run_id,)).fetchone()[0]
        urg_count_2 = conn.execute("SELECT count(*) FROM urgency_observations WHERE run_id = ?", (run_id,)).fetchone()[0]
    finally:
        conn.close()

    # CRITICAL INVARIANT: Row counts must remain strictly 1x (no duplication!)
    assert chg_count_2 == 1, f"Expected 1 charge observation after retry, got {chg_count_2}"
    assert disc_count_2 == 1, f"Expected 1 disclosure observation after retry, got {disc_count_2}"
    assert sc_count_2 == 3, f"Expected 3 stage captures after retry, got {sc_count_2}"
    assert rec_count_2 == 1, f"Expected 1 total reconciliation after retry, got {rec_count_2}"
    assert add_count_2 == 1, f"Expected 1 addon observation after retry, got {add_count_2}"
    assert urg_count_2 == 1, f"Expected 1 urgency observation after retry, got {urg_count_2}"


def test_stage_to_snapshot_linkage_prioritizes_specific_refs():
    """
    Verifies that explicit provider_step_id or screenshot_ref is prioritized over
    generic stage names, ensuring stage captures bind to the intended screenshot.
    """
    audit_id = crud.create_audit(input_url="http://test.com/product", merchant="Linkage Store", preset="quick")
    cond_id = crud.create_condition(
        audit_id=audit_id,
        condition_key="link_key",
        requested={"session": "fresh", "cart_tier": "above_threshold"},
    )
    run_id = crud.create_run(condition_id=cond_id, requested={"session": "fresh", "cart_tier": "above_threshold"})

    poll_payload = {
        "status": "COMPLETED",
        "steps": [
            {"id": "step_action_prod", "action": "Navigate to product", "screenshot": TINY_JPEG_B64},
            # Intermediate step containing 'cart' in text
            {"id": "step_action_add", "action": "Click 'ADD TO CART' button", "screenshot": TINY_JPEG_B64},
            # Actual cart view
            {"id": "step_action_drawer", "action": "Inspect cart drawer", "screenshot": TINY_JPEG_B64},
            {"id": "step_action_chk", "action": "Order review and checkout summary", "screenshot": TINY_JPEG_B64},
        ],
        "result": {
            "status": "ok",
            "requested": {"session": "fresh", "cart_tier": "above_threshold"},
            "observed": {"subtotal_minor": 199900, "currency": "INR"},
            "stage_captures": [
                {
                    "step_name": "product",
                    "step_index": 1,
                    "provider_step_id": "step_action_prod",
                    "capture_status": "verified",
                    "inspection_status": "inspected",
                },
                {
                    "step_name": "cart",
                    "step_index": 2,
                    "provider_step_id": "step_action_drawer",  # Explicitly binds to drawer step!
                    "capture_status": "verified",
                    "inspection_status": "inspected",
                },
                {
                    "step_name": "checkout_summary",
                    "step_index": 3,
                    "provider_step_id": "step_action_chk",
                    "capture_status": "verified",
                    "inspection_status": "inspected",
                },
            ],
            "charges": [],
            "disclosures": [],
            "totals": {"subtotal_minor": 199900, "charges_minor": 0, "taxes_minor": 0, "discounts_minor": 0, "final_payable_minor": 199900},
        },
    }

    adapter = ControlledPipelineAdapter(poll_payload)
    runner = JobRunner(worker_id="linkage_worker", adapter=adapter)

    crud.enqueue_job(run_id=run_id)
    assert runner.run_one_cycle() is True

    conn = connection.get_connection()
    try:
        caps = conn.execute("SELECT * FROM stage_captures WHERE run_id = ?", (run_id,)).fetchall()
        snaps = conn.execute("SELECT * FROM snapshots WHERE run_id = ?", (run_id,)).fetchall()
    finally:
        conn.close()

    snap_by_id = {s["id"]: s for s in snaps}
    cart_cap = next(c for c in caps if c["step_name"] == "cart")
    cart_snap = snap_by_id.get(cart_cap["snapshot_id"])

    assert cart_snap is not None
    # Verify the snapshot bound to cart was step_action_drawer, not step_action_add
    assert cart_cap["provider_step_id"] == "step_action_drawer"


def test_cart_stage_linkage_does_not_get_shadowed_by_product_transition():
    """
    Even without explicit provider_step_id, a step labeled with an affirmative cart view
    ('inspect cart drawer') must have higher priority than an action transition ('click add to cart').
    """
    audit_id = crud.create_audit(input_url="http://test.com/product", merchant="Fallback Store", preset="quick")
    cond_id = crud.create_condition(
        audit_id=audit_id,
        condition_key="fallback_key",
        requested={"session": "fresh", "cart_tier": "above_threshold"},
    )
    run_id = crud.create_run(condition_id=cond_id, requested={"session": "fresh", "cart_tier": "above_threshold"})

    poll_payload = {
        "status": "COMPLETED",
        "steps": [
            {"id": "step_1", "action": "Navigate to product", "screenshot": TINY_JPEG_B64},
            # Transition step (prio 1)
            {"id": "step_2", "action": "Click 'ADD TO CART'", "screenshot": TINY_JPEG_B64},
            # Definitive cart view (prio 2)
            {"id": "step_3", "action": "Inspect cart drawer contents", "screenshot": TINY_JPEG_B64},
            # Summary (checkout_summary)
            {"id": "step_4", "action": "Proceed to checkout summary", "screenshot": TINY_JPEG_B64},
        ],
        "result": {
            "status": "ok",
            "requested": {"session": "fresh", "cart_tier": "above_threshold"},
            "observed": {"subtotal_minor": 199900, "currency": "INR"},
            # Notice: No provider_step_id or screenshot_ref specified! Relies on stage fallback.
            "stage_captures": [
                {"step_name": "product", "step_index": 1, "capture_status": "verified", "inspection_status": "inspected"},
                {"step_name": "cart", "step_index": 2, "capture_status": "verified", "inspection_status": "inspected"},
                {"step_name": "checkout_summary", "step_index": 3, "capture_status": "verified", "inspection_status": "inspected"},
            ],
            "charges": [],
            "disclosures": [],
            "totals": {"subtotal_minor": 199900, "charges_minor": 0, "taxes_minor": 0, "discounts_minor": 0, "final_payable_minor": 199900},
        },
    }

    adapter = ControlledPipelineAdapter(poll_payload)
    runner = JobRunner(worker_id="fallback_worker", adapter=adapter)

    crud.enqueue_job(run_id=run_id)
    assert runner.run_one_cycle() is True

    conn = connection.get_connection()
    try:
        caps = conn.execute("SELECT * FROM stage_captures WHERE run_id = ?", (run_id,)).fetchall()
        snaps = conn.execute("SELECT * FROM snapshots WHERE run_id = ?", (run_id,)).fetchall()
    finally:
        conn.close()

    snap_by_id = {s["id"]: s for s in snaps}
    cart_cap = next(c for c in caps if c["step_name"] == "cart")
    assert cart_cap["snapshot_id"] is not None

    assert len(snaps) == 4
    step_2_snap_id = snaps[1]["id"]
    step_3_snap_id = snaps[2]["id"]

    # Step 3 ("Inspect cart drawer contents") should be mapped to cart, not Step 2 ("Click 'ADD TO CART'")
    assert cart_cap["snapshot_id"] == step_3_snap_id
    assert cart_cap["snapshot_id"] != step_2_snap_id
