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
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel
from .db import crud, connection
from .models.schemas import CreateAuditRequest, AuditResponse
from .matrix.orchestrator import expand_matrix
from .worker.job_runner import JobRunner
from .worker.redactor import get_evidence_dir
from .reports.html_report import generate_html_report
from .reports.complaint_draft import generate_complaint_draft
from .analysis.detectors import assess_audit_outcome
from .services.settings_service import get_settings_manager

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
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_FRONTEND = str(_REPO_ROOT / "frontend") if (_REPO_ROOT / "frontend").exists() else "/app/frontend"
FRONTEND_DIR = os.getenv("FRONTEND_DIR", _DEFAULT_FRONTEND)
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    def serve_landing(audit_id: Optional[str] = None):
        """
        Serve Product Landing Page at root.
        Preserves backward compatibility: if audit_id query parameter is present,
        redirects to /auditor?audit_id=...
        """
        if audit_id:
            return RedirectResponse(url=f"/auditor?audit_id={audit_id}", status_code=307)
        landing_file = os.path.join(FRONTEND_DIR, "index.html")
        with open(landing_file, "r", encoding="utf-8") as f:
            return f.read()

    @app.get("/auditor", response_class=HTMLResponse)
    def serve_auditor(audit_id: Optional[str] = None):
        """
        Serve Forensic Auditor Investigation Workspace.
        """
        auditor_file = os.path.join(FRONTEND_DIR, "auditor.html")
        if not os.path.exists(auditor_file):
            # Fallback if auditor.html doesn't exist
            auditor_file = os.path.join(FRONTEND_DIR, "index.html")
        with open(auditor_file, "r", encoding="utf-8") as f:
            return f.read()


ALLOWED_EVIDENCE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".html", ".json"}

