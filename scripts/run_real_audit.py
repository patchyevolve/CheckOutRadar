"""Execute one real bounded audit against a public retail site via TinyFish.

Guarantees:
- Zero Groq calls (GROQ_API_KEY explicitly suppressed).
- RealTinyFishClient execution against public merchant (Headphone Zone).
- Bounded 1-condition reference run (preset: single).
- Non-destructive execution: stops at checkout summary, never submits payment.
- Honest outcome evaluation: clean, inconclusive, or potential_indicators_detected.
- Durable persistence of navigation trace, evidence, snapshots, diffs, findings, and report.
"""

import os
import sys
import json
import time
from pathlib import Path

# Insert backend directory
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

# Load .env
env_file = Path(__file__).resolve().parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# STRICT CONSTRAINT: Zero Groq calls
os.environ["GROQ_API_KEY"] = ""
os.environ["LLM_API_KEY"] = ""

# Enable Real TinyFish execution
os.environ["MOCK_TINYFISH"] = "false"

from app.db import crud, connection
from app.matrix.orchestrator import expand_matrix
from app.worker.job_runner import JobRunner
from app.analysis.detectors import assess_audit_outcome
from app.reports.html_report import generate_html_report
from app.reports.complaint_draft import generate_complaint_draft
from app.services.settings_service import get_settings_manager

get_settings_manager().set_setting("mock_tinyfish", False)


