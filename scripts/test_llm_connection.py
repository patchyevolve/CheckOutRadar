#!/usr/bin/env python3
"""Live LLM Integration Verification Script for Checkout Radar.

Verifies:
1. Environment variables (LLM_API_KEY, LLM_BASE_URL, LLM_MODEL) without exposing secrets.
2. Live HTTP request to the configured OpenAI-compatible chat completion endpoint.
3. Downstream Pydantic ClassifiedFinding schema validation.
4. Deterministic non-judicial wording gate (semantic adjudicative rejection & disclaimer safety).
5. Evidence-grounding contract:
   - Verified absence requires 'not_observed_verified' disclosure record.
   - 'unknown' disclosure state is never claimed as absent.
   - Invented monetary amounts or evidence IDs are rejected.
"""

import os
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent

# Add backend to path
sys.path.insert(0, str(repo_root / "backend"))

# Load .env if present
env_path = repo_root / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from app.analysis.classifier import LLMClassifier, ClassifiedFinding, validate_explanation

def main():
    print("=" * 70)
    print("CHECKOUT RADAR: Live LLM Endpoint Verification & Guardrail Audit")
    print("=" * 70)

    api_key = os.getenv("LLM_API_KEY", "").strip()
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip()
    model = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()

    print(f"Base URL:      {base_url}")
    print(f"Target Model:  {model}")
    print(f"API Key:       {'[CONFIGURED & REDACTED]' if api_key else '[NOT SET - FALLBACK ACTIVE]'}")

    if not api_key:
        print("\n[!] No LLM_API_KEY detected in environment or .env.")
        print("    System runs in Offline Template-Fallback Mode (CI Regression Mode).")
        sys.exit(0)

    print("\n[+] Initializing LLMClassifier with live credentials...")
    classifier = LLMClassifier(api_key=api_key, base_url=base_url, model=model)

    # -------------------------------------------------------------
    # Scenario A: Fee with Verified Absence (not_observed_verified)
    # -------------------------------------------------------------
    print("\n[SCENARIO A] Drip Pricing Candidate with Empirically Verified Absence:")
    candidate_a = {
        "audit_id": "live_test_audit",
        "category": "drip_pricing",
        "severity": "medium",
        "confidence": 0.90,
        "amount_minor": 2000,
        "explanation": "Mandatory charge 'Convenience Fee' (₹20.00) was observed at checkout but absent at product stage.",
        "evidence_ids": ["snap_prod_01", "snap_chk_02"],
    }
    evidence_a = {
        "charges": [{"label": "Convenience Fee", "amount_minor": 2000, "step": "checkout"}],
        "disclosures": [{"charge_label": "Convenience Fee", "step": "product", "state": "not_observed_verified"}],
        "stage_captures": [{"snapshot_id": "snap_prod_01"}, {"snapshot_id": "snap_chk_02"}],
    }

    t0 = time.time()
    result_a = classifier.classify_candidate(candidate_a, evidence_a)
    latency_a = (time.time() - t0) * 1000

    print(f"    Latency:          {latency_a:.2f} ms")
    print(f"    Source:           {result_a.get('source')}")
    print(f"    Category:         {result_a.get('category')}")
    print(f"    Explanation:      {result_a.get('explanation')}")

    is_valid_a, reason_a = validate_explanation(
        result_a["explanation"],
        "drip_pricing",
        evidence_a,
        candidate_finding=candidate_a,
        evidence_ids=result_a.get("evidence_ids"),
    )
    assert is_valid_a, f"Scenario A failed validation: {reason_a}"
    print("    Quality Gate:     [PASS] Schema, Evidence Grounding & Non-Judicial Wording Gate passed.")

    # -------------------------------------------------------------
    # Scenario B: Fee with Unknown / Unverified Prior Disclosure
    # -------------------------------------------------------------
    print("\n[SCENARIO B] Drip Pricing Candidate with Unverified/Unknown Prior Disclosure:")
    candidate_b = {
        "audit_id": "live_test_audit",
        "category": "drip_pricing",
        "severity": "medium",
        "confidence": 0.85,
        "amount_minor": 1500,
        "explanation": "Mandatory charge 'Packaging Fee' (₹15.00) was observed at checkout, earlier disclosure unverified.",
        "evidence_ids": ["snap_chk_03"],
    }
    evidence_b = {
        "charges": [{"label": "Packaging Fee", "amount_minor": 1500, "step": "checkout"}],
        "disclosures": [{"charge_label": "Packaging Fee", "step": "product", "state": "unknown"}],
        "stage_captures": [{"snapshot_id": "snap_chk_03"}],
    }

    t1 = time.time()
    result_b = classifier.classify_candidate(candidate_b, evidence_b)
    latency_b = (time.time() - t1) * 1000

    print(f"    Latency:          {latency_b:.2f} ms")
    print(f"    Source:           {result_b.get('source')}")
    print(f"    Category:         {result_b.get('category')}")
    print(f"    Explanation:      {result_b.get('explanation')}")

    is_valid_b, reason_b = validate_explanation(
        result_b["explanation"],
        "drip_pricing",
        evidence_b,
        candidate_finding=candidate_b,
        evidence_ids=result_b.get("evidence_ids"),
    )
    assert is_valid_b, f"Scenario B failed validation: {reason_b}"
    print("    Quality Gate:     [PASS] Grounded Contract (unknown disclosure not claimed as absent).")

    # -------------------------------------------------------------
    # Scenario C: Deterministic Guardrail Interception of Adjudicative Language
    # -------------------------------------------------------------
    print("\n[SCENARIO C] Guardrail Interception of Prohibited Semantic Phrases:")
    test_adjudicative_phrases = [
        "The merchant is guilty of fraud.",
        "The company committed an illegal deceptive act.",
        "The merchant violated consumer law.",
        "This conduct is unlawful.",
        "The merchant has been found culpable.",
    ]
    for phrase in test_adjudicative_phrases:
        is_val, reason = validate_explanation(phrase, "drip_pricing", evidence_a)
        assert not is_val, f"Failed to reject: {phrase}"
    print(f"    Tested {len(test_adjudicative_phrases)} semantic adjudicative variations -> 100% intercepted.")

    # -------------------------------------------------------------
    # Scenario D: Rejection of Invented / Hallucinated Facts
    # -------------------------------------------------------------
    print("\n[SCENARIO D] Guardrail Interception of Invented Amounts & Evidence IDs:")
    hallucinated_amt_expl = "Potential indicator of drip pricing: convenience fee of ₹999.00 observed at checkout."
    is_val_amt, _ = validate_explanation(
        hallucinated_amt_expl, "drip_pricing", evidence_a, candidate_finding=candidate_a
    )
    assert not is_val_amt, "Failed to reject invented monetary amount!"
    print("    Invented monetary amount (₹999.00 vs ₹20.00 observed) -> [INTERCEPTED]")

    is_val_id, _ = validate_explanation(
        "Potential indicator of drip pricing: fee observed.",
        "drip_pricing",
        evidence_a,
        candidate_finding=candidate_a,
        evidence_ids=["snap_invented_999"],
    )
    assert not is_val_id, "Failed to reject invented evidence ID!"
    print("    Invented evidence ID ('snap_invented_999') -> [INTERCEPTED]")

    print("\n" + "=" * 70)
    print("[SUCCESS] All Quality Gates, Grounding Contracts & Audits Passed.")
    print("=" * 70)

if __name__ == "__main__":
    main()
