"""Unit tests for Durable Job Table and Lease Recovery."""

import pytest
from datetime import datetime, timezone, timedelta
from app.db import crud, connection
from app.worker.job_runner import JobRunner


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    test_db = tmp_path / "test_lease.db"
    monkeypatch.setenv("SQLITE_DB_PATH", str(test_db))
    monkeypatch.setenv("MOCK_TINYFISH", "true")
    connection.init_db()


def test_job_lease_claim_and_recovery():
    audit_id = crud.create_audit(input_url="http://test.com", merchant="Test", preset="quick")
    cond_id = crud.create_condition(
        audit_id=audit_id,
        condition_key="test_key",
        requested={"session": "fresh", "cart_tier": "above_threshold"},
    )
    run_id = crud.create_run(condition_id=cond_id, requested={"session": "fresh", "cart_tier": "above_threshold"})
    job_id = crud.enqueue_job(run_id=run_id)

    # Worker 1 claims job
    claimed_1 = crud.claim_next_job(worker_id="worker_1", lease_duration_seconds=60)
    assert claimed_1 is not None
    assert claimed_1["id"] == job_id
    assert claimed_1["lease_owner"] == "worker_1"

    # Worker 2 tries to claim while lease is active -> None
    claimed_2 = crud.claim_next_job(worker_id="worker_2", lease_duration_seconds=60)
    assert claimed_2 is None

    # Simulate lease expiry by backdating lease_expires_at in SQLite
    conn = connection.get_connection()
    expired_time = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    conn.execute("UPDATE jobs SET lease_expires_at = ? WHERE id = ?", (expired_time, job_id))
    conn.commit()
    conn.close()

    # Worker 2 can now claim the expired lease!
    claimed_3 = crud.claim_next_job(worker_id="worker_2", lease_duration_seconds=60)
    assert claimed_3 is not None
    assert claimed_3["id"] == job_id
    assert claimed_3["lease_owner"] == "worker_2"


def test_lease_recovery_avoids_duplicate_agent_submission():
    """
    On lease expiry or restart, if run already has a provider_run_id,
    the job processor must NOT call submit_agent_run again!
    """
    audit_id = crud.create_audit(input_url="http://test.com", merchant="Test", preset="quick")
    cond_id = crud.create_condition(
        audit_id=audit_id,
        condition_key="test_key",
        requested={"session": "fresh", "cart_tier": "above_threshold"},
    )
    run_id = crud.create_run(condition_id=cond_id, requested={"session": "fresh", "cart_tier": "above_threshold"})
    job_id = crud.enqueue_job(run_id=run_id)

    # Set existing provider_run_id on the run (simulating crash after submit)
    crud.update_run_outcome(
        run_id=run_id,
        provider_run_id="mock_run_existing_123",
        provider_status="RUNNING",
        outcome="ok",
        observed=None,
    )

    runner = JobRunner(worker_id="recovering_worker")
    # Pre-register mock run in adapter
    runner.adapter._runs["mock_run_existing_123"] = {
        "variant": "clean",
        "goal": "Test goal",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
    }

    # Execute cycle
    processed = runner.run_one_cycle()
    assert processed is True

    # Check provider calls: there should be NO agent_submit call during this cycle!
    calls = crud.get_provider_calls_for_audit(audit_id)
    submit_calls = [c for c in calls if c["operation"] == "agent_submit"]
    assert len(submit_calls) == 0, "Duplicate agent_submit occurred during lease recovery!"

    # Verify run completed successfully
    run_after = crud.get_run(run_id)
    assert run_after["outcome"] == "ok"
