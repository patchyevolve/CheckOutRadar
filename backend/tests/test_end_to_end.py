"""End-to-end integration test demonstrating the full audit pipeline."""

import pytest
import os
from pathlib import Path
from app.db import crud, connection
from app.matrix.orchestrator import expand_matrix
from app.worker.job_runner import JobRunner
from app.tinyfish.mock_client import MockTinyFishClient
from app.reports.html_report import generate_html_report
from app.reports.complaint_draft import generate_complaint_draft


@pytest.fixture(autouse=True)
def setup_env(tmp_path, monkeypatch):
    test_db = tmp_path / "e2e_test.db"
    test_ev = tmp_path / "evidence"
    monkeypatch.setenv("SQLITE_DB_PATH", str(test_db))
    monkeypatch.setenv("EVIDENCE_DIR", str(test_ev))
    monkeypatch.setenv("MOCK_TINYFISH", "true")
    connection.init_db()


def test_full_pipeline_adversarial_variant():
    # 1. Submit audit for Late Disclosure variant
    audit_id = crud.create_audit(
        input_url="http://harness:8001/variant/late_disclosure",
        merchant="Demo Store (Late Handling)",
        preset="quick",
    )
    assert audit_id.startswith("aud_")

    # 2. Expand matrix (Quick = 4 conditions)
    conditions = expand_matrix(audit_id, preset="quick")
    assert len(conditions) == 4

    # 3. Worker drains queue
    from app.tinyfish.mock_client import MockTinyFishClient
    mock_adapter = MockTinyFishClient()
    runner = JobRunner(worker_id="test_worker", adapter=mock_adapter)
    processed_count = 0
    while runner.run_one_cycle():
        processed_count += 1

    assert processed_count == 4, f"Expected 4 runs processed, got {processed_count}"

    # 4. Check audit status
    audit = crud.get_audit(audit_id)
    assert audit["status"] == "complete"

    # 5. Check Diffs
    diffs = crud.get_diffs_for_audit(audit_id)
    assert len(diffs) > 0
    late_diffs = [d for d in diffs if d["type"] == "LATE_DISCLOSURE"]
    assert len(late_diffs) > 0, "Expected LATE_DISCLOSURE diff"

    # 6. Check Findings
    findings = crud.get_findings_for_audit(audit_id)
    assert len(findings) > 0
    drip_findings = [f for f in findings if f["category"] == "drip_pricing"]
    assert len(drip_findings) > 0, "Expected drip_pricing finding"
    assert "₹5.00" in drip_findings[0]["explanation"]
    assert "heuristic" in drip_findings[0]["heuristic_note"].lower()

    # 7. Check Provider Calls (Search, Fetch, Agent, Screenshot)
    calls = crud.get_provider_calls_for_audit(audit_id)
    ops = [c["operation"] for c in calls]
    assert "search" in ops, "Search not logged in main path"
    assert "fetch" in ops, "Fetch not logged in main path"
    assert "agent_submit" in ops, "Agent submit not logged"
    assert "agent_poll" in ops, "Agent poll not logged"

    # 8. Check HTML Report generation
    html = generate_html_report(
        audit=audit,
        conditions=conditions,
        diffs=diffs,
        findings=findings,
        provider_calls=calls,
    )
    assert "Checkout Radar Audit Report" in html
    assert "Drip Pricing" in html

    # 9. Check Complaint Draft generation
    draft = generate_complaint_draft(audit=audit, findings=findings, diffs=diffs)
    assert draft["is_draft"] is True
    assert draft["auto_submitted"] is False
    assert "DRIP PRICING" in draft["draft_text"]


def test_full_pipeline_clean_variant_produces_no_findings():
    """Negative control: Clean harness must produce 0 findings."""
    audit_id = crud.create_audit(
        input_url="http://harness:8001/variant/clean",
        merchant="Demo Store (Clean)",
        preset="quick",
    )
    expand_matrix(audit_id, preset="quick")

    runner = JobRunner(worker_id="clean_worker", adapter=MockTinyFishClient())
    while runner.run_one_cycle():
        pass

    findings = crud.get_findings_for_audit(audit_id)
    assert len(findings) == 0, f"Clean store must produce 0 findings, got {len(findings)}"


def test_full_pipeline_addon_countdown_variant():
    """Adversarial variant: Add-on and resetting countdown must produce both basket_sneaking and false_urgency findings."""
    audit_id = crud.create_audit(
        input_url="http://harness:8001/variant/addon_countdown",
        merchant="Demo Store (Addon & Countdown)",
        preset="quick",
    )
    expand_matrix(audit_id, preset="quick")

    runner = JobRunner(worker_id="addon_worker", adapter=MockTinyFishClient())
    while runner.run_one_cycle():
        pass

    findings = crud.get_findings_for_audit(audit_id)
    categories = [f["category"] for f in findings]
    assert "basket_sneaking" in categories, f"Expected basket_sneaking, got {categories}"
    assert "false_urgency" in categories, f"Expected false_urgency, got {categories}"

    sneak = [f for f in findings if f["category"] == "basket_sneaking"][0]
    assert "Transit Protection Guarantee" in sneak["explanation"]
    assert "₹15.00" in sneak["explanation"]

    urgency = [f for f in findings if f["category"] == "false_urgency"][0]
    assert "countdown timer restarted or reset" in urgency["explanation"]
    assert "30s measured elapsed wall-clock time" in urgency["explanation"]
    assert "holding session and page state fixed without navigation" in urgency["explanation"]
    assert urgency.get("heuristic_note") is not None
    assert "potential false-urgency indicator" in urgency["heuristic_note"]
    assert "not proof of deceptive intent" in urgency["heuristic_note"]


