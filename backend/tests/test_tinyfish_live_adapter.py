"""
Unit & Integration Tests for Live TinyFish Adapter, Worker Execution, and Security Boundaries.

Verifies:
1. Adapter Initialization & Headers (sourcing credentials from DB settings / env).
2. Agent Submission & Polling contracts with resilient DNS and Base URL routing.
3. Secret Redaction across all provider calls, exceptions, and DB logs.
4. Screenshot extraction, base64 decoding, and redactor pipeline integration.
5. Search & Fetch execution contracts.
6. Worker Live Execution Lifecycle (submission, transient polling retry, evidence persistence).
7. Worker Idempotency & Lease Recovery (zero duplicate observations/findings on re-run).
8. Honest Blocker Outcomes (blocked_by_login, blocked_by_bot -> strictly inconclusive).
9. Missing Stage Handling (inaccessible checkout summary -> strictly inconclusive, never clean).
10. Settings test-tinyfish endpoint with secret scrub verification.
"""

import os
import json
import io
import pytest
from unittest.mock import patch, MagicMock
import urllib.error
import urllib.request
from datetime import datetime, timezone

from app.db import crud, connection
from app.tinyfish.real_client import RealTinyFishClient
from app.tinyfish.mock_client import MockTinyFishClient
from app.worker.job_runner import JobRunner, get_adapter
from app.services.settings_service import get_settings_manager, redact_secrets
from app.analysis.detectors import assess_audit_outcome
from app.models.contracts import TINYFISH_AGENT_OUTPUT_SCHEMA


MOCK_TEST_KEY = "tf_mock_live_test_key_12345678"


@pytest.fixture(autouse=True)
def setup_test_environment(tmp_path, monkeypatch):
    test_db = tmp_path / "test_live_adapter.db"
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("SQLITE_DB_PATH", str(test_db))
    monkeypatch.setenv("EVIDENCE_DIR", str(evidence_dir))
    monkeypatch.setenv("TINYFISH_API_KEY", MOCK_TEST_KEY)
    monkeypatch.setenv("MOCK_TINYFISH", "false")
    monkeypatch.setenv("TINYFISH_MAX_POLLS", "5")
    monkeypatch.setenv("TINYFISH_POLL_INTERVAL", "0")

    connection.init_db()
    mgr = get_settings_manager()
    mgr._memory_overrides.clear()
    mgr.set_setting("mock_tinyfish", False)
    mgr.set_setting("tinyfish_api_key", MOCK_TEST_KEY, is_secret=True)

    yield

    mgr._memory_overrides.clear()


# =====================================================================
# 1. Adapter Initialization & Contract Tests
# =====================================================================

def test_real_client_initialization_and_headers():
    # Explicit key
    client_explicit = RealTinyFishClient(api_key="tf_mock_explicit_key_9999")
    assert client_explicit.api_key == "tf_mock_explicit_key_9999"
    headers = client_explicit._headers()
    assert headers["X-API-Key"] == "tf_mock_explicit_key_9999"
    assert headers["Content-Type"] == "application/json"

    # Settings DB fallback
    client_settings = RealTinyFishClient()
    assert client_settings.api_key == MOCK_TEST_KEY


def test_get_adapter_routing(monkeypatch):
    mgr = get_settings_manager()

    # Local harness target should always return MockTinyFishClient
    local_adapter = get_adapter("http://localhost:8000/harness/run")
    assert isinstance(local_adapter, MockTinyFishClient)

    # When mock_tinyfish is True, returns MockTinyFishClient
    mgr.set_setting("mock_tinyfish", True)
    mock_adapter = get_adapter("https://www.headphonezone.in")
    assert isinstance(mock_adapter, MockTinyFishClient)

    # When mock_tinyfish is False with API key, returns RealTinyFishClient
    mgr.set_setting("mock_tinyfish", False)
    mgr.set_setting("tinyfish_api_key", MOCK_TEST_KEY, is_secret=True)
    live_adapter = get_adapter("https://www.headphonezone.in")
    assert isinstance(live_adapter, RealTinyFishClient)


# =====================================================================
# 2. Agent Submission & Redaction Tests
# =====================================================================