@app.get("/evidence/{filename:path}")
def get_evidence_file(filename: str):
    """
    Safely serve generated evidence artifacts from the configured evidence directory.
    Enforces strict path traversal defenses, disallows dangerous extensions (.db, .env, .py),
    and ensures only regular files within EVIDENCE_DIR are served.
    """
    if not filename or "\x00" in filename:
        raise HTTPException(status_code=404, detail="Evidence file not found")

    path_obj = Path(filename)
    if ".." in path_obj.parts or path_obj.is_absolute():
        raise HTTPException(status_code=404, detail="Evidence file not found")

    ext = path_obj.suffix.lower()
    if ext not in ALLOWED_EVIDENCE_EXTENSIONS:
        raise HTTPException(status_code=404, detail="Evidence file not found")

    ev_dir = get_evidence_dir().resolve()
    target_path = (ev_dir / filename).resolve()

    # Enforce strictly that target_path resides within ev_dir
    try:
        target_path.relative_to(ev_dir)
    except ValueError:
        raise HTTPException(status_code=404, detail="Evidence file not found")

    if not target_path.is_file():
        raise HTTPException(status_code=404, detail="Evidence file not found")

    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".html": "text/html; charset=utf-8",
        ".json": "application/json",
    }.get(ext, "application/octet-stream")

    return FileResponse(path=str(target_path), media_type=media_type)



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
        # Extract host or map synthetic harness variants to explicit descriptive names
        import urllib.parse
        parsed = urllib.parse.urlparse(req.input_url)
        path = (parsed.path or "").lower()
        netloc = (parsed.netloc or "").lower()
        if "harness" in netloc or "localhost" in netloc or "127.0.0.1" in netloc:
            if "clean" in path:
                merchant = "Demo Harness (Clean Upfront)"
            elif "late" in path:
                merchant = "Demo Harness (Drip Pricing / Late Fee)"
            elif "addon" in path or "countdown" in path:
                merchant = "Demo Harness (Basket Sneak + Urgency)"
            elif "upfront" in path:
                merchant = "Demo Harness (Upfront Convenience)"
            elif "threshold" in path:
                merchant = "Demo Harness (Cart Threshold Policy)"
            else:
                merchant = "Demo Harness (Synthetic Variant)"
        elif "headphonezone" in netloc:
            merchant = "Headphone Zone (Live Merchant)"
        else:
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
            run_id = rd["id"]
            rd["requested"] = json.loads(rd["requested"]) if rd.get("requested") else {}
            sc_rows = conn.execute(
                """
                SELECT 
                    sc.*,
                    s.artifact_path,
                    s.sha256 as snapshot_sha256,
                    s.captured_at as snapshot_captured_at
                FROM stage_captures sc
                LEFT JOIN snapshots s ON sc.snapshot_id = s.id
                WHERE sc.run_id = ?
                ORDER BY sc.step_index ASC
                """,
                (run_id,),
            ).fetchall()

            stage_captures = []
            for sc in sc_rows:
                sc_dict = dict(sc)
                # Fallback to finding snapshot by step_name if not directly joined via snapshot_id
                if not sc_dict.get("snapshot_sha256") and sc_dict.get("step_name"):
                    fallback_snap = conn.execute(
                        "SELECT * FROM snapshots WHERE run_id = ? AND step_name = ? ORDER BY captured_at DESC LIMIT 1",
                        (run_id, sc_dict["step_name"]),
                    ).fetchone()
                    if fallback_snap:
                        f_dict = dict(fallback_snap)
                        sc_dict["snapshot_id"] = sc_dict.get("snapshot_id") or f_dict["id"]
                        sc_dict["snapshot_sha256"] = f_dict["sha256"]
                        sc_dict["snapshot_captured_at"] = f_dict["captured_at"]
                        sc_dict["artifact_path"] = f_dict["artifact_path"]

                art_path = sc_dict.get("artifact_path")
                if art_path:
                    fname = Path(art_path).name
                    sc_dict["evidence_filename"] = fname
                    sc_dict["evidence_url"] = f"/evidence/{fname}"
                else:
                    sc_dict["evidence_filename"] = None
                    sc_dict["evidence_url"] = None
                stage_captures.append(sc_dict)

            rd["stage_captures"] = stage_captures
            rd["snapshots"] = [dict(s) for s in conn.execute("SELECT * FROM snapshots WHERE run_id = ?", (run_id,)).fetchall()]
            rd["charges"] = [dict(c) for c in conn.execute("SELECT * FROM charge_observations WHERE run_id = ?", (run_id,)).fetchall()]
            rd["disclosures"] = [dict(d) for d in conn.execute("SELECT * FROM disclosure_observations WHERE run_id = ?", (run_id,)).fetchall()]
            rd["urgency_indicators"] = [dict(u) for u in conn.execute("SELECT * FROM urgency_observations WHERE run_id = ?", (run_id,)).fetchall()]
            runs.append(rd)

        findings = crud.get_findings_for_audit(audit_id)
        diffs = crud.get_diffs_for_audit(audit_id)
        assessment = assess_audit_outcome(runs=runs, findings=findings, diffs=diffs)

        return {
            "audit": audit,
            "conditions": conditions,
            "runs": runs,
            "diffs_count": len(diffs),
            "findings_count": len(findings),
            "assessment": assessment,
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

    conn = connection.get_connection()
    try:
        rows = conn.execute(
            "SELECT r.* FROM runs r JOIN conditions c ON r.condition_id = c.id WHERE c.audit_id = ?",
            (audit_id,),
        ).fetchall()
        runs = [dict(r) for r in rows]
    finally:
        conn.close()

    draft = generate_complaint_draft(audit=audit, findings=findings, diffs=diffs, runs=runs)
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


class UpdateSettingsRequest(BaseModel):
    llm_base_url: Optional[str] = None
    llm_model: Optional[str] = None
    llm_api_key: Optional[str] = None
    clear_llm_key: Optional[bool] = False
    tinyfish_api_key: Optional[str] = None
    clear_tinyfish_key: Optional[bool] = False
    mock_tinyfish: Optional[bool] = None
    llm_provider: Optional[str] = None
    llm_pacing_seconds: Optional[float] = None


class TestLLMRequest(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


@app.get("/settings")
def get_settings():
    """Retrieve public provider settings with all secrets safely masked."""
    return get_settings_manager().get_public_settings()


@app.post("/settings")
def update_settings(req: UpdateSettingsRequest):
    """Update provider settings on backend and persist to database. Never echoes raw secrets."""
    try:
        updated = get_settings_manager().update_settings(req.model_dump(exclude_unset=True))
        return updated
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/settings/test-llm")
def test_llm_connection(req: TestLLMRequest):
    """Execute an isolated test request to verify LLM endpoint and model. Secrets are strictly redacted."""
    res = get_settings_manager().test_llm_connection(
        base_url=req.base_url,
        api_key=req.api_key,
        model=req.model,
    )
    return res


@app.get("/health")
def health_check():
    settings = get_settings_manager().get_public_settings()
    return {
        "status": "healthy",
        "service": "checkout-radar-api",
        "mock_mode": settings["mock_tinyfish"],
        "has_tinyfish_key": settings["has_tinyfish_key"],
        "has_llm_key": settings["has_llm_key"],
    }

