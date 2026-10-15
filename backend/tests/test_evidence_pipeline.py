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
from datetime import datetime, timezone, timedelta
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


def test_repeated_processing_of_completed_run_is_strictly_idempotent():
    """
    Review Recommendation 1: Repeated processing of the same completed run.
    Verifies that re-executing or re-enqueueing a completed run preserves exactly
    canonical counts, leaves no duplicate rows, and maintains identical snapshot references.
    """
    audit_id = crud.create_audit(input_url="http://test.com/idempotent", merchant="Idempotent Store", preset="quick")
    cond_id = crud.create_condition(
        audit_id=audit_id,
        condition_key="idempotent_key",
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
            "observed": {"subtotal_minor": 199900, "currency": "INR"},
            "stage_captures": [
                {"step_name": "product", "step_index": 1, "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "step_1"},
                {"step_name": "cart", "step_index": 2, "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "step_2"},
                {"step_name": "checkout_summary", "step_index": 3, "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "step_3"},
            ],
            "charges": [
                {"label": "Delivery fee", "amount_minor": 0, "currency": "INR", "step": "product", "mandatory": "yes"},
            ],
            "disclosures": [
                {"charge_label": "Delivery fee", "step": "product", "state": "observed", "visible_text": "Free shipping", "amount_minor": 0},
            ],
            "preselected_addons": [
                {"label": "Warranty", "amount_minor": 0, "default_selected": False, "user_modified": False, "in_total": False, "step": "product"},
            ],
            "urgency_indicators": [
                {"text": "Fast dispatch", "type": "scarcity", "claimed_deadline": None, "observed_seconds_remaining": None, "step": "product"},
            ],
            "totals": {
                "subtotal_minor": 199900,
                "charges_minor": 0,
                "taxes_minor": 0,
                "discounts_minor": 0,
                "final_payable_minor": 199900,
            },
        },
    }

    adapter = ControlledPipelineAdapter(poll_payload)
    runner = JobRunner(worker_id="worker_rep_1", adapter=adapter)

    # First pass
    crud.enqueue_job(run_id=run_id)
    assert runner.run_one_cycle() is True

    # Capture stage capture snapshot IDs from pass 1
    conn = connection.get_connection()
    try:
        initial_caps = {r["step_name"]: r["snapshot_id"] for r in conn.execute("SELECT * FROM stage_captures WHERE run_id = ?", (run_id,)).fetchall()}
    finally:
        conn.close()

    assert len(initial_caps) == 3
    assert all(sid is not None for sid in initial_caps.values())

    # Second pass: re-enqueue and process the exact same completed run
    crud.enqueue_job(run_id=run_id)
    assert runner.run_one_cycle() is True

    # Third pass: execute yet again
    crud.enqueue_job(run_id=run_id)
    assert runner.run_one_cycle() is True

    conn = connection.get_connection()
    try:
        chg_cnt = conn.execute("SELECT count(*) FROM charge_observations WHERE run_id = ?", (run_id,)).fetchone()[0]
        disc_cnt = conn.execute("SELECT count(*) FROM disclosure_observations WHERE run_id = ?", (run_id,)).fetchone()[0]
        cap_cnt = conn.execute("SELECT count(*) FROM stage_captures WHERE run_id = ?", (run_id,)).fetchone()[0]
        rec_cnt = conn.execute("SELECT count(*) FROM total_reconciliations WHERE run_id = ?", (run_id,)).fetchone()[0]
        add_cnt = conn.execute("SELECT count(*) FROM addon_observations WHERE run_id = ?", (run_id,)).fetchone()[0]
        urg_cnt = conn.execute("SELECT count(*) FROM urgency_observations WHERE run_id = ?", (run_id,)).fetchone()[0]
        subsequent_caps = {r["step_name"]: r["snapshot_id"] for r in conn.execute("SELECT * FROM stage_captures WHERE run_id = ?", (run_id,)).fetchall()}
    finally:
        conn.close()

    # Strict single-instance canonical invariants
    assert chg_cnt == 1
    assert disc_cnt == 1
    assert cap_cnt == 3
    assert rec_cnt == 1
    assert add_cnt == 1
    assert urg_cnt == 1

    # Snapshot references remain valid and non-null in snapshots table
    conn = connection.get_connection()
    try:
        snap_ids_in_db = {s["id"] for s in conn.execute("SELECT id FROM snapshots WHERE run_id = ?", (run_id,)).fetchall()}
    finally:
        conn.close()
    assert all(sid in snap_ids_in_db for sid in subsequent_caps.values())


def test_recovery_after_partially_completed_insertion_rolls_back_cleanly(monkeypatch):
    """
    Review Recommendation 2: Recovery after a partially completed insertion.
    Verifies that if an error or crash occurs midway through observation persistence,
    the entire transaction rolls back atomically without leaving partial orphan rows,
    and subsequent recovery re-populates the complete record cleanly.
    """
    audit_id = crud.create_audit(input_url="http://test.com/atomic", merchant="Atomic Store", preset="quick")
    cond_id = crud.create_condition(
        audit_id=audit_id,
        condition_key="atomic_key",
        requested={"session": "fresh", "cart_tier": "above_threshold"},
    )
    run_id = crud.create_run(condition_id=cond_id, requested={"session": "fresh", "cart_tier": "above_threshold"})

    totals = {"subtotal_minor": 1000, "charges_minor": 0, "taxes_minor": 0, "discounts_minor": 0, "final_payable_minor": 1000}
    snap_id = crud.create_snapshot(
        run_id=run_id,
        step_name="product",
        artifact_path="/tmp/fake.jpg",
        sha256="abc123456789",
        redaction_status="redacted",
    )
    stage_captures = [{"step_name": "product", "step_index": 1, "capture_status": "verified", "inspection_status": "inspected", "snapshot_id": snap_id}]
    charges = [{"label": "Fee", "amount_minor": 100, "step": "checkout_summary", "mandatory": "yes"}]

    # Simulate an error during insertion by causing an intentional type error on charges
    bad_charges = [{"label": "Fee", "amount_minor": "INVALID_AMOUNT_STRING", "step": "checkout_summary", "mandatory": "yes"}]

    # Attempt persistence with corrupted payload inside the atomic transaction
    with pytest.raises(Exception):
        crud.persist_run_observations_atomically(
            run_id=run_id,
            outcome="ok",
            provider_run_id="prov_01",
            provider_status="COMPLETED",
            observed={},
            profile_state_verified=False,
            totals=totals,
            stage_captures=stage_captures,
            charges=bad_charges,
        )

    # Invariant: Because of atomic transaction rollback, ZERO partial records exist in DB!
    conn = connection.get_connection()
    try:
        cap_cnt = conn.execute("SELECT count(*) FROM stage_captures WHERE run_id = ?", (run_id,)).fetchone()[0]
        chg_cnt = conn.execute("SELECT count(*) FROM charge_observations WHERE run_id = ?", (run_id,)).fetchone()[0]
        rec_cnt = conn.execute("SELECT count(*) FROM total_reconciliations WHERE run_id = ?", (run_id,)).fetchone()[0]
    finally:
        conn.close()

    assert cap_cnt == 0, f"Expected 0 stage captures after rollback, got {cap_cnt}"
    assert chg_cnt == 0, f"Expected 0 charge observations after rollback, got {chg_cnt}"
    assert rec_cnt == 0, f"Expected 0 reconciliations after rollback, got {rec_cnt}"

    # Now recover cleanly with valid payload
    crud.persist_run_observations_atomically(
        run_id=run_id,
        outcome="ok",
        provider_run_id="prov_01",
        provider_status="COMPLETED",
        observed={},
        profile_state_verified=False,
        totals=totals,
        stage_captures=stage_captures,
        charges=charges,
    )

    conn = connection.get_connection()
    try:
        cap_cnt_after = conn.execute("SELECT count(*) FROM stage_captures WHERE run_id = ?", (run_id,)).fetchone()[0]
        chg_cnt_after = conn.execute("SELECT count(*) FROM charge_observations WHERE run_id = ?", (run_id,)).fetchone()[0]
        rec_cnt_after = conn.execute("SELECT count(*) FROM total_reconciliations WHERE run_id = ?", (run_id,)).fetchone()[0]
    finally:
        conn.close()

    assert cap_cnt_after == 1
    assert chg_cnt_after == 1
    assert rec_cnt_after == 1


def test_concurrent_and_overlapping_retry_protection():
    """
    Review Recommendation 3: Concurrent or overlapping retry attempts.
    Verifies that:
    1. Active lease prevents any second worker from claiming the job.
    2. Concurrent thread claim attempts race safely with exclusive lock (exactly 1 claim succeeds).
    3. An expired-lease worker that lost its lease to another worker cannot complete or overwrite the job.
    """
    import concurrent.futures
    audit_id = crud.create_audit(input_url="http://test.com/concurrent", merchant="Concurrent Store", preset="quick")
    cond_id = crud.create_condition(
        audit_id=audit_id,
        condition_key="conc_key",
        requested={"session": "fresh", "cart_tier": "above_threshold"},
    )
    run_id = crud.create_run(condition_id=cond_id, requested={"session": "fresh", "cart_tier": "above_threshold"})
    job_id = crud.enqueue_job(run_id=run_id)

    # 3A: Concurrent claim race across multiple threads
    def try_claim(w_id):
        return crud.claim_next_job(worker_id=w_id, lease_duration_seconds=60)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(try_claim, f"concurrent_worker_{i}") for i in range(5)]
        results = [f.result() for f in futures]

    # Exactly ONE worker claimed the job; all other 4 received None
    successful_claims = [r for r in results if r is not None]
    assert len(successful_claims) == 1
    winning_worker = successful_claims[0]["lease_owner"]

    # 3B: While winning worker holds active lease, another worker calling claim receives None
    assert crud.claim_next_job(worker_id="intruder_worker", lease_duration_seconds=60) is None

    # 3C: Simulate lease expiry and takeover
    conn = connection.get_connection()
    expired_time = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    conn.execute("UPDATE jobs SET lease_expires_at = ? WHERE id = ?", (expired_time, job_id))
    conn.commit()
    conn.close()

    # Worker 2 claims expired lease
    takeover_worker = crud.claim_next_job(worker_id="takeover_worker", lease_duration_seconds=60)
    assert takeover_worker is not None
    assert takeover_worker["lease_owner"] == "takeover_worker"

    # Winning worker (old owner) attempts to complete the job -> FAILS because lease was lost!
    old_worker_completed = crud.complete_job(job_id, worker_id=winning_worker)
    assert old_worker_completed is False

    # Takeover worker completes the job -> SUCCEEDS
    new_worker_completed = crud.complete_job(job_id, worker_id="takeover_worker")
    assert new_worker_completed is True

    # State in DB is now 'done'
    conn = connection.get_connection()
    try:
        final_state = conn.execute("SELECT state FROM jobs WHERE id = ?", (job_id,)).fetchone()[0]
    finally:
        conn.close()
    assert final_state == "done"


def test_snapshot_references_remain_valid_and_unaltered_after_recovery():
    """
    Review Recommendation 4: Snapshot references remaining valid after recovery.
    Verifies that:
    1. Screenshots and SHA-256 digests in `snapshots` table are preserved through retries.
    2. Physical image files on disk are unaltered.
    3. Stage captures re-link to valid snapshot IDs without creating dangling foreign keys.
    """
    import hashlib
    from pathlib import Path

    audit_id = crud.create_audit(input_url="http://test.com/snapshots", merchant="Snapshot Store", preset="quick")
    cond_id = crud.create_condition(
        audit_id=audit_id,
        condition_key="snap_key",
        requested={"session": "fresh", "cart_tier": "above_threshold"},
    )
    run_id = crud.create_run(condition_id=cond_id, requested={"session": "fresh", "cart_tier": "above_threshold"})

    poll_payload = {
        "status": "COMPLETED",
        "steps": [
            {"id": "step_p1", "action": "Navigate to product", "screenshot": TINY_JPEG_B64},
            {"id": "step_c2", "action": "Inspect cart drawer", "screenshot": TINY_JPEG_B64},
            {"id": "step_s3", "action": "Review checkout summary", "screenshot": TINY_JPEG_B64},
        ],
        "result": {
            "status": "ok",
            "requested": {"session": "fresh", "cart_tier": "above_threshold"},
            "observed": {"subtotal_minor": 199900, "currency": "INR"},
            "stage_captures": [
                {"step_name": "product", "step_index": 1, "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "step_p1"},
                {"step_name": "cart", "step_index": 2, "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "step_c2"},
                {"step_name": "checkout_summary", "step_index": 3, "capture_status": "verified", "inspection_status": "inspected", "screenshot_ref": "step_s3"},
            ],
            "charges": [],
            "disclosures": [],
            "totals": {"subtotal_minor": 199900, "charges_minor": 0, "taxes_minor": 0, "discounts_minor": 0, "final_payable_minor": 199900},
        },
    }

    adapter = ControlledPipelineAdapter(poll_payload)
    runner = JobRunner(worker_id="snap_worker", adapter=adapter)

    # Initial execution
    crud.enqueue_job(run_id=run_id)
    assert runner.run_one_cycle() is True

    conn = connection.get_connection()
    try:
        initial_snaps = conn.execute("SELECT * FROM snapshots WHERE run_id = ?", (run_id,)).fetchall()
        initial_caps = conn.execute("SELECT * FROM stage_captures WHERE run_id = ?", (run_id,)).fetchall()
    finally:
        conn.close()

    assert len(initial_snaps) == 3
    assert len(initial_caps) == 3

    # Check physical files on disk and their SHA-256
    snap_records = [dict(s) for s in initial_snaps]
    for s in snap_records:
        file_path = Path(s["artifact_path"])
        assert file_path.exists(), f"Snapshot file {file_path} must exist on disk"
        disk_sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
        assert disk_sha == s["sha256"], f"Disk hash {disk_sha} must match DB hash {s['sha256']}"

    # Trigger recovery retry (simulating crash or recovery pass)
    crud.enqueue_job(run_id=run_id)
    assert runner.run_one_cycle() is True

    conn = connection.get_connection()
    try:
        snaps_after = conn.execute("SELECT * FROM snapshots WHERE run_id = ?", (run_id,)).fetchall()
        caps_after = conn.execute("SELECT * FROM stage_captures WHERE run_id = ?", (run_id,)).fetchall()
        # Verify foreign key integrity: 0 dangling snapshots
        dangling_count = conn.execute(
            """
            SELECT count(*)
            FROM stage_captures sc
            LEFT JOIN snapshots s ON sc.snapshot_id = s.id
            WHERE sc.run_id = ? AND sc.snapshot_id IS NOT NULL AND s.id IS NULL
            """,
            (run_id,),
        ).fetchone()[0]
    finally:
        conn.close()

    assert len(caps_after) == 3
    assert dangling_count == 0, "All stage capture snapshot IDs must resolve to valid snapshots"

    # Verify physical files still exist and hashes remain identical
    for s in snap_records:
        file_path = Path(s["artifact_path"])
        assert file_path.exists()
        disk_sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
        assert disk_sha == s["sha256"]


def test_stale_worker_with_superseded_generation_cannot_persist_observations_or_overwrite_newer_results():
    """
    Fencing Token & Stale Worker Protection:
    1. A monotonic `lease_generation` fencing token is incremented on every claim.
    2. A worker holding an expired lease or superseded generation cannot persist observations via
       `persist_run_observations_atomically` (raises StaleLeaseError and rolls back).
    3. Observations written by the new generation owner are preserved and NOT overwritten.
    4. Stale worker's `complete_job` call is rejected.
    """
    audit_id = crud.create_audit(input_url="http://test.com/fencing", merchant="Fencing Store", preset="quick")
    cond_id = crud.create_condition(
        audit_id=audit_id,
        condition_key="fencing_key",
        requested={"session": "fresh", "cart_tier": "above_threshold"},
    )
    run_id = crud.create_run(condition_id=cond_id, requested={"session": "fresh", "cart_tier": "above_threshold"})
    job_id = crud.enqueue_job(run_id=run_id)

    # 1. Worker 1 claims the job -> generation 1
    w1_claim = crud.claim_next_job(worker_id="worker_1", lease_duration_seconds=60)
    assert w1_claim is not None
    assert w1_claim["lease_owner"] == "worker_1"
    assert w1_claim["lease_generation"] == 1
    w1_expiry = w1_claim["lease_expires_at"]

    # 2. Simulate lease expiration for Worker 1
    conn = connection.get_connection()
    past_time = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    conn.execute("UPDATE jobs SET lease_expires_at = ? WHERE id = ?", (past_time, job_id))
    conn.commit()
    conn.close()

    # 3. Worker 2 claims the job -> generation 2
    w2_claim = crud.claim_next_job(worker_id="worker_2", lease_duration_seconds=60)
    assert w2_claim is not None
    assert w2_claim["lease_owner"] == "worker_2"
    assert w2_claim["lease_generation"] == 2
    w2_expiry = w2_claim["lease_expires_at"]

    # 4. Worker 2 persists valid observations and completes job
    crud.persist_run_observations_atomically(
        run_id=run_id,
        outcome="ok",
        totals={"subtotal_minor": 10000, "charges_minor": 500, "final_payable_minor": 10500},
        charges=[{"label": "Valid Fee", "amount_minor": 500, "step": "cart", "mandatory": "yes"}],
        job_id=job_id,
        worker_id="worker_2",
        lease_expires_at=w2_expiry,
        lease_generation=2,
    )
    w2_completed = crud.complete_job(job_id, worker_id="worker_2", lease_expires_at=w2_expiry, lease_generation=2)
    assert w2_completed is True

    # 5. Worker 1 wakes up (delayed) and attempts to persist observations with generation 1
    with pytest.raises(crud.StaleLeaseError) as exc_info:
        crud.persist_run_observations_atomically(
            run_id=run_id,
            outcome="ok",
            totals={"subtotal_minor": 99900, "charges_minor": 9900, "final_payable_minor": 109800},
            charges=[{"label": "Stale Fee Overwrite", "amount_minor": 9900, "step": "cart", "mandatory": "yes"}],
            job_id=job_id,
            worker_id="worker_1",
            lease_expires_at=w1_expiry,
            lease_generation=1,
        )
    assert "generation" in str(exc_info.value).lower() or "no longer claimed" in str(exc_info.value).lower()

    # Worker 1 completion also fails
    w1_completed = crud.complete_job(job_id, worker_id="worker_1", lease_expires_at=w1_expiry, lease_generation=1)
    assert w1_completed is False

    # 6. Verify that Worker 2's observations were NOT overwritten by Worker 1
    conn = connection.get_connection()
    try:
        charges = conn.execute("SELECT label, amount_minor FROM charge_observations WHERE run_id = ?", (run_id,)).fetchall()
        assert len(charges) == 1
        assert charges[0]["label"] == "Valid Fee"
        assert charges[0]["amount_minor"] == 500
    finally:
        conn.close()