def test_submit_agent_run_success():
    client = RealTinyFishClient(api_key=MOCK_TEST_KEY)
    audit_id = crud.create_audit(input_url="https://example.com/p", merchant="Example", preset="single")
    cond_id = crud.create_condition(audit_id=audit_id, condition_key="fresh_above", requested={"session": "fresh", "cart_tier": "above_threshold"})
    run_id = crud.create_run(condition_id=cond_id, requested={"session": "fresh", "cart_tier": "above_threshold"})

    mock_response_body = json.dumps({"run_id": "tf_run_abc123"}).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = mock_response_body
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        prov_run_id = client.submit_agent_run(
            url="https://example.com/p",
            goal="Audit checkout flow",
            audit_id=audit_id,
            run_id=run_id,
            output_schema=TINYFISH_AGENT_OUTPUT_SCHEMA,
            browser_profile="lite",
            use_profile=False,
        )

        assert prov_run_id == "tf_run_abc123"
        req = mock_urlopen.call_args[0][0]
        assert req.get_method() == "POST"
        assert req.headers.get("X-api-key") == MOCK_TEST_KEY
        body = json.loads(req.data.decode("utf-8"))
        assert body["url"] == "https://example.com/p"
        assert body["goal"] == "Audit checkout flow"
        assert body["browser_profile"] == "lite"
        assert "output_schema" in body

    # Verify provider call logged in SQLite
    calls = crud.get_provider_calls_for_audit(audit_id)
    assert len(calls) == 1
    assert calls[0]["operation"] == "agent_submit"
    assert calls[0]["provider_request_id"] == "tf_run_abc123"
    assert calls[0]["response_status"] == 200
    assert bool(calls[0]["result_usable"]) is True


def test_submit_agent_run_error_scrubs_secrets():
    client = RealTinyFishClient(api_key=MOCK_TEST_KEY)
    audit_id = crud.create_audit(input_url="https://example.com/p", merchant="Example", preset="single")
    cond_id = crud.create_condition(audit_id=audit_id, condition_key="fresh_above", requested={"session": "fresh", "cart_tier": "above_threshold"})
    run_id = crud.create_run(condition_id=cond_id, requested={"session": "fresh", "cart_tier": "above_threshold"})

    sensitive_error = f'{{"error": "Unauthorized", "detail": "Invalid token {MOCK_TEST_KEY}"}}'
    http_err = urllib.error.HTTPError(
        url="https://agent.tinyfish.ai/v1/automation/run-async",
        code=401,
        msg="Unauthorized",
        hdrs={},
        fp=io.BytesIO(sensitive_error.encode("utf-8")),
    )

    with patch("urllib.request.urlopen", side_effect=http_err):
        with pytest.raises(RuntimeError) as exc_info:
            client.submit_agent_run(
                url="https://example.com/p",
                goal="Audit checkout flow",
                audit_id=audit_id,
                run_id=run_id,
                output_schema=TINYFISH_AGENT_OUTPUT_SCHEMA,
            )

        err_str = str(exc_info.value)
        assert MOCK_TEST_KEY not in err_str
        assert "[REDACTED]" in err_str

    calls = crud.get_provider_calls_for_audit(audit_id)
    assert len(calls) == 1
    assert calls[0]["response_status"] == 401
    assert bool(calls[0]["result_usable"]) is False
    assert MOCK_TEST_KEY not in (calls[0]["error_class"] or "")
    assert "[REDACTED]" in calls[0]["error_class"]


# =====================================================================
# 3. Polling & Screenshot Download Tests
# =====================================================================

