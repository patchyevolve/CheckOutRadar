"""Typed Database Operations for Checkout Radar."""

import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
import sqlite3
from .connection import get_connection


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# -------------------------------------------------------------
# Audits, Conditions, Runs
# -------------------------------------------------------------

def create_audit(
    input_url: str,
    merchant: str,
    preset: str = "quick",
    cart_recipe: Optional[Dict[str, Any]] = None,
    schedule_interval: Optional[int] = None,
) -> str:
    audit_id = f"aud_{uuid.uuid4().hex[:12]}"
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO audits (id, input_url, merchant, cart_recipe, preset, schedule_interval, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                audit_id,
                input_url,
                merchant,
                json.dumps(cart_recipe) if cart_recipe else None,
                preset,
                schedule_interval,
                utc_now(),
            ),
        )
        conn.commit()
        return audit_id
    finally:
        conn.close()


def get_audit(audit_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM audits WHERE id = ?", (audit_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        if data.get("cart_recipe"):
            data["cart_recipe"] = json.loads(data["cart_recipe"])
        return data
    finally:
        conn.close()


def update_audit_status(audit_id: str, status: str):
    conn = get_connection()
    try:
        conn.execute("UPDATE audits SET status = ? WHERE id = ?", (status, audit_id))
        conn.commit()
    finally:
        conn.close()


def create_condition(
    audit_id: str,
    condition_key: str,
    requested: Dict[str, Any],
    is_reference: bool = False,
    supported: bool = True,
) -> str:
    cond_id = f"cond_{uuid.uuid4().hex[:12]}"
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO conditions (id, audit_id, condition_key, requested, is_reference, supported)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (cond_id, audit_id, condition_key, json.dumps(requested), int(is_reference), int(supported)),
        )
        conn.commit()
        return cond_id
    finally:
        conn.close()


def get_conditions_for_audit(audit_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM conditions WHERE audit_id = ?", (audit_id,)).fetchall()
        res = []
        for r in rows:
            d = dict(r)
            d["requested"] = json.loads(d["requested"])
            res.append(d)
        return res
    finally:
        conn.close()


def create_run(
    condition_id: str,
    requested: Dict[str, Any],
    attempt: int = 1,
    profile_id: Optional[str] = None,
) -> str:
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO runs (id, condition_id, attempt, requested, profile_id, started_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, condition_id, attempt, json.dumps(requested), profile_id, utc_now()),
        )
        conn.commit()
        return run_id
    finally:
        conn.close()


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["requested"] = json.loads(d["requested"]) if d.get("requested") else {}
        d["observed"] = json.loads(d["observed"]) if d.get("observed") else None
        return d
    finally:
        conn.close()


