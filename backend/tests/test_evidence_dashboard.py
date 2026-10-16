"""Tests for Phase 1: Evidence Dashboard & Safe Evidence Serving.

Covers:
1. Valid evidence retrieval via /evidence/{filename}
2. Missing evidence files (404)
3. Rejection of path traversal attempts (../, encoded slashes, disallowed extensions)
4. Disallowing sensitive files (.db, .env, .py)
5. Correct stage-to-snapshot linkage in API (snapshot_sha256, evidence_url, filename)
6. Assessment outcome schema (clean, indicators_detected, inconclusive)
7. Missing screenshot file graceful handling (no 500s)
8. Fresh-database mock demonstration
9. HTML report evidence link verification (/evidence/{filename})
"""

import os
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.db import crud, connection
from app.matrix.orchestrator import expand_matrix
from app.worker.job_runner import JobRunner
from app.tinyfish.mock_client import MockTinyFishClient, TINY_JPEG_BYTES
from app.analysis.detectors import assess_audit_outcome
from app.reports.html_report import generate_html_report


@pytest.fixture
def client_and_evidence_dir(tmp_path, monkeypatch):
    """Setup isolated test database and evidence directory."""
    test_db = tmp_path / "test_checkout_radar.db"
    test_ev = tmp_path / "evidence"
    test_ev.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("SQLITE_DB_PATH", str(test_db))
    monkeypatch.setenv("EVIDENCE_DIR", str(test_ev))

    connection.init_db()
    client = TestClient(app)
    return client, test_ev


def test_evidence_serving_valid_file(client_and_evidence_dir):
    """Test safe serving of valid image and json files from evidence directory."""
    client, ev_dir = client_and_evidence_dir

    # Create dummy jpg artifact
    dummy_jpg = ev_dir / "run_test_product_12345.jpg"
    dummy_jpg.write_bytes(TINY_JPEG_BYTES)

    resp = client.get("/evidence/run_test_product_12345.jpg")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content == TINY_JPEG_BYTES

    # Create dummy json artifact
    dummy_json = ev_dir / "aud_test_summary.json"
    dummy_json.write_text(json.dumps({"test": "data"}))

    resp_json = client.get("/evidence/aud_test_summary.json")
    assert resp_json.status_code == 200
    assert "application/json" in resp_json.headers["content-type"]
    assert resp_json.json() == {"test": "data"}


def test_evidence_serving_missing_file_returns_404(client_and_evidence_dir):
    """Test 404 returned for missing files in evidence directory."""
    client, ev_dir = client_and_evidence_dir
    resp = client.get("/evidence/nonexistent_file_99999.jpg")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Evidence file not found"


def test_evidence_serving_rejects_path_traversal(client_and_evidence_dir):
    """Strictly verify directory traversal defense."""
    client, ev_dir = client_and_evidence_dir

    # Attempting to access parent directory files
    traversal_paths = [
        "../../etc/passwd",
        "../checkout_radar.db",
        "nested/../../main.py",
        "something/../../../test",
    ]
    for p in traversal_paths:
        resp = client.get(f"/evidence/{p}")
        assert resp.status_code in [404, 400], f"Expected 404 for traversal path: {p}"

    # Disallowed file extensions
    sensitive_files = [
        "secret.db",
        "app.env",
        "main.py",
        "script.sh",
        "id_rsa",
    ]
    for sf in sensitive_files:
        (ev_dir / sf).write_text("sensitive")
        resp = client.get(f"/evidence/{sf}")
        assert resp.status_code == 404, f"Disallowed extension {sf} should return 404"