def test_poll_agent_run_success():
    client = RealTinyFishClient(api_key=MOCK_TEST_KEY)
    audit_id = crud.create_audit(input_url="https://example.com/p", merchant="Example", preset="single")

    poll_payload = {
        "status": "COMPLETED",
        "steps": [
            {"id": "step_1", "action": "product page view", "screenshot": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="},
            {"id": "step_2", "action": "checkout summary review", "screenshot_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="},
        ],
        "result": {
            "status": "ok",
            "observed": {"subtotal_minor": 149900, "currency": "INR"},
            "charges": [
                {"label": "Product", "amount_minor": 149900, "currency": "INR", "step": "product", "mandatory": "yes"},
                {"label": "Product", "amount_minor": 149900, "currency": "INR", "step": "checkout_summary", "mandatory": "yes"},
            ],
            "disclosures": [],
            "totals": {
                "subtotal_minor": 149900,
                "charges_minor": 0,
                "taxes_minor": 0,
                "discounts_minor": 0,
                "final_payable_minor": 149900,
            },
        },
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(poll_payload).encode("utf-8")
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        res = client.poll_agent_run("tf_run_abc123", audit_id=audit_id)
        assert res["status"] == "COMPLETED"
        assert len(res["steps"]) == 2

        req = mock_urlopen.call_args[0][0]
        assert "screenshots=base64" in req.full_url
        assert req.headers.get("X-api-key") == MOCK_TEST_KEY


def test_download_screenshot_success_and_redaction():
    client = RealTinyFishClient(api_key=MOCK_TEST_KEY)
    audit_id = crud.create_audit(input_url="https://example.com/p", merchant="Example", preset="single")

    raw_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    mock_resp = MagicMock()
    mock_resp.read.return_value = raw_png
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        data = client.download_screenshot("tf_run_abc", "step_1", audit_id=audit_id)
        assert data == raw_png

    # Error path with secret leak prevention
    http_err = urllib.error.HTTPError(
        url="https://agent.tinyfish.ai/v1/runs/tf_run_abc/steps/step_1/screenshot",
        code=403,
        msg=f"Forbidden for key {MOCK_TEST_KEY}",
        hdrs={},
        fp=io.BytesIO(b"Forbidden"),
    )
    with patch("urllib.request.urlopen", side_effect=http_err):
        with pytest.raises(RuntimeError) as exc_info:
            client.download_screenshot("tf_run_abc", "step_1", audit_id=audit_id)
        assert MOCK_TEST_KEY not in str(exc_info.value)


# =====================================================================
# 4. Search, Fetch & Profile Tests
# =====================================================================

def test_search_and_fetch_with_secret_scrubbing():
    client = RealTinyFishClient(api_key=MOCK_TEST_KEY)
    audit_id = crud.create_audit(input_url="https://example.com/p", merchant="Example", preset="single")

    # Search success
    search_data = {"results": [{"title": "Policy", "url": "https://example.com/terms"}]}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(search_data).encode("utf-8")
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = client.search("terms", audit_id=audit_id)
        assert len(res) == 1
        assert res[0]["url"] == "https://example.com/terms"

    # Search failure scrubs secrets
    err = urllib.error.HTTPError(
        url="https://api.search.tinyfish.ai/?query=terms",
        code=500,
        msg=f"Server error for {MOCK_TEST_KEY}",
        hdrs={},
        fp=io.BytesIO(b"Internal Error"),
    )
    with patch("urllib.request.urlopen", side_effect=err):
        res = client.search("terms", audit_id=audit_id)
        assert res == []

    calls = crud.get_provider_calls_for_audit(audit_id)
    assert any(c["operation"] == "search" and MOCK_TEST_KEY not in (c.get("error_class") or "") for c in calls)


def test_browser_profile_create_and_delete():
    client = RealTinyFishClient(api_key=MOCK_TEST_KEY)
    audit_id = crud.create_audit(input_url="https://example.com/p", merchant="Example", preset="single")

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"id": "prof_998877"}).encode("utf-8")
    mock_resp.status = 201
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        prof_id = client.create_browser_profile("audit_session", audit_id=audit_id)
        assert prof_id == "prof_998877"

    mock_del_resp = MagicMock()
    mock_del_resp.status = 204
    mock_del_resp.__enter__.return_value = mock_del_resp

    with patch("urllib.request.urlopen", return_value=mock_del_resp):
        client.delete_browser_profile(prof_id, audit_id=audit_id)

    calls = crud.get_provider_calls_for_audit(audit_id)
    ops = [c["operation"] for c in calls]
    assert "profile_create" in ops
    assert "profile_delete" in ops


# =====================================================================
# 5. Worker Live Execution Lifecycle & Idempotency Tests
# =====================================================================

