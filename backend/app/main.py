"""Checkout Radar — FastAPI Application & API Surface.

Endpoints:
- POST /audits: Create and launch audit matrix
- GET /audits: List all audits
- GET /audits/{id}: Status, runs, conditions
- GET /audits/{id}/stream: SSE live agent progress stream
- GET /audits/{id}/diff: Matched-pair matrix diffs
- GET /audits/{id}/findings: Flagged indicators with CCPA mapping and evidence
- GET /audits/{id}/report: Exportable HTML report
- POST /audits/{id}/complaint-draft: Draft grievance text (never auto-submitted)
- POST /audits/{id}/reobserve: Manual temporal re-observation
- GET /audits/{id}/provider-calls: Audited TinyFish calls log
- GET /health: Health check
"""

import os
import json
import asyncio
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .db import crud, connection
from .models.schemas import CreateAuditRequest, AuditResponse
from .matrix.orchestrator import expand_matrix
from .worker.job_runner import JobRunner
from .reports.html_report import generate_html_report
from .reports.complaint_draft import generate_complaint_draft

app = FastAPI(
    title="Checkout Radar API",
    version="1.0.0",
    description="Outside-in checkout flow auditor and CCPA 2023 dark pattern indicator detector",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    connection.init_db()


# Mount frontend static files and serve dashboard at root
FRONTEND_DIR = os.getenv("FRONTEND_DIR", "/home/daksh/working/checkout-radar/frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    def serve_dashboard():
        index_file = os.path.join(FRONTEND_DIR, "index.html")
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()



def run_worker_drain():
    """Background task to drain the job queue."""
    runner = JobRunner(worker_id="bg_worker")
    while runner.run_one_cycle():
        pass


# -------------------------------------------------------------
# Audits Endpoints
# -------------------------------------------------------------

@app.post("/audits", response_model=Dict[str, Any])
def submit_audit(req: CreateAuditRequest, background_tasks: BackgroundTasks):
    merchant = req.merchant
    if not merchant:
        # Extract host as default merchant
        import urllib.parse
        parsed = urllib.parse.urlparse(req.input_url)
        merchant = parsed.netloc or "Demo Merchant"

    recipe_dict = req.cart_recipe.dict() if req.cart_recipe else None

    audit_id = crud.create_audit(
        input_url=req.input_url,
        merchant=merchant,
        preset=req.preset,
        cart_recipe=recipe_dict,
        schedule_interval=req.schedule_interval,
    )

    # Expand condition matrix and enqueue durable jobs
    conditions = expand_matrix(audit_id=audit_id, preset=req.preset, cart_recipe=recipe_dict)

    crud.update_audit_status(audit_id, "running")
    crud.emit_event(audit_id, "audit_started", {
        "audit_id": audit_id,
        "merchant": merchant,
        "preset": req.preset,
        "conditions_count": len(conditions),
    })

    # Trigger worker execution in background
    background_tasks.add_task(run_worker_drain)

    return {
        "id": audit_id,
        "merchant": merchant,
        "preset": req.preset,
        "status": "running",
        "conditions_count": len(conditions),
    }


@app.get("/audits", response_model=List[Dict[str, Any]])
def list_audits():
    conn = connection.get_connection()
    try:
        rows = conn.execute("SELECT * FROM audits ORDER BY created_at DESC").fetchall()
        res = []
        for r in rows:
            d = dict(r)
            cond_count = conn.execute("SELECT count(*) as c FROM conditions WHERE audit_id = ?", (d["id"],)).fetchone()["c"]
            run_count = conn.execute(
                "SELECT count(*) as c FROM runs r JOIN conditions c ON r.condition_id = c.id WHERE c.audit_id = ? AND r.finished_at IS NOT NULL",
                (d["id"],),
            ).fetchone()["c"]
            finding_count = conn.execute("SELECT count(*) as c FROM findings WHERE audit_id = ?", (d["id"],)).fetchone()["c"]
            d["conditions_count"] = cond_count
            d["completed_runs"] = run_count
            d["findings_count"] = finding_count
            res.append(d)
        return res
    finally:
        conn.close()


@app.get("/audits/{audit_id}")
def get_audit_details(audit_id: str):
    audit = crud.get_audit(audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")

    conditions = crud.get_conditions_for_audit(audit_id)
    conn = connection.get_connection()
    try:
        runs_rows = conn.execute(
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
        for r in runs_rows:
            rd = dict(r)
            rd["requested"] = json.loads(rd["requested"]) if rd.get("requested") else {}
            rd["observed"] = json.loads(rd["observed"]) if rd.get("observed") else {}
            runs.append(rd)

        findings = crud.get_findings_for_audit(audit_id)
        diffs = crud.get_diffs_for_audit(audit_id)

        return {
            "audit": audit,
            "conditions": conditions,
            "runs": runs,
            "diffs_count": len(diffs),
            "findings_count": len(findings),
        }
    finally:
        conn.close()


@app.get("/audits/{audit_id}/stream")
async def stream_audit_progress(audit_id: str, last_event_id: int = Query(0)):
    """Server-Sent Events (SSE) live progress stream with reconnection support."""
    audit = crud.get_audit(audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")

    async def event_generator():
        current_seq = last_event_id
        while True:
            events = crud.get_events_for_audit(audit_id, after_seq=current_seq)
            for ev in events:
                current_seq = ev["seq"]
                payload = json.dumps(ev["payload"])
                yield f"id: {ev['seq']}\nevent: {ev['type']}\ndata: {payload}\n\n"

            # Check if audit is finished
            a = crud.get_audit(audit_id)
            if a and a.get("status") in ["complete", "failed"] and not events:
                yield "event: complete\ndata: {}\n\n"
                break

            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/audits/{audit_id}/diff")
def get_audit_diffs(audit_id: str):
    audit = crud.get_audit(audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")
    diffs = crud.get_diffs_for_audit(audit_id)
    return {"audit_id": audit_id, "diffs": diffs}


@app.get("/audits/{audit_id}/findings")
def get_audit_findings(audit_id: str):
    audit = crud.get_audit(audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")
    findings = crud.get_findings_for_audit(audit_id)
    return {"audit_id": audit_id, "findings": findings}


@app.get("/audits/{audit_id}/report", response_class=HTMLResponse)
def get_audit_report(audit_id: str):
    audit = crud.get_audit(audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")

    conditions = crud.get_conditions_for_audit(audit_id)
    diffs = crud.get_diffs_for_audit(audit_id)
    findings = crud.get_findings_for_audit(audit_id)
    provider_calls = crud.get_provider_calls_for_audit(audit_id)

    html = generate_html_report(
        audit=audit,
        conditions=conditions,
        diffs=diffs,
        findings=findings,
        provider_calls=provider_calls,
    )
    return HTMLResponse(content=html)


@app.post("/audits/{audit_id}/complaint-draft")
def get_complaint_draft_endpoint(audit_id: str):
    audit = crud.get_audit(audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")

    diffs = crud.get_diffs_for_audit(audit_id)
    findings = crud.get_findings_for_audit(audit_id)

    draft = generate_complaint_draft(audit=audit, findings=findings, diffs=diffs)
    return draft


@app.post("/audits/{audit_id}/reobserve")
def trigger_temporal_reobservation(audit_id: str, background_tasks: BackgroundTasks):
    """
    Trigger manual temporal re-observation.
    Appends a new run to the reference condition to produce temporal diffs.
    """
    audit = crud.get_audit(audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")

    conn = connection.get_connection()
    try:
        ref_cond = conn.execute(
            "SELECT * FROM conditions WHERE audit_id = ? AND is_reference = 1 LIMIT 1",
            (audit_id,),
        ).fetchone()
        if not ref_cond:
            raise HTTPException(status_code=400, detail="No reference condition found")

        # Create new run attempt
        run_count = conn.execute("SELECT count(*) as c FROM runs WHERE condition_id = ?", (ref_cond["id"],)).fetchone()["c"]
        req = json.loads(ref_cond["requested"])

        new_run_id = crud.create_run(
            condition_id=ref_cond["id"],
            requested=req,
            attempt=run_count + 1,
        )
        crud.enqueue_job(run_id=new_run_id)
        crud.update_audit_status(audit_id, "running")

        crud.emit_event(audit_id, "temporal_reobserve_started", {"new_run_id": new_run_id})
        background_tasks.add_task(run_worker_drain)

        return {"status": "enqueued", "new_run_id": new_run_id, "attempt": run_count + 1}
    finally:
        conn.close()


@app.get("/audits/{audit_id}/provider-calls")
def get_provider_calls(audit_id: str):
    calls = crud.get_provider_calls_for_audit(audit_id)
    return {"audit_id": audit_id, "provider_calls": calls}


@app.get("/health")
def health_check():
    mock_mode = os.getenv("MOCK_TINYFISH", "false").lower() in ["true", "1", "yes"]
    return {
        "status": "healthy",
        "service": "checkout-radar-api",
        "mock_mode": mock_mode,
        "has_tinyfish_key": bool(os.getenv("TINYFISH_API_KEY")),
        "has_llm_key": bool(os.getenv("LLM_API_KEY")),
    }