def main():
    print("=" * 70)
    print("CHECKOUT RADAR: LIVE EXTERNAL AUDIT VALIDATION")
    print("=" * 70)

    connection.init_db()

    target_url = "https://www.headphonezone.in/products/tangzu-waner-s-g"
    merchant_name = "Headphone Zone"
    preset = "single"

    print(f"Target Merchant:               {merchant_name}")
    print(f"Target URL:                    {target_url}")
    print(f"Audit Preset:                  {preset} (1 bounded condition)")
    print(f"Provider:                      TinyFish Web Agent API (live)")
    print(f"LLM Classification:            Offline deterministic fallback (0 Groq calls)")
    print(f"Safety Constraint:             STOP BEFORE PAYMENT (Order review only)")

    # 1. Create Audit
    audit_id = crud.create_audit(
        input_url=target_url,
        merchant=merchant_name,
        preset=preset,
    )
    print(f"\n[1] Audit Created:              {audit_id}")

    # 2. Expand Matrix (Single Bounded Condition)
    conditions = expand_matrix(audit_id, preset=preset)
    print(f"[2] Matrix Expanded:           {len(conditions)} condition(s) created")
    for c in conditions:
        print(f"    - Condition ID: {c['condition_id']} | Key: {c['condition_key']} | Ref: {c['is_reference']}")

    # 3. Instantiate Runner with Real TinyFish Adapter
    runner = JobRunner(worker_id="real_audit_worker")
    adapter_name = type(runner.get_adapter_for_job(target_url)).__name__
    print(f"[3] Worker Initialized:        Adapter = {adapter_name}")

    if adapter_name != "RealTinyFishClient":
        print(f"ERROR: Expected RealTinyFishClient, got {adapter_name}. Check API key and MOCK_TINYFISH.")
        sys.exit(1)

    # 4. Execute Job
    print(f"\n[4] Executing Job via {adapter_name}...")
    t_start = time.time()
    processed = runner.run_one_cycle()
    timeout_sec = 240.0
    while time.time() - t_start < timeout_sec:
        audit = crud.get_audit(audit_id)
        if audit and audit.get("status") == "complete":
            break
        if not runner.run_one_cycle():
            time.sleep(3.0)
    elapsed = time.time() - t_start

    print(f"    Cycle Completed in {elapsed:.2f}s (processed = {processed})")

    # 5. Inspect Results in SQLite
    print("\n" + "=" * 70)
    print("DATABASE AUDIT INSPECTION & EVIDENCE PROVENANCE")
    print("=" * 70)

    audit = crud.get_audit(audit_id)
    print(f"Audit Status:                  {audit.get('status')}")

    # Provider Calls
    p_calls = crud.get_provider_calls_for_audit(audit_id)
    print(f"\nProvider Calls Logged ({len(p_calls)} operations):")
    for idx, pc in enumerate(p_calls, 1):
        print(
            f"  {idx}. Op: {pc.get('operation'):<15} | Status: {pc.get('response_status')} | "
            f"Usable: {pc.get('result_usable')} | Error: {pc.get('error_class') or 'None'}"
        )

    # Runs
    conn = connection.get_connection()
    try:
        run_rows = conn.execute(
            """
            SELECT r.*, c.condition_key, c.is_reference
            FROM runs r
            JOIN conditions c ON r.condition_id = c.id
            WHERE c.audit_id = ?
            ORDER BY r.id ASC
            """,
            (audit_id,),
        ).fetchall()
        runs = []
        for r in run_rows:
            rd = dict(r)
            run_id = rd["id"]
            rd["requested"] = json.loads(rd["requested"]) if rd.get("requested") else {}
            rd["observed"] = json.loads(rd["observed"]) if rd.get("observed") else {}
            rd["stage_captures"] = [dict(sc) for sc in conn.execute("SELECT * FROM stage_captures WHERE run_id = ?", (run_id,)).fetchall()]
            rd["charges"] = [dict(c) for c in conn.execute("SELECT * FROM charge_observations WHERE run_id = ?", (run_id,)).fetchall()]
            rd["disclosures"] = [dict(d) for d in conn.execute("SELECT * FROM disclosure_observations WHERE run_id = ?", (run_id,)).fetchall()]
            rd["urgency_indicators"] = [dict(u) for u in conn.execute("SELECT * FROM urgency_observations WHERE run_id = ?", (run_id,)).fetchall()]
            runs.append(rd)

        diffs = crud.get_diffs_for_audit(audit_id)
        findings = crud.get_findings_for_audit(audit_id)
    finally:
        conn.close()

    print(f"\nRuns Completed ({len(runs)}):")
    for r in runs:
        print(f"  Run ID: {r['id']} | Condition: {r['condition_key']}")
        print(f"  Provider Run ID: {r.get('provider_run_id')} | Provider Status: {r.get('provider_status')} | Outcome: {r.get('outcome')}")
        print(f"  Observed Subtotal: {r.get('observed', {}).get('subtotal_minor', 'N/A')} {r.get('observed', {}).get('currency', 'INR')}")

        print(f"  Stage Captures ({len(r['stage_captures'])}):")
        for sc in r["stage_captures"]:
            print(f"    - Step: {sc['step_name']:<16} | Status: {sc['capture_status']} | Inspection: {sc['inspection_status']} | Snapshot: {sc['snapshot_id']}")

        print(f"  Itemized Charges ({len(r['charges'])}):")
        for ch in r["charges"]:
            print(f"    - {ch['label']}: ₹{ch['amount_minor']/100:.2f} ({ch['canonical_label']}) | Step: {ch['step']} | Mandatory: {ch['mandatory']}")

        print(f"  Disclosures ({len(r['disclosures'])}):")
        for d in r["disclosures"]:
            print(f"    - {d['charge_label']}: {d['state']} at {d['step']} | Text: {d.get('visible_text')}")

        print(f"  Urgency Indicators ({len(r['urgency_indicators'])}):")
        for u in r["urgency_indicators"]:
            print(f"    - {u['text']} | Type: {u['type']} | Observed Remaining: {u.get('observed_seconds_remaining')}s")

    # Diffs
    print(f"\nDiffs Generated ({len(diffs)}):")
    for d in diffs:
        print(f"  - [{d['type']}] Key: {d.get('matching_key')} | Detail: {d.get('detail')}")

    # Findings
    print(f"\nFindings Persisted ({len(findings)}):")
    for f in findings:
        print(f"  - Category: {f['category'].upper()} | Severity: {f['severity']} | Conf: {f['confidence']}")
        print(f"    Explanation: {f['explanation']}")
        print(f"    Evidence IDs: {f.get('evidence_ids')}")

    # Assessment
    assessment = assess_audit_outcome(runs=runs, findings=findings, diffs=diffs)
    print("\n" + "=" * 70)
    print(f"FINAL AUDIT ASSESSMENT: {assessment['status'].upper()}")
    print("=" * 70)
    print(f"Status:                        {assessment['status']}")
    print(f"Summary:                       {assessment.get('summary')}")
    if assessment.get("inconclusive_reasons"):
        print(f"Inconclusive Reasons:")
        for reason in assessment["inconclusive_reasons"]:
            print(f"  - {reason}")

    # 6. Generate and Save HTML Report
    html_content = generate_html_report(
        audit=audit,
        conditions=conditions,
        diffs=diffs,
        findings=findings,
        provider_calls=p_calls,
        runs=runs,
    )
    report_file = Path(__file__).parent.parent / "data" / "evidence" / f"{audit_id}_report.html"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(html_content, encoding="utf-8")
    print(f"\n[6] HTML Report Generated:    {report_file}")

    # 7. Generate Complaint Draft
    draft = generate_complaint_draft(audit=audit, findings=findings, diffs=diffs, runs=runs)
    complaint_file = Path(__file__).parent.parent / "data" / "evidence" / f"{audit_id}_complaint.json"
    complaint_file.write_text(json.dumps(draft, indent=2), encoding="utf-8")
    print(f"[7] Complaint Draft Generated: {complaint_file}")

    # Persist audit summary JSON
    summary = {
        "audit_id": audit_id,
        "target_url": target_url,
        "merchant": merchant_name,
        "preset": preset,
        "elapsed_seconds": elapsed,
        "provider_calls_count": len(p_calls),
        "runs_count": len(runs),
        "diffs_count": len(diffs),
        "findings_count": len(findings),
        "assessment": assessment,
        "html_report_path": str(report_file),
        "complaint_draft_path": str(complaint_file),
    }
    summary_file = Path(__file__).parent.parent / "data" / "evidence" / f"{audit_id}_summary.json"
    summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[8] Audit Summary Saved:       {summary_file}")


if __name__ == "__main__":
    main()
