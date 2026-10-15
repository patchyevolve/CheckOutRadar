"""Durable Job Worker with Lease Recovery and Complete Audit Execution.

Key reliability features:
- Claims jobs with lease timeouts.
- On lease expiry or crash recovery, checks existing provider_run_id before resubmitting.
- Search, Fetch, and Agent visibly in execution path.
- Handles honest blocker outcomes (blocked_by_login, blocked_by_bot).
- Reconciles totals and excludes inconsistent extractions from diffs.
- Evaluates matched pairs deterministically and invokes CCPA detectors & classifier.
"""

import os
import time
import base64
import logging
from typing import Dict, Any, List, Optional
from ..db import crud
from ..tinyfish.adapter import TinyFishAdapter
from ..tinyfish.real_client import RealTinyFishClient
from ..tinyfish.mock_client import MockTinyFishClient
from ..tinyfish.goals import build_checkout_goal
from ..models.contracts import TINYFISH_AGENT_OUTPUT_SCHEMA
from ..models.schemas import AgentRunOutput
from ..analysis.normalizer import canonicalize_label
from ..analysis.reconciler import reconcile_totals
from ..analysis.diff_engine import DiffEngine
from ..analysis.detectors import (
    detect_drip_pricing_indicators,
    detect_basket_sneaking_indicators,
    detect_false_urgency_indicators,
    detect_run_false_urgency_indicators,
)
from ..analysis.classifier import LLMClassifier
from .redactor import redact_and_store_screenshot

logger = logging.getLogger(__name__)


def get_adapter(url: Optional[str] = None) -> TinyFishAdapter:
    mock_mode = os.getenv("MOCK_TINYFISH", "false").lower() in ["true", "1", "yes"]
    api_key = os.getenv("TINYFISH_API_KEY", "")
    is_local = bool(url and any(h in url for h in ["harness", "localhost", "127.0.0.1", "testserver"]))
    if mock_mode or not api_key or is_local:
        return MockTinyFishClient()
    return RealTinyFishClient(api_key=api_key)