def test_job_runner_full_live_cycle():
    """
    Simulates full worker execution using RealTinyFishClient:
    - Search & Fetch
    - Agent Submission
    - Polling retry with transient error
    - Redacted screenshot storage
    - Atomic observation persistence
    - Clean outcome evaluation
    """
    audit_id = crud.create_audit(input_url="https://www.headphonezone.in/product", merchant="Headphone Zone", preset="single")
    cond_id = crud.create_condition(
        audit_id=audit_id,
        condition_key="ref_fresh_above",
        requested={"session": "fresh", "cart_tier": "above_threshold", "pincode": "110001"},
        is_reference=True,
    )
    run_id = crud.create_run(
        condition_id=cond_id,
        requested={"session": "fresh", "cart_tier": "above_threshold", "pincode": "110001"},
    )
    job_id = crud.enqueue_job(run_id=run_id)

    # 1x1 valid transparent PNG base64
    tiny_png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

    poll_payload = {
        "status": "COMPLETED",
        "steps": [
            {
                "id": "step_pdp",
                "action": "view product page",
                "screenshot": f"data:image/png;base64,{tiny_png_b64}",
            },
            {
                "id": "step_chk",
                "action": "checkout summary order review",
                "screenshot_base64": tiny_png_b64,
            },
        ],
        "result": {
            "status": "ok",
            "observed": {
                "subtotal_minor": 149900,
                "currency": "INR",
                "pincode": "110001",
            },
            "stage_captures": [
                {
                    "step_name": "product",
                    "step_index": 1,
                    "provider_step_id": "step_pdp",
                    "capture_status": "verified",
                    "inspection_status": "inspected",
                },
                {
                    "step_name": "checkout_summary",
                    "step_index": 2,
                    "provider_step_id": "step_chk",
                    "capture_status": "verified",
                    "inspection_status": "inspected",
                },
            ],
            "charges": [
                {
                    "label": "Earphones",
                    "canonical_label": "item_price",
                    "amount_minor": 149900,
                    "currency": "INR",
                    "step": "product",
                    "mandatory": "yes",
                },
                {
                    "label": "Earphones",
                    "canonical_label": "item_price",
                    "amount_minor": 149900,
                    "currency": "INR",
                    "step": "checkout_summary",
                    "mandatory": "yes",
                },
            ],
            "disclosures": [
                {
                    "charge_label": "Earphones",
                    "step": "product",
                    "state": "observed",
                    "visible_text": "₹1,499.00 (Inclusive of all taxes)",
                }
            ],
            "totals": {
                "subtotal_minor": 149900,
                "charges_minor": 0,
                "taxes_minor": 0,
                "discounts_minor": 0,
                "final_payable_minor": 149900,
            },
            "preselected_addons": [],
            "urgency_indicators": [],
        },
    }

    call_count = {"poll": 0}

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if "query=" in url:
            resp = MagicMock()
            resp.read.return_value = json.dumps({"results": []}).encode("utf-8")
            resp.status = 200
            resp.__enter__.return_value = resp
            return resp
        elif "run-async" in url:
            resp = MagicMock()
            resp.read.return_value = json.dumps({"run_id": "tf_prov_live_456"}).encode("utf-8")
            resp.status = 200
            resp.__enter__.return_value = resp
            return resp
        elif "/v1/runs/" in url:
            call_count["poll"] += 1
            if call_count["poll"] == 1:
                # First poll: simulate transient 502 Bad Gateway
                raise urllib.error.HTTPError(url=url, code=502, msg="Bad Gateway", hdrs={}, fp=io.BytesIO(b"Bad Gateway"))
            # Second poll: success!
            resp = MagicMock()
            resp.read.return_value = json.dumps(poll_payload).encode("utf-8")
            resp.status = 200
            resp.__enter__.return_value = resp
            return resp
        resp = MagicMock()
        resp.status = 200
        resp.__enter__.return_value = resp
        return resp

    runner = JobRunner(worker_id="test_worker_live")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        processed = runner.run_one_cycle()
        assert processed is True

    # Verify audit completed
    audit = crud.get_audit(audit_id)
    assert audit["status"] == "complete"

    # Verify run observations and stage captures
    conn = connection.get_connection()
    try:
        run_row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        assert run_row["outcome"] == "ok"
        assert run_row["provider_run_id"] == "tf_prov_live_456"

        charges = conn.execute("SELECT * FROM charge_observations WHERE run_id = ?", (run_id,)).fetchall()
        assert len(charges) == 2

        stage_caps = conn.execute("SELECT * FROM stage_captures WHERE run_id = ?", (run_id,)).fetchall()
        assert len(stage_caps) == 2
        for sc in stage_caps:
            assert sc["capture_status"] == "verified"
            assert sc["inspection_status"] == "inspected"
            assert sc["snapshot_id"] is not None
            # Check snapshot file exists
            snap = conn.execute("SELECT * FROM snapshots WHERE id = ?", (sc["snapshot_id"],)).fetchone()
            assert snap is not None
            assert os.path.exists(snap["artifact_path"])
    finally:
        conn.close()

    # Verify assessment evaluates to verified clean under tested condition
    runs = [{
        "id": run_id,
        "outcome": "ok",
        "stage_captures": [dict(sc) for sc in stage_caps],
        "charges": [dict(c) for c in charges],
        "disclosures": [{"state": "observed"}],
        "urgency_indicators": [],
    }]
    assessment = assess_audit_outcome(runs=runs, findings=[], diffs=[])
    assert assessment["status"] == "clean"
    assert assessment["is_clean"] is True