def test_stage_to_snapshot_linkage_and_metadata(client_and_evidence_dir):
    """Verify GET /audits/{id} enriches stage_captures with snapshot SHA256 and evidence_url."""
    client, ev_dir = client_and_evidence_dir

    audit_id = crud.create_audit(
        input_url="http://harness:8001/variant/clean",
        merchant="Test Merchant",
        preset="single",
    )
    conditions = expand_matrix(audit_id, preset="single")
    cond = conditions[0]
    run_id = cond["run_id"]

    # Create dummy image and snapshot
    img_name = f"{run_id}_product_abcd1234ef56.jpg"
    img_path = ev_dir / img_name
    img_path.write_bytes(TINY_JPEG_BYTES)
    sha256_val = "abcd1234ef567890abcdef1234567890abcdef1234567890abcdef1234567890"

    snap_id = crud.create_snapshot(
        run_id=run_id,
        step_name="product",
        artifact_path=str(img_path),
        sha256=sha256_val,
    )

    crud.create_stage_capture(
        run_id=run_id,
        step_name="product",
        step_index=1,
        provider_step_id="prov_step_1",
        capture_status="verified",
        inspection_status="inspected",
        snapshot_id=snap_id,
    )

    resp = client.get(f"/audits/{audit_id}")
    assert resp.status_code == 200
    data = resp.json()

    assert len(data["runs"]) > 0
    sc = data["runs"][0]["stage_captures"][0]
    assert sc["step_name"] == "product"
    assert sc["snapshot_id"] == snap_id
    assert sc["snapshot_sha256"] == sha256_val
    assert sc["evidence_url"] == f"/evidence/{img_name}"
    assert sc["evidence_filename"] == img_name


def test_assessment_banner_schema_distinctions():
    """Verify assessment outcome generator correctly discriminates clean vs inconclusive vs indicators."""
    # 1. Clean audit: all required stages verified, 0 findings
    runs_clean = [{
        "id": "run_clean",
        "outcome": "ok",
        "stage_captures": [
            {"step_name": "product", "capture_status": "verified", "inspection_status": "inspected"},
            {"step_name": "cart", "capture_status": "verified", "inspection_status": "inspected"},
            {"step_name": "checkout_summary", "capture_status": "verified", "inspection_status": "inspected"},
        ],
        "charges": [],
        "disclosures": [],
        "urgency_indicators": [],
    }]
    clean_outcome = assess_audit_outcome(runs=runs_clean, findings=[], diffs=[])
    assert clean_outcome["status"] == "clean"
    assert clean_outcome["is_clean"] is True
    assert clean_outcome["is_inconclusive"] is False
    assert len(clean_outcome["inconclusive_reasons"]) == 0

    # 2. Inconclusive audit: missing checkout_summary stage
    runs_incomplete = [{
        "id": "run_inc",
        "outcome": "ok",
        "stage_captures": [
            {"step_name": "product", "capture_status": "verified", "inspection_status": "inspected"},
        ],
        "charges": [],
        "disclosures": [],
        "urgency_indicators": [],
    }]
    inc_outcome = assess_audit_outcome(runs=runs_incomplete, findings=[], diffs=[])
    assert inc_outcome["status"] == "inconclusive"
    assert inc_outcome["is_clean"] is False
    assert inc_outcome["is_inconclusive"] is True
    assert len(inc_outcome["inconclusive_reasons"]) > 0
    assert any("checkout_summary" in r for r in inc_outcome["inconclusive_reasons"])

    # 3. Indicators detected: findings exist
    findings_flagged = [{
        "category": "drip_pricing",
        "severity": "high",
        "confidence": 0.9,
        "explanation": "Hidden handling fee at checkout",
    }]
    ind_outcome = assess_audit_outcome(runs=runs_clean, findings=findings_flagged, diffs=[])
    assert ind_outcome["status"] in ["potential_indicators_detected", "indicators_detected"]
    assert ind_outcome["is_clean"] is False
    assert ind_outcome["findings_count"] == 1


def test_missing_screenshots_graceful_handling(client_and_evidence_dir):
    """Ensure that if an image artifact is absent from disk, the API remains fully functional and returns 404 on the asset URL."""
    client, ev_dir = client_and_evidence_dir

    audit_id = crud.create_audit(
        input_url="http://harness:8001/variant/clean",
        merchant="Missing Asset Store",
        preset="single",
    )
    conditions = expand_matrix(audit_id, preset="single")
    cond = conditions[0]
    run_id = cond["run_id"]

    # Deliberately point artifact_path to non-existent file
    ghost_filename = f"{run_id}_product_ghostfile.jpg"
    ghost_path = ev_dir / ghost_filename

    snap_id = crud.create_snapshot(
        run_id=run_id,
        step_name="product",
        artifact_path=str(ghost_path),
        sha256="0000000000000000000000000000000000000000000000000000000000000000",
    )
    crud.create_stage_capture(
        run_id=run_id,
        step_name="product",
        step_index=1,
        capture_status="verified",
        inspection_status="inspected",
        snapshot_id=snap_id,
    )

    # API response works smoothly
    resp = client.get(f"/audits/{audit_id}")
    assert resp.status_code == 200
    ev_url = resp.json()["runs"][0]["stage_captures"][0]["evidence_url"]
    assert ev_url == f"/evidence/{ghost_filename}"

    # Asset fetch gracefully returns 404 (not 500)
    asset_resp = client.get(ev_url)
    assert asset_resp.status_code == 404


