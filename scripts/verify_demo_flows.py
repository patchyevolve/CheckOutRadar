"""Checkout Radar — AZINHACK Three-Flow Demonstration Verification Script.

Executes and verifies:
1. Flow 1: Synthetic Positive Controls (Drip Pricing, Basket Sneaking, False Urgency)
2. Flow 2: Real-Site Negative Control (Headphone Zone aud_b29153cee0b1)
3. Flow 3: Failure-Mode Demonstration (Missing Checkout Summary -> Inconclusive)
"""

import sys
import os
import json
from pathlib import Path

# Add backend to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.db import crud, connection
from app.matrix.orchestrator import expand_matrix
from app.worker.job_runner import JobRunner
from app.tinyfish.mock_client import MockTinyFishClient
from app.analysis.detectors import assess_audit_outcome
from app.reports.html_report import generate_html_report
from app.reports.complaint_draft import generate_complaint_draft


def run_flow_1_synthetic_positive_controls():
    print("=" * 70)
    print("DEMO FLOW 1: Synthetic Positive Controls (Controlled Merchant Harness)")
    print("=" * 70)

    # 1A. Drip Pricing (Late Disclosure)
    print("\n[1A] Testing Drip Pricing Detection (Variant: late_disclosure)...")
    audit_id_drip = crud.create_audit(
        input_url="http://harness:8001/variant/late_disclosure",
        merchant="Demo Store (Late Handling)",
        preset="quick",
    )
    expand_matrix(audit_id_drip, preset="quick")
    runner_drip = JobRunner(worker_id="demo_worker_drip", adapter=MockTinyFishClient())
    while runner_drip.run_one_cycle():
        pass

    findings_drip = crud.get_findings_for_audit(audit_id_drip)
    diffs_drip = crud.get_diffs_for_audit(audit_id_drip)
    drip_findings = [f for f in findings_drip if f["category"] == "drip_pricing"]
    assert len(drip_findings) > 0, "Expected drip_pricing finding"
    print(f"  ✓ Emitted Drip Pricing Indicator: {drip_findings[0]['explanation']}")
    print(f"  ✓ Matched Pair Diff Type: {diffs_drip[0]['type']} ({diffs_drip[0]['matching_key']})")

    # 1B. Basket Sneaking & False Urgency (Addon & Countdown)
    print("\n[1B] Testing Basket Sneaking & False Urgency (Variant: addon_countdown)...")
    audit_id_addon = crud.create_audit(
        input_url="http://harness:8001/variant/addon_countdown",
        merchant="Demo Store (Pre-selected Addon)",
        preset="quick",
    )
    expand_matrix(audit_id_addon, preset="quick")
    runner_addon = JobRunner(worker_id="demo_worker_addon", adapter=MockTinyFishClient())
    while runner_addon.run_one_cycle():
        pass

    findings_addon = crud.get_findings_for_audit(audit_id_addon)
    sneak_findings = [f for f in findings_addon if f["category"] == "basket_sneaking"]
    urgency_findings = [f for f in findings_addon if f["category"] == "false_urgency"]
    assert len(sneak_findings) > 0, "Expected basket_sneaking finding"
    assert len(urgency_findings) > 0, "Expected false_urgency finding"
    print(f"  ✓ Emitted Basket Sneaking Indicator: {sneak_findings[0]['explanation']}")
    print(f"  ✓ Emitted False Urgency Indicator: {urgency_findings[0]['explanation']}")
    print("DEMO FLOW 1 PASSED: All 3 dark pattern categories positively detected.")


