-- Checkout Radar Database Schema (SQLite)
-- Append-only evidence store, typed observation events, durable jobs, provider calls log

CREATE TABLE IF NOT EXISTS audits (
    id TEXT PRIMARY KEY,
    input_url TEXT NOT NULL,
    merchant TEXT NOT NULL,
    cart_recipe TEXT, -- JSON
    preset TEXT NOT NULL DEFAULT 'quick', -- quick, full
    schedule_interval INTEGER DEFAULT NULL,
    status TEXT NOT NULL DEFAULT 'pending', -- pending, running, partial, complete, failed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conditions (
    id TEXT PRIMARY KEY,
    audit_id TEXT NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
    condition_key TEXT NOT NULL, -- Stable key: pincode:session:tier
    requested TEXT NOT NULL, -- JSON
    is_reference BOOLEAN NOT NULL DEFAULT 0,
    supported BOOLEAN NOT NULL DEFAULT 1,
    UNIQUE(audit_id, condition_key)
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    condition_id TEXT NOT NULL REFERENCES conditions(id) ON DELETE CASCADE,
    attempt INTEGER NOT NULL DEFAULT 1,
    provider_run_id TEXT DEFAULT NULL,
    provider_status TEXT DEFAULT 'PENDING', -- PENDING, RUNNING, COMPLETED, FAILED, CANCELLED
    outcome TEXT DEFAULT 'ok', -- ok, blocked_by_login, blocked_by_bot, condition_not_applied, extraction_inconsistent, unsupported, failed
    profile_id TEXT DEFAULT NULL,
    profile_state_verified BOOLEAN DEFAULT 0,
    requested TEXT NOT NULL, -- JSON
    observed TEXT DEFAULT NULL, -- JSON
    started_at TIMESTAMP DEFAULT NULL,
    finished_at TIMESTAMP DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    state TEXT NOT NULL DEFAULT 'queued', -- queued, claimed, done, retry_wait, dead
    lease_owner TEXT DEFAULT NULL,
    lease_expires_at TIMESTAMP DEFAULT NULL,
    last_error TEXT DEFAULT NULL,
    retries INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS provider_calls (
    id TEXT PRIMARY KEY,
    audit_id TEXT NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
    run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
    operation TEXT NOT NULL, -- search, fetch, agent_submit, agent_poll, screenshot
    requested_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP DEFAULT NULL,
    provider_request_id TEXT DEFAULT NULL,
    response_status INTEGER DEFAULT NULL,
    error_class TEXT DEFAULT NULL,
    result_usable BOOLEAN NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS fetches (
    id TEXT PRIMARY KEY,
    audit_id TEXT NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    ttl INTEGER NOT NULL DEFAULT 0,
    cache_status TEXT NOT NULL DEFAULT 'miss', -- hit, miss, bypass
    retrieved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    content_ref TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    step_name TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    redaction_status TEXT NOT NULL DEFAULT 'redacted', -- redacted, raw_clean
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    schema_version TEXT NOT NULL DEFAULT 'v1'
);

CREATE TABLE IF NOT EXISTS stage_captures (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    step_name TEXT NOT NULL, -- product, cart, checkout_summary
    step_index INTEGER NOT NULL,
    provider_step_id TEXT DEFAULT NULL,
    capture_status TEXT NOT NULL DEFAULT 'verified', -- verified, failed, incomplete
    inspection_status TEXT NOT NULL DEFAULT 'inspected', -- inspected, uninspected
    snapshot_id TEXT REFERENCES snapshots(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS charge_observations (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    stage_capture_id TEXT REFERENCES stage_captures(id) ON DELETE SET NULL,
    step_index INTEGER NOT NULL,
    label TEXT NOT NULL,
    canonical_label TEXT NOT NULL, -- handling, delivery, platform, small_cart, surge, packaging, other
    amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'INR',
    step TEXT NOT NULL, -- product, cart, checkout_summary
    mandatory TEXT NOT NULL DEFAULT 'yes' -- yes, no, unknown
);

CREATE TABLE IF NOT EXISTS disclosure_observations (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    stage_capture_id TEXT REFERENCES stage_captures(id) ON DELETE SET NULL,
    charge_label TEXT NOT NULL,
    step TEXT NOT NULL, -- product, cart, checkout_summary
    state TEXT NOT NULL, -- observed, not_observed_verified, unknown
    visible_text TEXT DEFAULT NULL,
    amount_minor INTEGER DEFAULT NULL,
    condition_text TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS addon_observations (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    stage_capture_id TEXT REFERENCES stage_captures(id) ON DELETE SET NULL,
    label TEXT NOT NULL,
    amount_minor INTEGER NOT NULL,
    default_selected BOOLEAN NOT NULL DEFAULT 1,
    user_modified BOOLEAN NOT NULL DEFAULT 0,
    in_total BOOLEAN NOT NULL DEFAULT 1,
    step TEXT NOT NULL DEFAULT 'cart'
);

CREATE TABLE IF NOT EXISTS urgency_observations (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    stage_capture_id TEXT REFERENCES stage_captures(id) ON DELETE SET NULL,
    text TEXT NOT NULL,
    type TEXT NOT NULL, -- countdown, scarcity, social_proof
    claimed_deadline TEXT DEFAULT NULL,
    observed_seconds_remaining INTEGER DEFAULT NULL,
    step TEXT NOT NULL DEFAULT 'product'
);

CREATE TABLE IF NOT EXISTS total_reconciliations (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    subtotal_minor INTEGER NOT NULL,
    charges_minor INTEGER NOT NULL,
    taxes_minor INTEGER NOT NULL DEFAULT 0,
    discounts_minor INTEGER NOT NULL DEFAULT 0,
    final_payable_minor INTEGER NOT NULL,
    calculated_payable_minor INTEGER NOT NULL,
    is_reconciled BOOLEAN NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS diffs (
    id TEXT PRIMARY KEY,
    audit_id TEXT NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
    type TEXT NOT NULL, -- PRICE_VARIANCE, LATE_DISCLOSURE, UNDISCLOSED_AT_STAGE, SMALL_CART_RULE, TEMPORAL_DRIFT
    run_a_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    run_b_id TEXT REFERENCES runs(id) ON DELETE CASCADE,
    matching_key TEXT NOT NULL,
    detail TEXT NOT NULL, -- JSON
    dedup_key TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    audit_id TEXT NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
    diff_id TEXT REFERENCES diffs(id) ON DELETE CASCADE,
    category TEXT NOT NULL, -- drip_pricing, basket_sneaking, false_urgency
    severity TEXT NOT NULL, -- low, medium, high
    confidence REAL NOT NULL,
    explanation TEXT NOT NULL,
    evidence_ids TEXT NOT NULL, -- JSON array of snapshot/observation IDs
    source TEXT NOT NULL, -- rule, llm
    dedup_key TEXT NOT NULL UNIQUE,
    heuristic_note TEXT DEFAULT NULL,
    raw_observations TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    audit_id TEXT NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    type TEXT NOT NULL, -- audit_started, run_started, run_completed, diff_found, finding_flagged, audit_completed
    payload TEXT NOT NULL, -- JSON
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    audit_id TEXT NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
    finding_id TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    acknowledged BOOLEAN NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_runs_condition ON runs(condition_id);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_charge_obs_run ON charge_observations(run_id);
CREATE INDEX IF NOT EXISTS idx_disclosure_obs_run ON disclosure_observations(run_id);
CREATE INDEX IF NOT EXISTS idx_diffs_audit ON diffs(audit_id);
CREATE INDEX IF NOT EXISTS idx_findings_audit ON findings(audit_id);
CREATE INDEX IF NOT EXISTS idx_events_audit_seq ON events(audit_id, seq);