def update_run_outcome(
    run_id: str,
    provider_run_id: Optional[str],
    provider_status: str,
    outcome: str,
    observed: Optional[Dict[str, Any]],
    profile_state_verified: bool = False,
):
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE runs
            SET provider_run_id = coalesce(?, provider_run_id),
                provider_status = ?,
                outcome = ?,
                observed = ?,
                profile_state_verified = ?,
                finished_at = ?
            WHERE id = ?
            """,
            (
                provider_run_id,
                provider_status,
                outcome,
                json.dumps(observed) if observed else None,
                int(profile_state_verified),
                utc_now(),
                run_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# -------------------------------------------------------------
# Durable Jobs & Lease Management
# -------------------------------------------------------------

def enqueue_job(run_id: str) -> str:
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO jobs (id, run_id, state) VALUES (?, ?, 'queued')",
            (job_id, run_id),
        )
        conn.commit()
        return job_id
    finally:
        conn.close()


def claim_next_job(worker_id: str, lease_duration_seconds: int = 120) -> Optional[Dict[str, Any]]:
    """Atomically claim the next queued or expired-lease job."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        now = utc_now()
        new_lease_expiry = (datetime.now(timezone.utc) + timedelta(seconds=lease_duration_seconds)).isoformat()

        # Find candidate job: either state='queued' or (state='claimed' AND lease_expires_at < now)
        cursor.execute(
            """
            SELECT j.*, r.condition_id, r.provider_run_id, c.audit_id, c.condition_key, c.requested
            FROM jobs j
            JOIN runs r ON j.run_id = r.id
            JOIN conditions c ON r.condition_id = c.id
            WHERE (j.state = 'queued')
               OR (j.state = 'claimed' AND j.lease_expires_at IS NOT NULL AND j.lease_expires_at < ?)
               OR (j.state = 'retry_wait')
            ORDER BY j.retries ASC, j.id ASC
            LIMIT 1
            """,
            (now,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        job_data = dict(row)
        cursor.execute(
            """
            UPDATE jobs
            SET state = 'claimed',
                lease_owner = ?,
                lease_expires_at = ?
            WHERE id = ?
            """,
            (worker_id, new_lease_expiry, job_data["id"]),
        )
        conn.commit()
        job_data["lease_owner"] = worker_id
        job_data["lease_expires_at"] = new_lease_expiry
        job_data["requested"] = json.loads(job_data["requested"])
        return job_data
    finally:
        conn.close()


def complete_job(job_id: str):
    conn = get_connection()
    try:
        conn.execute("UPDATE jobs SET state = 'done', lease_expires_at = NULL WHERE id = ?", (job_id,))
        conn.commit()
    finally:
        conn.close()


def fail_or_retry_job(job_id: str, error_message: str, max_retries: int = 2):
    conn = get_connection()
    try:
        row = conn.execute("SELECT run_id, retries FROM jobs WHERE id = ?", (job_id,)).fetchone()
        retries = row["retries"] if row else 0
        run_id = row["run_id"] if row else None
        if retries < max_retries:
            conn.execute(
                """
                UPDATE jobs
                SET state = 'retry_wait',
                    retries = retries + 1,
                    last_error = ?,
                    lease_expires_at = NULL
                WHERE id = ?
                """,
                (error_message, job_id),
            )
        else:
            conn.execute(
                """
                UPDATE jobs
                SET state = 'dead',
                    last_error = ?,
                    lease_expires_at = NULL
                WHERE id = ?
                """,
                (error_message, job_id),
            )
            if run_id:
                conn.execute(
                    """
                    UPDATE runs
                    SET outcome = 'failed',
                        provider_status = 'FAILED'
                    WHERE id = ?
                    """,
                    (run_id,),
                )
        conn.commit()
    finally:
        conn.close()


# -------------------------------------------------------------
# Provider Calls Audit Log
# -------------------------------------------------------------

def log_provider_call(
    audit_id: str,
    operation: str,
    run_id: Optional[str] = None,
    provider_request_id: Optional[str] = None,
    response_status: Optional[int] = None,
    error_class: Optional[str] = None,
    result_usable: bool = True,
    requested_at: Optional[str] = None,
) -> str:
    call_id = f"pcall_{uuid.uuid4().hex[:12]}"
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO provider_calls (
                id, audit_id, run_id, operation, requested_at, completed_at,
                provider_request_id, response_status, error_class, result_usable
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                call_id,
                audit_id,
                run_id,
                operation,
                requested_at or utc_now(),
                utc_now(),
                provider_request_id,
                response_status,
                error_class,
                int(result_usable),
            ),
        )
        conn.commit()
        return call_id
    finally:
        conn.close()


def get_provider_calls_for_audit(audit_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM provider_calls WHERE audit_id = ? ORDER BY requested_at ASC",
            (audit_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# -------------------------------------------------------------
# Evidence, Stage Captures & Observations
# -------------------------------------------------------------

def create_snapshot(
    run_id: str,
    step_name: str,
    artifact_path: str,
    sha256: str,
    redaction_status: str = "redacted",
) -> str:
    snap_id = f"snap_{uuid.uuid4().hex[:12]}"
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO snapshots (id, run_id, step_name, artifact_path, sha256, redaction_status, captured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (snap_id, run_id, step_name, artifact_path, sha256, redaction_status, utc_now()),
        )
        conn.commit()
        return snap_id
    finally:
        conn.close()


def create_stage_capture(
    run_id: str,
    step_name: str,
    step_index: int,
    provider_step_id: Optional[str] = None,
    capture_status: str = "verified",
    inspection_status: str = "inspected",
    snapshot_id: Optional[str] = None,
) -> str:
    cap_id = f"cap_{uuid.uuid4().hex[:12]}"
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO stage_captures (
                id, run_id, step_name, step_index, provider_step_id, capture_status, inspection_status, snapshot_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (cap_id, run_id, step_name, step_index, provider_step_id, capture_status, inspection_status, snapshot_id),
        )
        conn.commit()
        return cap_id
    finally:
        conn.close()


def insert_charge_observation(
    run_id: str,
    step_index: int,
    label: str,
    canonical_label: str,
    amount_minor: int,
    step: str,
    mandatory: str = "yes",
    currency: str = "INR",
    stage_capture_id: Optional[str] = None,
) -> str:
    obs_id = f"chg_{uuid.uuid4().hex[:12]}"
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO charge_observations (
                id, run_id, stage_capture_id, step_index, label, canonical_label, amount_minor, currency, step, mandatory
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (obs_id, run_id, stage_capture_id, step_index, label, canonical_label, amount_minor, currency, step, mandatory),
        )
        conn.commit()
        return obs_id
    finally:
        conn.close()


def insert_disclosure_observation(
    run_id: str,
    charge_label: str,
    step: str,
    state: str,
    visible_text: Optional[str] = None,
    amount_minor: Optional[int] = None,
    condition_text: Optional[str] = None,
    stage_capture_id: Optional[str] = None,
) -> str:
    obs_id = f"disc_{uuid.uuid4().hex[:12]}"
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO disclosure_observations (
                id, run_id, stage_capture_id, charge_label, step, state, visible_text, amount_minor, condition_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (obs_id, run_id, stage_capture_id, charge_label, step, state, visible_text, amount_minor, condition_text),
        )
        conn.commit()
        return obs_id
    finally:
        conn.close()


def insert_addon_observation(
    run_id: str,
    label: str,
    amount_minor: int,
    default_selected: bool,
    user_modified: bool = False,
    in_total: bool = True,
    step: str = "cart",
    stage_capture_id: Optional[str] = None,
) -> str:
    obs_id = f"add_{uuid.uuid4().hex[:12]}"
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO addon_observations (
                id, run_id, stage_capture_id, label, amount_minor, default_selected, user_modified, in_total, step
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (obs_id, run_id, stage_capture_id, label, amount_minor, int(default_selected), int(user_modified), int(in_total), step),
        )
        conn.commit()
        return obs_id
    finally:
        conn.close()


def insert_urgency_observation(
    run_id: str,
    text: str,
    type_: str,
    claimed_deadline: Optional[str] = None,
    observed_seconds_remaining: Optional[int] = None,
    step: str = "product",
    stage_capture_id: Optional[str] = None,
) -> str:
    obs_id = f"urg_{uuid.uuid4().hex[:12]}"
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO urgency_observations (
                id, run_id, stage_capture_id, text, type, claimed_deadline, observed_seconds_remaining, step
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (obs_id, run_id, stage_capture_id, text, type_, claimed_deadline, observed_seconds_remaining, step),
        )
        conn.commit()
        return obs_id
    finally:
        conn.close()


def insert_reconciliation(
    run_id: str,
    subtotal_minor: int,
    charges_minor: int,
    taxes_minor: int,
    discounts_minor: int,
    final_payable_minor: int,
) -> bool:
    from ..analysis.reconciler import reconcile_totals
    is_reconciled, _, detail = reconcile_totals(
        subtotal_minor=subtotal_minor,
        charges_minor=charges_minor,
        taxes_minor=taxes_minor,
        discounts_minor=discounts_minor,
        final_payable_minor=final_payable_minor,
    )
    calculated = detail["calculated_final_payable_minor"]
    rec_id = f"rec_{uuid.uuid4().hex[:12]}"
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO total_reconciliations (
                id, run_id, subtotal_minor, charges_minor, taxes_minor, discounts_minor,
                final_payable_minor, calculated_payable_minor, is_reconciled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (rec_id, run_id, subtotal_minor, charges_minor, taxes_minor, discounts_minor, final_payable_minor, calculated, int(is_reconciled)),
        )
        conn.commit()
        return is_reconciled
    finally:
        conn.close()


# -------------------------------------------------------------
# Diffs & Findings
# -------------------------------------------------------------

def insert_diff(
    audit_id: str,
    diff_type: str,
    run_a_id: str,
    run_b_id: Optional[str],
    matching_key: str,
    detail: Dict[str, Any],
    dedup_key: str,
) -> str:
    diff_id = f"diff_{uuid.uuid4().hex[:12]}"
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO diffs (id, audit_id, type, run_a_id, run_b_id, matching_key, detail, dedup_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (diff_id, audit_id, diff_type, run_a_id, run_b_id, matching_key, json.dumps(detail), dedup_key),
        )
        conn.commit()
        # Retrieve actual id if already existed
        row = conn.execute("SELECT id FROM diffs WHERE dedup_key = ?", (dedup_key,)).fetchone()
        return row["id"] if row else diff_id
    finally:
        conn.close()


def insert_finding(
    audit_id: str,
    category: str,
    severity: str,
    confidence: float,
    explanation: str,
    evidence_ids: List[str],
    source: str,
    dedup_key: str,
    diff_id: Optional[str] = None,
    heuristic_note: Optional[str] = None,
    raw_observations: Optional[Dict[str, Any]] = None,
) -> str:
    finding_id = f"find_{uuid.uuid4().hex[:12]}"
    conn = get_connection()
    try:
        raw_obs_json = json.dumps(raw_observations) if raw_observations else None
        conn.execute(
            """
            INSERT OR IGNORE INTO findings (
                id, audit_id, diff_id, category, severity, confidence, explanation,
                evidence_ids, source, dedup_key, heuristic_note, raw_observations
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                finding_id,
                audit_id,
                diff_id,
                category,
                severity,
                confidence,
                explanation,
                json.dumps(evidence_ids),
                source,
                dedup_key,
                heuristic_note,
                raw_obs_json,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT id FROM findings WHERE dedup_key = ?", (dedup_key,)).fetchone()
        return row["id"] if row else finding_id
    finally:
        conn.close()


def get_diffs_for_audit(audit_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM diffs WHERE audit_id = ?", (audit_id,)).fetchall()
        res = []
        for r in rows:
            d = dict(r)
            d["detail"] = json.loads(d["detail"])
            res.append(d)
        return res
    finally:
        conn.close()


def get_findings_for_audit(audit_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM findings WHERE audit_id = ?", (audit_id,)).fetchall()
        res = []
        for r in rows:
            d = dict(r)
            d["evidence_ids"] = json.loads(d["evidence_ids"])
            if "raw_observations" in d and d["raw_observations"]:
                try:
                    d["raw_observations"] = json.loads(d["raw_observations"])
                except Exception:
                    pass
            res.append(d)
        return res
    finally:
        conn.close()


# -------------------------------------------------------------
# Persisted Progress Stream (SSE Events)
# -------------------------------------------------------------

def emit_event(audit_id: str, event_type: str, payload: Dict[str, Any]):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT coalesce(max(seq), 0) + 1 as next_seq FROM events WHERE audit_id = ?", (audit_id,))
        seq = cur.fetchone()["next_seq"]
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO events (id, audit_id, seq, type, payload, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, audit_id, seq, event_type, json.dumps(payload), utc_now()),
        )
        conn.commit()
    finally:
        conn.close()


def get_events_for_audit(audit_id: str, after_seq: int = 0) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM events WHERE audit_id = ? AND seq > ? ORDER BY seq ASC",
            (audit_id, after_seq),
        ).fetchall()
        res = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            res.append(d)
        return res
    finally:
        conn.close()