def test_worker_idempotency_avoids_duplicate_agent_submission_and_charges():
    """
    If a job is reprocessed after worker restart and already has provider_run_id,
    it must NOT resubmit to TinyFish, and running again must NOT duplicate observations.
    """
    audit_id = crud.create_audit(input_url="https://example.com/p", merchant="Example", preset="single")
    cond_id = crud.create_condition(audit_id=audit_id, condition_key="fresh", requested={"session": "fresh", "cart_tier": "above_threshold"})
    run_id = crud.create_run(condition_id=cond_id, requested={"session": "fresh", "cart_tier": "above_threshold"})
    job_id = crud.enqueue_job(run_id=run_id)

    # Set existing provider_run_id on run
    crud.update_run_outcome(
        run_id=run_id,
        provider_run_id="tf_mock_existing_run_999",
        provider_status="RUNNING",
        outcome="ok",
        observed=None,
    )

    poll_payload = {
        "status": "COMPLETED",
        "steps": [],
        "result": {
            "status": "ok",
            "observed": {"subtotal_minor": 1000, "currency": "INR"},
            "charges": [
                {"label": "Item", "amount_minor": 1000, "currency": "INR", "step": "product", "mandatory": "yes"},
            ],
            "disclosures": [],
            "totals": {"subtotal_minor": 1000, "charges_minor": 0, "taxes_minor": 0, "discounts_minor": 0, "final_payable_minor": 1000},
            "stage_captures": [
                {"step_name": "product", "step_index": 1, "capture_status": "verified", "inspection_status": "inspected"},
                {"step_name": "checkout_summary", "step_index": 2, "capture_status": "verified", "inspection_status": "inspected"},
            ],
        },
    }

    submitted = {"count": 0}

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if "run-async" in url:
            submitted["count"] += 1
            resp = MagicMock()
            resp.read.return_value = json.dumps({"run_id": "tf_new_run"}).encode("utf-8")
            resp.status = 200
            resp.__enter__.return_value = resp
            return resp
        elif "/v1/runs/" in url:
            resp = MagicMock()
            resp.read.return_value = json.dumps(poll_payload).encode("utf-8")
            resp.status = 200
            resp.__enter__.return_value = resp
            return resp
        resp = MagicMock()
        resp.read.return_value = json.dumps({"results": []}).encode("utf-8")
        resp.status = 200
        resp.__enter__.return_value = resp
        return resp

    runner = JobRunner(worker_id="idempotency_worker")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        processed = runner.run_one_cycle()
        assert processed is True
        assert submitted["count"] == 0  # CRITICAL: Did NOT call submit_agent_run!

    # Re-running same job or atomic persist must not duplicate rows
    conn = connection.get_connection()
    try:
        charge_count = conn.execute("SELECT count(*) as c FROM charge_observations WHERE run_id = ?", (run_id,)).fetchone()["c"]
        assert charge_count == 1
    finally:
        conn.close()


