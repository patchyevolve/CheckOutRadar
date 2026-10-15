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


def test_legacy_database_migration_adds_lease_generation_idempotently(tmp_path, monkeypatch):
    """
    Validates that:
    1. An existing database created without `lease_generation` is safely upgraded by `connection.init_db()`.
    2. Existing rows have `lease_generation` defaulted to 0 without data loss.
    3. `init_db()` is idempotent and safe to run repeatedly on upgraded or existing databases.
    4. Workers can immediately claim legacy jobs and increment `lease_generation` to 1.
    """
    import sqlite3
    legacy_db = tmp_path / "legacy_migration.db"
    monkeypatch.setenv("SQLITE_DB_PATH", str(legacy_db))

    from pathlib import Path
    schema_path = Path(__file__).parent.parent / "app" / "db" / "schema.sql"
    with open(schema_path, "r", encoding="utf-8") as f:
        legacy_sql = f.read().replace("lease_generation INTEGER NOT NULL DEFAULT 0,", "")

    conn = sqlite3.connect(str(legacy_db))
    conn.executescript(legacy_sql)
    conn.execute("INSERT INTO audits (id, input_url, merchant, preset, status, created_at) VALUES ('aud_leg', 'http://legacy.test', 'Legacy Merchant', 'quick', 'pending', '2026-10-15T00:00:00Z');")
    conn.execute("INSERT INTO conditions (id, audit_id, condition_key, requested) VALUES ('cond_leg', 'aud_leg', 'key_1', '{\"session\": \"fresh\"}');")
    conn.execute("INSERT INTO runs (id, condition_id, requested) VALUES ('run_leg', 'cond_leg', '{\"session\": \"fresh\"}');")
    conn.execute("INSERT INTO jobs (id, run_id, state) VALUES ('job_leg_1', 'run_leg', 'queued');")
    conn.commit()
    conn.close()

    # Verify initial schema lacks lease_generation
    conn = sqlite3.connect(str(legacy_db))
    cols_before = [c[1] for c in conn.execute("PRAGMA table_info(jobs)").fetchall()]
    assert "lease_generation" not in cols_before
    conn.close()

    # Pass 1: Run init_db() to execute live migration
    connection.init_db()

    conn = sqlite3.connect(str(legacy_db))
    cols_after = [c[1] for c in conn.execute("PRAGMA table_info(jobs)").fetchall()]
    assert "lease_generation" in cols_after
    row = conn.execute("SELECT id, state, lease_generation FROM jobs WHERE id = 'job_leg_1'").fetchone()
    assert row[0] == "job_leg_1"
    assert row[1] == "queued"
    assert row[2] == 0
    conn.close()

    # Pass 2 & 3: Run init_db() repeatedly to verify idempotency
    connection.init_db()
    connection.init_db()

    # Verify worker can claim the upgraded legacy job and bump generation to 1
    claimed = crud.claim_next_job(worker_id="upgrade_worker", lease_duration_seconds=60)
    assert claimed is not None
    assert claimed["id"] == "job_leg_1"
    assert claimed["lease_generation"] == 1
    assert claimed["lease_owner"] == "upgrade_worker"