def test_full_pipeline_upfront_fee_negative_control():
    """Negative control: Upfront fee disclosed on product page must produce 0 dark pattern findings."""
    audit_id = crud.create_audit(
        input_url="http://harness:8001/variant/upfront_fee",
        merchant="Demo Store (Upfront Fee)",
        preset="quick",
    )
    expand_matrix(audit_id, preset="quick")

    runner = JobRunner(worker_id="upfront_worker", adapter=MockTinyFishClient())
    while runner.run_one_cycle():
        pass

    findings = crud.get_findings_for_audit(audit_id)
    assert len(findings) == 0, f"Upfront fee must produce 0 findings, got {len(findings)}"


def test_full_pipeline_legitimate_threshold_negative_control():
    """Negative control: Legitimate cart threshold rules must produce SMALL_CART_RULE diff but 0 dark pattern findings."""
    audit_id = crud.create_audit(
        input_url="http://harness:8001/variant/legitimate_threshold",
        merchant="Demo Store (Threshold)",
        preset="quick",
    )
    expand_matrix(audit_id, preset="quick")

    runner = JobRunner(worker_id="threshold_worker", adapter=MockTinyFishClient())
    while runner.run_one_cycle():
        pass

    diffs = crud.get_diffs_for_audit(audit_id)
    rule_diffs = [d for d in diffs if d["type"] == "SMALL_CART_RULE"]
    assert len(rule_diffs) > 0, "Expected SMALL_CART_RULE diff for threshold crossing"

    findings = crud.get_findings_for_audit(audit_id)
    assert len(findings) == 0, f"Legitimate threshold must produce 0 dark pattern findings, got {len(findings)}"


def test_full_pipeline_inconclusive_blocked_by_login():
    """
    Critical specification test:
    When an audit cannot inspect the checkout flow because it is blocked by login or bot wall,
    it must NOT claim 'Clean Audit'. It must be evaluated as INCONCLUSIVE.
    """
    audit_id = crud.create_audit(
        input_url="http://harness:8001/variant/blocked_store",
        merchant="Blocked Merchant",
        preset="quick",
    )
    conditions = expand_matrix(audit_id, preset="quick")

    # Mock adapter that returns blocked_by_login
    class BlockedMockAdapter(MockTinyFishClient):
        def poll_agent_run(self, provider_run_id, audit_id, run_id=None):
            req_at = "2026-10-14T10:00:00Z"
            return {
                "run_id": provider_run_id,
                "status": "COMPLETED",
                "goal": "checkout",
                "created_at": req_at,
                "finished_at": req_at,
                "num_of_steps": 1,
                "result": {
                    "status": "blocked_by_login",
                    "requested": {"session": "fresh", "cart_tier": "above_threshold"},
                    "observed": {"subtotal_minor": 0, "currency": "INR"},
                    "stage_captures": [
                        {"step_name": "product", "step_index": 1, "capture_status": "failed", "inspection_status": "uninspected"}
                    ],
                    "charges": [],
                    "disclosures": [],
                    "totals": {
                        "subtotal_minor": 0, "charges_minor": 0, "taxes_minor": 0,
                        "discounts_minor": 0, "final_payable_minor": 0, "currency": "INR",
                    },
                },
                "steps": [],
            }

    runner = JobRunner(worker_id="blocked_worker", adapter=BlockedMockAdapter())
    while runner.run_one_cycle():
        pass

    # No dark pattern findings were detected because agent was blocked
    findings = crud.get_findings_for_audit(audit_id)
    assert len(findings) == 0

    audit = crud.get_audit(audit_id)
    diffs = crud.get_diffs_for_audit(audit_id)
    calls = crud.get_provider_calls_for_audit(audit_id)

    # HTML report MUST declare Inconclusive, never 'Clean Audit'
    html = generate_html_report(
        audit=audit,
        conditions=conditions,
        diffs=diffs,
        findings=findings,
        provider_calls=calls,
    )
    assert "INCONCLUSIVE" in html, "Blocked audit must display INCONCLUSIVE badge"
    assert "Clean Audit: No potential dark pattern indicators detected" not in html
    assert "Inconclusive Flow: Evidence incomplete or obstructed" in html

    # Complaint draft must note audit was inconclusive
    draft = generate_complaint_draft(audit=audit, findings=findings, diffs=diffs)
    assert "AUDIT INCONCLUSIVE" in draft["draft_text"]