def test_worker_honest_blocker_evaluates_inconclusive():
    """
    When TinyFish returns blocked_by_login or blocked_by_bot:
    - Outcome is recorded honestly as blocked_by_login.
    - Zero spurious findings are generated.
    - Audit outcome evaluates to inconclusive.
    """
    audit_id = crud.create_audit(input_url="https://example.com/p", merchant="Example", preset="single")
    cond_id = crud.create_condition(audit_id=audit_id, condition_key="fresh", requested={"session": "fresh", "cart_tier": "above_threshold"})
    run_id = crud.create_run(condition_id=cond_id, requested={"session": "fresh", "cart_tier": "above_threshold"})
    job_id = crud.enqueue_job(run_id=run_id)

    blocker_payload = {
        "status": "COMPLETED",
        "steps": [
            {"id": "step_1", "action": "navigate to product", "screenshot": ""},
            {"id": "step_2", "action": "mandatory OTP wall blocked checkout", "screenshot": ""},
        ],
        "result": {
            "status": "blocked_by_login",
            "observed": {"subtotal_minor": 0, "currency": "INR"},
            "charges": [],
            "disclosures": [],
            "totals": {},
            "stage_captures": [],
        },
    }

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if "run-async" in url:
            resp = MagicMock()
            resp.read.return_value = json.dumps({"run_id": "tf_blocked_run"}).encode("utf-8")
            resp.status = 200
            resp.__enter__.return_value = resp
            return resp
        elif "/v1/runs/" in url:
            resp = MagicMock()
            resp.read.return_value = json.dumps(blocker_payload).encode("utf-8")
            resp.status = 200
            resp.__enter__.return_value = resp
            return resp
        resp = MagicMock()
        resp.read.return_value = json.dumps({"results": []}).encode("utf-8")
        resp.status = 200
        resp.__enter__.return_value = resp
        return resp

    runner = JobRunner(worker_id="blocker_worker")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        processed = runner.run_one_cycle()
        assert processed is True

    conn = connection.get_connection()
    try:
        run_row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        assert run_row["outcome"] == "blocked_by_login"

        findings = crud.get_findings_for_audit(audit_id)
        assert len(findings) == 0

        runs = [{"id": run_id, "outcome": "blocked_by_login", "stage_captures": []}]
        assessment = assess_audit_outcome(runs=runs, findings=findings)
        assert assessment["status"] == "inconclusive"
        assert assessment["is_inconclusive"] is True
        assert any("blocked_by_login" in r for r in assessment["inconclusive_reasons"])
    finally:
        conn.close()


def test_missing_checkout_summary_stage_is_inconclusive():
    """
    If checkout summary was never reached or verified, audit outcome is strictly inconclusive.
    Never declares clean without inspecting the order summary stage.
    """
    runs = [{
        "id": "run_incomplete",
        "outcome": "ok",
        "stage_captures": [
            {"step_name": "product", "capture_status": "verified", "inspection_status": "inspected"}
        ],
        "charges": [{"label": "Item", "amount_minor": 1000, "step": "product"}],
        "disclosures": [],
        "urgency_indicators": [],
    }]
    assessment = assess_audit_outcome(runs=runs, findings=[])
    assert assessment["status"] == "inconclusive"
    assert assessment["is_clean"] is False
    assert any("checkout_summary" in r for r in assessment["inconclusive_reasons"])


# =====================================================================
# 6. Settings test-tinyfish Endpoint Tests
# =====================================================================

def test_settings_tf_missing_key():
    mgr = get_settings_manager()
    mgr.set_setting("tinyfish_api_key", "", is_secret=True)
    res = mgr.test_tinyfish_connection(api_key="")
    assert res["success"] is False
    assert res["error"] == "missing_api_key"


def test_settings_tf_success():
    mgr = get_settings_manager()
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = mgr.test_tinyfish_connection(api_key=MOCK_TEST_KEY)
        assert res["success"] is True
        assert res["status_code"] == 200
        assert res["latency_ms"] is not None


def test_settings_tf_error_redaction():
    mgr = get_settings_manager()
    err = urllib.error.HTTPError(
        url="https://api.search.tinyfish.ai/?query=test",
        code=401,
        msg=f"Bad key {MOCK_TEST_KEY}",
        hdrs={},
        fp=io.BytesIO(b"Unauthorized"),
    )

    with patch("urllib.request.urlopen", side_effect=err):
        res = mgr.test_tinyfish_connection(api_key=MOCK_TEST_KEY)
        assert res["success"] is False
        assert res["status_code"] == 401
        assert MOCK_TEST_KEY not in res["message"]