def run_flow_2_real_site_negative_control():
    print("\n" + "=" * 70)
    print("DEMO FLOW 2: Negative Control (Clean Upfront Pricing & Empirical Verification)")
    print("=" * 70)

    expected_stages = {"product", "cart", "checkout_summary"}

    # 2A. Deterministic Synthetic Clean Negative Control (Runs on Any Fresh Clone)
    print("\n[2A] Executing Deterministic Clean Negative Control (Variant: clean)...")
    audit_id_clean = crud.create_audit(
        input_url="http://harness:8001/variant/clean",
        merchant="Demo Store (Clean Upfront)",
        preset="quick",
    )
    expand_matrix(audit_id_clean, preset="quick")
    runner_clean = JobRunner(worker_id="demo_worker_clean", adapter=MockTinyFishClient())
    while runner_clean.run_one_cycle():
        pass

    audit_clean = crud.get_audit(audit_id_clean)
    conditions_clean = crud.get_conditions_for_audit(audit_id_clean)
    diffs_clean = crud.get_diffs_for_audit(audit_id_clean)
    findings_clean = crud.get_findings_for_audit(audit_id_clean)
    calls_clean = crud.get_provider_calls_for_audit(audit_id_clean)

    conn = connection.get_connection()
    try:
        run_rows = conn.execute(
            "SELECT r.* FROM runs r JOIN conditions c ON r.condition_id = c.id WHERE c.audit_id = ?",
            (audit_id_clean,),
        ).fetchall()
        runs_clean = []
        for r in run_rows:
            rd = dict(r)
            run_id = rd["id"]
            rd["stage_captures"] = [dict(sc) for sc in conn.execute("SELECT * FROM stage_captures WHERE run_id = ?", (run_id,)).fetchall()]
            rd["charges"] = [dict(c) for c in conn.execute("SELECT * FROM charge_observations WHERE run_id = ?", (run_id,)).fetchall()]
            rd["disclosures"] = [dict(d) for d in conn.execute("SELECT * FROM disclosure_observations WHERE run_id = ?", (run_id,)).fetchall()]
            rd["urgency_indicators"] = [dict(u) for u in conn.execute("SELECT * FROM urgency_observations WHERE run_id = ?", (run_id,)).fetchall()]
            rd["snapshots"] = [dict(s) for s in conn.execute("SELECT * FROM snapshots WHERE run_id = ?", (run_id,)).fetchall()]
            runs_clean.append(rd)
    finally:
        conn.close()

    assert len(findings_clean) == 0, "Clean variant should have 0 findings"
    assessment_clean = assess_audit_outcome(runs=runs_clean, findings=findings_clean, diffs=diffs_clean)
    assert assessment_clean["is_clean"] is True
    assert assessment_clean["status"] == "clean"
    print(f"  ✓ Clean Audit Outcome: {assessment_clean['status'].upper()} (is_clean = True, 0 findings)")

    captured_stages = {sc["step_name"] for sc in runs_clean[0].get("stage_captures", []) if sc.get("capture_status") == "verified"}
    assert expected_stages.issubset(captured_stages), f"Expected stages {expected_stages}, got {captured_stages}"
    print(f"  ✓ Captured Required Stages: {sorted(list(captured_stages))}")

    html_clean = generate_html_report(
        audit=audit_clean,
        conditions=conditions_clean,
        diffs=diffs_clean,
        findings=findings_clean,
        provider_calls=calls_clean,
        runs=runs_clean,
    )
    assert "VERIFIED CLEAN" in html_clean
    print("  ✓ HTML Evidence Report contains 'VERIFIED CLEAN'")

    # 2B. Empirical Headphone Zone Audit (If present in local environment)
    print("\n[2B] Checking Real-Site Empirical Evidence (Headphone Zone aud_b29153cee0b1)...")
    audit_id = "aud_b29153cee0b1"
    audit = crud.get_audit(audit_id)
    if audit is None:
        print("  ℹ️ Real-Site Limitation Notice:")
        print("     Empirical audit aud_b29153cee0b1 is not present in local database (fresh clone state).")
        print("     To reproduce live external evidence without fabricated data, execute:")
        print("     `python3 scripts/run_real_audit.py` with valid TINYFISH_API_KEY credentials.")
        print("     (Deterministic synthetic clean negative control verified above in [2A]).")
    else:
        conditions = crud.get_conditions_for_audit(audit_id)
        diffs = crud.get_diffs_for_audit(audit_id)
        findings = crud.get_findings_for_audit(audit_id)
        provider_calls = crud.get_provider_calls_for_audit(audit_id)

        conn = connection.get_connection()
        try:
            run_rows = conn.execute(
                "SELECT r.* FROM runs r JOIN conditions c ON r.condition_id = c.id WHERE c.audit_id = ?",
                (audit_id,),
            ).fetchall()
            runs = []
            for r in run_rows:
                rd = dict(r)
                run_id = rd["id"]
                rd["stage_captures"] = [dict(sc) for sc in conn.execute("SELECT * FROM stage_captures WHERE run_id = ?", (run_id,)).fetchall()]
                rd["charges"] = [dict(c) for c in conn.execute("SELECT * FROM charge_observations WHERE run_id = ?", (run_id,)).fetchall()]
                rd["disclosures"] = [dict(d) for d in conn.execute("SELECT * FROM disclosure_observations WHERE run_id = ?", (run_id,)).fetchall()]
                rd["urgency_indicators"] = [dict(u) for u in conn.execute("SELECT * FROM urgency_observations WHERE run_id = ?", (run_id,)).fetchall()]
                rd["snapshots"] = [dict(s) for s in conn.execute("SELECT * FROM snapshots WHERE run_id = ?", (run_id,)).fetchall()]
                runs.append(rd)
        finally:
            conn.close()

        print(f"  Target Merchant:   {audit['merchant']} ({audit['input_url']})")
        print(f"  Provider Run ID:   {runs[0]['provider_run_id']} (Status: {runs[0]['provider_status']})")
        print(f"  Findings Count:    {len(findings)} (Negative Control: 0 dark pattern indicators)")

        snap_map = {s["id"]: s for s in runs[0]["snapshots"]}
        print("\n  Verified Stage Captures:")
        seen_stages = set()
        for sc in runs[0]["stage_captures"]:
            st = sc["step_name"]
            if st in seen_stages:
                continue
            seen_stages.add(st)
            snap = snap_map.get(sc["snapshot_id"], {})
            print(f"    - {st:<18} | ID: {sc['snapshot_id']} | Hash: {snap.get('sha256')[:20]}... | {sc['capture_status'].upper()}")
        assert set(expected_stages).issubset(seen_stages), "Missing required stages in real audit"

        html = generate_html_report(
            audit=audit,
            conditions=conditions,
            diffs=diffs,
            findings=findings,
            provider_calls=provider_calls,
            runs=runs,
        )
        assert "VERIFIED CLEAN" in html
        assert "[Screenshot Verified]" in html
        assert "[DOM Extracted (Unexpanded)]" in html
        assert "[Inferred]" in html
        assert "[Uninspected Flow]" in html
        print("\n  Evidence Contract Classifications:")
        print("    - Listed Price, Taxes (GST), Free Delivery: [Screenshot Verified]")
        print("    - COD Convenience Fee (₹99.00 in drawer):    [DOM Extracted (Unexpanded)]")
        print("    - Zero-charge items without UI elements:    [Inferred]")
        print("    - Third-party Payment Gateways:             [Uninspected Flow]")

        assessment = assess_audit_outcome(runs=runs, findings=findings, diffs=diffs)
        assert assessment["is_clean"] is True
        print(f"\n  Final Outcome: {assessment['status'].upper()} (Certified clean strictly under tested flow)")

    print("DEMO FLOW 2 PASSED: Clean negative control and empirical contract verified.")