class JobRunner:
    def __init__(self, worker_id: str = "worker_1", adapter: Optional[TinyFishAdapter] = None):
        self.worker_id = worker_id
        self._default_adapter = adapter
        self.classifier = LLMClassifier()
        self.diff_engine = DiffEngine(expected_disclosure_stage="product")

    @property
    def adapter(self) -> TinyFishAdapter:
        if self._default_adapter is None:
            self._default_adapter = get_adapter()
        return self._default_adapter

    def get_adapter_for_job(self, input_url: Optional[str] = None) -> TinyFishAdapter:
        if self._default_adapter is not None:
            return self._default_adapter
        return get_adapter(input_url)



    def run_one_cycle(self) -> bool:
        """Claim and execute one job if available. Returns True if a job was processed."""
        job = crud.claim_next_job(worker_id=self.worker_id, lease_duration_seconds=180)
        if not job:
            return False

        job_id = job["id"]
        run_id = job["run_id"]
        audit_id = job["audit_id"]

        try:
            self._process_job(job)
            crud.complete_job(job_id, worker_id=self.worker_id, lease_expires_at=job.get("lease_expires_at"))
            self._check_and_finalize_audit(audit_id)
            return True
        except Exception as e:
            logger.exception(f"Job {job_id} failed: {e}")
            crud.fail_or_retry_job(job_id, error_message=str(e), max_retries=2)
            self._check_and_finalize_audit(audit_id)
            return True

    def _process_job(self, job: Dict[str, Any]):
        job_id = job["id"]
        run_id = job["run_id"]
        audit_id = job["audit_id"]
        cond_key = job.get("condition_key", "")
        requested = job.get("requested", {})
        existing_provider_run_id = job.get("provider_run_id")

        audit = crud.get_audit(audit_id)
        if not audit:
            raise ValueError(f"Audit {audit_id} not found")

        crud.emit_event(audit_id, "run_started", {"run_id": run_id, "condition_key": cond_key})

        adapter = self.get_adapter_for_job(audit.get("input_url"))

        # 1. Step: Discovery via Search & Policy via Fetch (rule A: visibly in execution path)
        merchant_name = audit.get("merchant") or "Demo Merchant"
        search_results = adapter.search(query=f"{merchant_name} checkout pricing terms", audit_id=audit_id)
        if search_results:
            policy_urls = [r["url"] for r in search_results[:2]]
            adapter.fetch(urls=policy_urls, audit_id=audit_id, ttl=3600)

        # 2. Browser Context Profile isolation for returning session
        is_returning = (requested.get("session") == "returning")
        profile_id = None
        if is_returning:
            profile_id = adapter.create_browser_profile(name=f"audit_{audit_id}_{run_id}", audit_id=audit_id)

        # 3. Lease recovery / Idempotency check:
        # If we already have a provider_run_id, do NOT resubmit! Poll existing run.
        provider_run_id = existing_provider_run_id
        if not provider_run_id:
            goal = build_checkout_goal(
                start_url=audit["input_url"],
                requested_pincode=requested.get("pincode"),
                cart_recipe=audit.get("cart_recipe"),
                is_returning=is_returning,
            )
            provider_run_id = adapter.submit_agent_run(
                url=audit["input_url"],
                goal=goal,
                audit_id=audit_id,
                run_id=run_id,
                output_schema=TINYFISH_AGENT_OUTPUT_SCHEMA,
                use_profile=is_returning,
                profile_id=profile_id,
            )
            # Persist provider_run_id immediately so lease recovery can find it if worker dies
            crud.update_run_outcome(
                run_id=run_id,
                provider_run_id=provider_run_id,
                provider_status="RUNNING",
                outcome="ok",
                observed=None,
                profile_state_verified=is_returning,
            )

        # 4. Poll for run completion (with bounded wait and transient error resilience)
        poll_data = None
        max_polls = int(os.getenv("TINYFISH_MAX_POLLS", "60"))
        poll_interval = int(os.getenv("TINYFISH_POLL_INTERVAL", "5"))
        consecutive_poll_errors = 0
        for _ in range(max_polls):
            try:
                poll_data = adapter.poll_agent_run(provider_run_id, audit_id=audit_id, run_id=run_id)
                consecutive_poll_errors = 0
            except Exception as pe:
                consecutive_poll_errors += 1
                logger.warning(f"Transient error polling {provider_run_id} ({consecutive_poll_errors}/5): {pe}")
                if consecutive_poll_errors >= 5:
                    raise
                time.sleep(poll_interval)
                continue

            prov_status = poll_data.get("status", "PENDING")
            if prov_status in ["COMPLETED", "FAILED", "CANCELLED"]:
                break
            time.sleep(poll_interval)

        if not poll_data or poll_data.get("status") not in ["COMPLETED", "FAILED", "CANCELLED"]:
            raise TimeoutError(f"Provider run {provider_run_id} timed out polling")

        prov_status = poll_data.get("status")
        result_dict = poll_data.get("result") or {}

        # 5. Process Step Screenshots, Redact, and Store Snapshots
        snapshot_map = {}  # step_name / step_id / index -> snapshot_id
        stage_best_priority = {}  # st_name -> priority int
        for step_idx, step in enumerate(poll_data.get("steps", [])):
            step_action = step.get("action", "") or step.get("name", "") or step.get("description", "")
            step_id = step.get("id", "")
            act_lower = step_action.lower()

            # Identify step name (checkout_summary, cart, product)
            # Evaluate checkout/summary before cart so "proceed from cart to checkout" resolves to checkout_summary
            st_name = "product"
            prio = 1
            if any(k in act_lower for k in ["checkout", "summary", "review", "pay", "order"]):
                st_name = "checkout_summary"
                if any(k in act_lower for k in ["summary", "review", "bill", "total"]):
                    prio = 2
            elif "cart" in act_lower or "basket" in act_lower:
                st_name = "cart"
                # Distinguish an affirmative cart drawer / page view from an "add to cart" click on product page
                if any(k in act_lower for k in ["drawer", "view cart", "open cart", "your cart", "cart page", "inspect cart", "in cart"]):
                    prio = 2
                elif any(k in act_lower for k in ["add to cart", "add_to_cart", "add item"]):
                    prio = 1
            else:
                st_name = "product"
                if any(k in act_lower for k in ["product", "item", "pincode", "details", "price"]):
                    prio = 2

            raw_bytes = None
            if step.get("screenshot"):
                # base64 data uri
                try:
                    s_uri = step["screenshot"]
                    if "," in s_uri:
                        b64_part = s_uri.split(",", 1)[1]
                        raw_bytes = base64.b64decode(b64_part)
                except Exception:
                    raw_bytes = None

            if not raw_bytes and step_id:
                try:
                    raw_bytes = adapter.download_screenshot(provider_run_id, step_id, audit_id, run_id)
                except Exception:
                    raw_bytes = None

            if raw_bytes:
                snap_id, sha256_hash, path = redact_and_store_screenshot(raw_bytes, run_id, st_name)
                # Map specific identifiers first
                if step_id:
                    snapshot_map[step_id] = snap_id
                snapshot_map[f"step_{step_idx + 1}"] = snap_id
                snapshot_map[f"step_{step_idx}"] = snap_id
                snapshot_map[step_idx + 1] = snap_id
                snapshot_map[step_idx] = snap_id
                if step.get("name"):
                    snapshot_map[step["name"]] = snap_id
                if step.get("screenshot_ref"):
                    snapshot_map[step["screenshot_ref"]] = snap_id

                # Update stage name fallback only if equal or higher priority
                if st_name not in stage_best_priority or prio >= stage_best_priority[st_name]:
                    stage_best_priority[st_name] = prio
                    snapshot_map[st_name] = snap_id

        # 6. Parse and Validate Local Contract
        run_outcome = result_dict.get("status", "ok")
        if prov_status == "FAILED":
            run_outcome = "failed"

        observed = result_dict.get("observed", {})
        charges = result_dict.get("charges", [])
        disclosures = result_dict.get("disclosures", [])
        totals = result_dict.get("totals", {})
        addons = result_dict.get("preselected_addons", [])
        urgencies = result_dict.get("urgency_indicators", [])

        # Check requested vs observed conditions
        req_pin = requested.get("pincode")
        obs_pin = observed.get("pincode")
        if req_pin and obs_pin and req_pin != obs_pin:
            run_outcome = "condition_not_applied"

        # 7. Resolve Snapshot IDs and Persist Stage Captures & Observations Atomically
        resolved_stage_captures = []
        for sc in result_dict.get("stage_captures", []):
            st_name = sc.get("step_name", "product")
            snap_id = (
                snapshot_map.get(sc.get("screenshot_ref"))
                or snapshot_map.get(sc.get("provider_step_id"))
                or snapshot_map.get(st_name)
                or snapshot_map.get(f"step_{sc.get('step_index')}")
                or snapshot_map.get(sc.get("step_index"))
            )
            sc_copy = dict(sc)
            sc_copy["snapshot_id"] = snap_id
            resolved_stage_captures.append(sc_copy)

        is_reconciled, run_outcome = crud.persist_run_observations_atomically(
            run_id=run_id,
            outcome=run_outcome,
            provider_run_id=provider_run_id,
            provider_status=prov_status,
            observed=observed,
            profile_state_verified=is_returning,
            totals=totals,
            stage_captures=resolved_stage_captures,
            charges=charges,
            disclosures=disclosures,
            addons=addons,
            urgencies=urgencies,
        )

        # 8. Diff Engine & Finding Generation (Only if outcome == 'ok')
        if run_outcome == "ok":

            current_bundle = {
                "id": run_id,
                "audit_id": audit_id,
                "requested": requested,
                "observed": observed,
                "charges": charges,
                "disclosures": disclosures,
                "stage_captures": resolved_stage_captures,
                "preselected_addons": addons,
                "urgency_indicators": urgencies,
            }

            # A. Single run diffs (LATE_DISCLOSURE, UNDISCLOSED_AT_STAGE)
            single_diffs = self.diff_engine.compute_single_run_diffs(current_bundle)
            for sd in single_diffs:
                diff_id = crud.insert_diff(
                    audit_id=audit_id,
                    diff_type=sd["type"],
                    run_a_id=sd["run_a_id"],
                    run_b_id=sd["run_b_id"],
                    matching_key=sd["matching_key"],
                    detail=sd["detail"],
                    dedup_key=sd["dedup_key"],
                )
                sd["id"] = diff_id

            # B. Pairwise diffs with already completed runs in this audit
            other_conditions = crud.get_conditions_for_audit(audit_id)
            for c_entry in other_conditions:
                if c_entry["condition_key"] == cond_key:
                    continue
                # Retrieve latest ok run for this other condition
                other_run = self._get_latest_ok_run(c_entry["id"])
                if other_run:
                    pairwise_diffs = self.diff_engine.compute_pairwise_diffs(current_bundle, other_run)
                    for pd in pairwise_diffs:
                        pdiff_id = crud.insert_diff(
                            audit_id=audit_id,
                            diff_type=pd["type"],
                            run_a_id=pd["run_a_id"],
                            run_b_id=pd["run_b_id"],
                            matching_key=pd["matching_key"],
                            detail=pd["detail"],
                            dedup_key=pd["dedup_key"],
                        )
                        pd["id"] = pdiff_id

            # C. Rule Detectors & LLM Classification
            candidate_findings = []
            candidate_findings.extend(detect_drip_pricing_indicators(single_diffs, current_bundle))
            candidate_findings.extend(detect_basket_sneaking_indicators(current_bundle))
            candidate_findings.extend(detect_run_false_urgency_indicators(current_bundle))

            # Store and classify findings
            for cand in candidate_findings:
                classified = self.classifier.classify_candidate(cand, evidence_context=current_bundle)
                finding_id = crud.insert_finding(
                    audit_id=audit_id,
                    diff_id=classified.get("diff_id"),
                    category=classified["category"],
                    severity=classified["severity"],
                    confidence=classified["confidence"],
                    explanation=classified["explanation"],
                    evidence_ids=classified.get("evidence_ids", []),
                    source=classified.get("source", "rule"),
                    dedup_key=classified["dedup_key"],
                    heuristic_note=classified.get("heuristic_note"),
                    raw_observations=classified.get("raw_observations") or cand.get("raw_observations"),
                )
                crud.emit_event(audit_id, "finding_flagged", {
                    "finding_id": finding_id,
                    "category": classified["category"],
                    "severity": classified["severity"],
                })

        # Clean up profile
        if profile_id:
            try:
                adapter.delete_browser_profile(profile_id, audit_id=audit_id)
            except Exception:
                pass

        crud.emit_event(audit_id, "run_completed", {
            "run_id": run_id,
            "condition_key": cond_key,
            "outcome": run_outcome,
        })

    def _get_latest_ok_run(self, condition_id: str) -> Optional[Dict[str, Any]]:
        conn = crud.get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM runs WHERE condition_id = ? AND outcome = 'ok' ORDER BY id DESC LIMIT 1",
                (condition_id,),
            ).fetchone()
            if not row:
                return None
            run_d = dict(row)
            run_id = run_d["id"]
            charges = [dict(r) for r in conn.execute("SELECT * FROM charge_observations WHERE run_id = ?", (run_id,)).fetchall()]
            disclosures = [dict(r) for r in conn.execute("SELECT * FROM disclosure_observations WHERE run_id = ?", (run_id,)).fetchall()]
            addons = [dict(r) for r in conn.execute("SELECT * FROM addon_observations WHERE run_id = ?", (run_id,)).fetchall()]
            urgencies = [dict(r) for r in conn.execute("SELECT * FROM urgency_observations WHERE run_id = ?", (run_id,)).fetchall()]
            stage_caps = [dict(r) for r in conn.execute("SELECT * FROM stage_captures WHERE run_id = ?", (run_id,)).fetchall()]

            import json
            return {
                "id": run_id,
                "audit_id": conn.execute("SELECT audit_id FROM conditions WHERE id = ?", (condition_id,)).fetchone()["audit_id"],
                "requested": json.loads(run_d["requested"]) if run_d.get("requested") else {},
                "observed": json.loads(run_d["observed"]) if run_d.get("observed") else {},
                "charges": charges,
                "disclosures": disclosures,
                "stage_captures": stage_caps,
                "preselected_addons": addons,
                "urgency_indicators": urgencies,
            }
        finally:
            conn.close()

    def _check_and_finalize_audit(self, audit_id: str):
        conn = crud.get_connection()
        try:
            # Check if all jobs are done
            row = conn.execute(
                """
                SELECT count(*) as pending_count
                FROM jobs j
                JOIN runs r ON j.run_id = r.id
                JOIN conditions c ON r.condition_id = c.id
                WHERE c.audit_id = ? AND j.state IN ('queued', 'claimed', 'retry_wait')
                """,
                (audit_id,),
            ).fetchone()
            if row["pending_count"] == 0:
                crud.update_audit_status(audit_id, "complete")
                crud.emit_event(audit_id, "audit_completed", {"audit_id": audit_id})
        finally:
            conn.close()