def test_fresh_database_mock_demonstration(tmp_path, monkeypatch):
    """End-to-end mock flow execution on a completely fresh database."""
    fresh_db = tmp_path / "fresh_demo.db"
    fresh_ev = tmp_path / "fresh_evidence"
    fresh_ev.mkdir()

    monkeypatch.setenv("SQLITE_DB_PATH", str(fresh_db))
    monkeypatch.setenv("EVIDENCE_DIR", str(fresh_ev))

    connection.init_db()

    audit_id = crud.create_audit(
        input_url="http://harness:8001/variant/clean",
        merchant="Demo Store (Fresh Clean)",
        preset="quick",
    )
    expand_matrix(audit_id, preset="quick")

    runner = JobRunner(worker_id="fresh_worker", adapter=MockTinyFishClient())
    while runner.run_one_cycle():
        pass

    client = TestClient(app)
    resp = client.get(f"/audits/{audit_id}")
    assert resp.status_code == 200
    det = resp.json()

    assert det["audit"]["status"] == "complete"
    assert det["assessment"]["is_clean"] is True
    assert det["assessment"]["status"] == "clean"

    # All stage captures exist with evidence URLs
    ref_run = det["runs"][0]
    stages = [sc["step_name"] for sc in ref_run["stage_captures"]]
    assert "product" in stages
    assert "cart" in stages
    assert "checkout_summary" in stages

    for sc in ref_run["stage_captures"]:
        assert sc["evidence_url"].startswith("/evidence/")
        fname = sc["evidence_filename"]
        # Check that the file was generated and is retrievable
        asset_resp = client.get(f"/evidence/{fname}")
        assert asset_resp.status_code == 200


def test_html_report_uses_valid_evidence_urls(client_and_evidence_dir):
    """Verify HTML report contains valid /evidence/{filename} links instead of broken relative ./ links."""
    client, ev_dir = client_and_evidence_dir

    audit_id = crud.create_audit(
        input_url="http://harness:8001/variant/clean",
        merchant="Report Link Store",
        preset="single",
    )
    expand_matrix(audit_id, preset="single")

    runner = JobRunner(worker_id="report_worker", adapter=MockTinyFishClient())
    while runner.run_one_cycle():
        pass

    resp = client.get(f"/audits/{audit_id}/report")
    assert resp.status_code == 200
    html = resp.text

    assert 'href="/evidence/' in html
    assert 'href="./' not in html


def test_landing_page_serves_html(client_and_evidence_dir):
    """Verify / serves the landing page with status 200."""
    client, _ = client_and_evidence_dir
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Outside-In Differential Checkout Transparency" in resp.text
    assert "The Problem" in resp.text
    assert "The Five-Stage Outside-In Auditing Workflow" in resp.text


def test_landing_page_redirects_with_audit_id(client_and_evidence_dir):
    """Verify /?audit_id=xyz redirects to /auditor?audit_id=xyz with 307 Temporary Redirect."""
    client, _ = client_and_evidence_dir
    resp = client.get("/?audit_id=aud_test123", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/auditor?audit_id=aud_test123"


def test_auditor_page_serves_workspace(client_and_evidence_dir):
    """Verify /auditor serves the investigation workspace with status 200."""
    client, _ = client_and_evidence_dir
    resp = client.get("/auditor")
    assert resp.status_code == 200
    assert "Launch Checkout Audit" in resp.text
    assert "Overview" in resp.text