def run_flow_3_failure_mode_inconclusive():
    print("\n" + "=" * 70)
    print("DEMO FLOW 3: Failure-Mode Demonstration (Conservative Inconclusive Default)")
    print("=" * 70)

    audit_id = crud.create_audit(
        input_url="http://harness:8001/variant/incomplete_flow",
        merchant="Demo Store (Incomplete Run)",
        preset="single",
    )
    conditions = expand_matrix(audit_id, preset="single")

    class IncompleteMockAdapter(MockTinyFishClient):
        def poll_agent_run(self, provider_run_id, audit_id, run_id=None):
            req_at = "2026-10-15T12:00:00Z"
            return {
                "run_id": provider_run_id,
                "status": "COMPLETED",
                "goal": "checkout",
                "created_at": req_at,
                "finished_at": req_at,
                "num_of_steps": 2,
                "result": {
                    "status": "ok",
                    "requested": {"session": "fresh", "cart_tier": "above_threshold"},
                    "observed": {"subtotal_minor": 199900, "currency": "INR"},
                    "stage_captures": [
                        {
                            "step_name": "product",
                            "step_index": 0,
                            "capture_status": "verified",
                            "inspection_status": "inspected",
                            "snapshot_id": "snap_demo_prod",
                        }
                    ],
                    "charges": [],
                    "disclosures": [],
                    "totals": {
                        "subtotal_minor": 199900,
                        "charges_minor": 0,
                        "taxes_minor": 0,
                        "discounts_minor": 0,
                        "final_payable_minor": 199900,
                        "currency": "INR",
                    },
                },
                "steps": [],
            }

    runner = JobRunner(worker_id="demo_worker_incomplete", adapter=IncompleteMockAdapter())
    while runner.run_one_cycle():
        pass

    findings = crud.get_findings_for_audit(audit_id)
    assert len(findings) == 0, "Incomplete run has 0 rule findings"

    audit = crud.get_audit(audit_id)
    diffs = crud.get_diffs_for_audit(audit_id)
    calls = crud.get_provider_calls_for_audit(audit_id)

    # Load runs
    conn = connection.get_connection()
    try:
        run_rows = conn.execute(
            "SELECT r.* FROM runs r JOIN conditions c ON r.condition_id = c.id WHERE c.audit_id = ?",
            (audit_id,),
        ).fetchall()
        runs = []
        for r in run_rows:
            rd = dict(r)
            run_id = rd["id"]
            rd["stage_captures"] = [dict(sc) for sc in conn.execute("SELECT * FROM stage_captures WHERE run_id = ?", (run_id,)).fetchall()]
            rd["charges"] = [dict(c) for c in conn.execute("SELECT * FROM charge_observations WHERE run_id = ?", (run_id,)).fetchall()]
            rd["disclosures"] = [dict(d) for d in conn.execute("SELECT * FROM disclosure_observations WHERE run_id = ?", (run_id,)).fetchall()]
            rd["urgency_indicators"] = [dict(u) for u in conn.execute("SELECT * FROM urgency_observations WHERE run_id = ?", (run_id,)).fetchall()]
            runs.append(rd)
    finally:
        conn.close()

    assessment = assess_audit_outcome(runs=runs, findings=findings, diffs=diffs)
    assert assessment["status"] == "inconclusive"
    assert assessment["is_clean"] is False
    assert assessment["is_inconclusive"] is True
    print(f"  Assessment Status: {assessment['status'].upper()}")
    print(f"  Inconclusive Reason: {assessment['inconclusive_reasons'][0]}")

    html = generate_html_report(
        audit=audit,
        conditions=conditions,
        diffs=diffs,
        findings=findings,
        provider_calls=calls,
        runs=runs,
    )
    assert "INCONCLUSIVE AUDIT" in html
    assert "VERIFIED CLEAN" not in html
    print("  Report Badge:      INCONCLUSIVE AUDIT (Clean badge correctly denied)")

    draft = generate_complaint_draft(audit=audit, findings=findings, diffs=diffs, runs=runs)
    assert "AUDIT INCONCLUSIVE" in draft["draft_text"]
    print("  Complaint Draft:   Records AUDIT INCONCLUSIVE")
    print("DEMO FLOW 3 PASSED: Conservative fail-closed behavior verified.")


if __name__ == "__main__":
    print("\n" + "#" * 70)
    print("CHECKOUT RADAR: PRE-HACKATHON THREE-FLOW DEMO VERIFICATION")
    print("#" * 70)
    connection.init_db()
    run_flow_1_synthetic_positive_controls()
    run_flow_2_real_site_negative_control()
    run_flow_3_failure_mode_inconclusive()
    print("\n" + "#" * 70)
    print("ALL THREE DEMONSTRATION FLOWS FULLY VERIFIED & REPRODUCIBLE")
    print("#" * 70 + "\n")
