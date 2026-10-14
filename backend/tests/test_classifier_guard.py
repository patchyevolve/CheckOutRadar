"""Regression tests for LLM Classifier Output Validation & Non-Judicial Wording Guard."""

import pytest
from app.analysis.classifier import (
    validate_explanation,
    build_safe_grounded_template,
    PROHIBITED_ADJUDICATIVE_PATTERNS,
    ClassifiedFinding,
    LLMClassifier,
)


def test_validator_rejects_semantic_adjudicative_variations():
    """Verify semantic variations of adjudicative assertions are caught and rejected."""
    prohibited_examples = [
        "The merchant is guilty of fraud.",
        "The company committed an illegal deceptive act.",
        "The merchant violated consumer law.",
        "This conduct is unlawful.",
        "The merchant has been found culpable.",
        "This is a criminal offense by the merchant.",
        "The seller was found liable for statutory penalties.",
    ]
    for text in prohibited_examples:
        is_valid, reason = validate_explanation(
            explanation=text,
            category="drip_pricing",
            evidence_context={},
        )
        assert not is_valid, f"Expected validator to reject: '{text}'"
        assert (
            "prohibited adjudicative language" in reason.lower()
            or "prohibited legal term" in reason.lower()
            or "missing mandatory" in reason.lower()
        )


def test_validator_accepts_valid_disclaimers_without_false_positives():
    """Verify negative disclaimers do NOT cause false positives."""
    valid_explanations_with_disclaimers = [
        (
            "Observed potential indicator of Drip Pricing (CCPA_2023_ANNEX_1_8): "
            "mandatory convenience fee of ₹20.00 was observed at checkout while unobserved at product stage. "
            "This empirical indicator serves as technical checkout audit evidence and does not constitute a legal determination or statutory adjudication."
        ),
        (
            "Potential indicator of drip pricing: convenience fee of ₹20.00 observed at checkout. "
            "This finding is an automated empirical indicator and does not declare that the merchant violated consumer law or is guilty of fraud."
        ),
        (
            "Potential dark pattern indicator: pre-selected addon observed in cart payable total. "
            "This report is a technical audit and cannot be construed as a legal verdict or finding of liability."
        ),
    ]
    evidence = {
        "charges": [{"label": "Convenience Fee", "amount_minor": 2000, "step": "checkout"}],
        "disclosures": [{"charge_label": "Convenience Fee", "step": "product", "state": "unknown"}],
    }
    candidate = {"category": "drip_pricing", "amount_minor": 2000, "explanation": "fee of ₹20.00"}

    for expl in valid_explanations_with_disclaimers:
        is_valid, reason = validate_explanation(
            explanation=expl,
            category="drip_pricing",
            evidence_context=evidence,
            candidate_finding=candidate,
        )
        assert is_valid, f"Expected valid disclaimer not to be rejected. Got failure: {reason}"


def test_validator_rejects_missing_potential_indicator_framing():
    """Must explicitly frame findings as potential indicators."""
    expl = "A mandatory fee of ₹20.00 was charged at checkout without earlier display."
    is_valid, reason = validate_explanation(
        explanation=expl,
        category="drip_pricing",
        evidence_context={"charges": [{"amount_minor": 2000}]},
    )
    assert not is_valid
    assert "missing mandatory non-judicial framing" in reason.lower()


def test_validator_rejects_ungrounded_absence_assertions():
    """Fee cannot be claimed as absent if disclosures are unobserved/unknown."""
    expl = "Potential indicator of drip pricing: convenience fee was absent at product stage."
    is_valid, reason = validate_explanation(
        explanation=expl,
        category="drip_pricing",
        evidence_context={"disclosures": []},
    )
    assert not is_valid
    assert "cannot be claimed as absent" in reason.lower() or "not_observed_verified" in reason.lower()


def test_validator_accepts_verified_absence():
    """Fee absence claim is accepted when supported by verified negative observation."""
    expl = "Potential indicator of drip pricing: convenience fee was absent at product stage."
    is_valid, reason = validate_explanation(
        explanation=expl,
        category="drip_pricing",
        evidence_context={
            "disclosures": [{"charge_label": "Convenience Fee", "state": "not_observed_verified"}]
        },
    )
    assert is_valid
    assert reason is None


def test_validator_accepts_compliant_unknown_disclosure_framing():
    """Unknown disclosure status is correctly accepted when framed with uncertainty."""
    expl = (
        "Potential indicator of drip pricing: fee observed at checkout, while earlier disclosure status "
        "was unobserved or unknown in this capture."
    )
    is_valid, reason = validate_explanation(
        explanation=expl,
        category="drip_pricing",
        evidence_context={"disclosures": [{"state": "unknown"}]},
    )
    assert is_valid
    assert reason is None


def test_validator_rejects_invented_monetary_amount():
    """Amounts in explanation must be traceable to candidate or evidence."""
    expl = "Potential indicator of drip pricing: mandatory fee of ₹999.00 observed at checkout."
    candidate = {"category": "drip_pricing", "amount_minor": 2000, "explanation": "fee of ₹20.00"}
    evidence = {"charges": [{"amount_minor": 2000}]}

    is_valid, reason = validate_explanation(
        explanation=expl,
        category="drip_pricing",
        evidence_context=evidence,
        candidate_finding=candidate,
    )
    assert not is_valid
    assert "ungrounded monetary amount" in reason.lower()


def test_validator_rejects_invented_evidence_id():
    """Evidence IDs in finding must be traceable to audit observations."""
    expl = "Potential indicator of drip pricing: convenience fee observed."
    candidate = {"category": "drip_pricing", "evidence_ids": ["snap_real_01"]}
    evidence = {"stage_captures": [{"snapshot_id": "snap_real_01"}]}

    is_valid, reason = validate_explanation(
        explanation=expl,
        category="drip_pricing",
        evidence_context=evidence,
        candidate_finding=candidate,
        evidence_ids=["snap_invented_999"],
    )
    assert not is_valid
    assert "ungrounded evidence id" in reason.lower()


def test_bounded_retry_triggers_on_first_pass_failure(monkeypatch):
    """
    Test bounded retry policy:
    Attempt 0 returns prohibited wording;
    Attempt 1 (retry) returns valid non-judicial wording.
    Verify retry was attempted and succeeded with source='llm'.
    """
    classifier = LLMClassifier(api_key="mock_key")
    call_count = 0

    def fake_execute(messages):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First attempt: prohibited wording
            return (
                '{"category": "drip_pricing", "severity": "high", "confidence": 0.95, '
                '"explanation": "The merchant is guilty of fraud under consumer law.", '
                '"evidence_ids": ["snap_1"]}'
            )
        else:
            # Second attempt (corrective retry): valid wording
            return (
                '{"category": "drip_pricing", "severity": "medium", "confidence": 0.90, '
                '"explanation": "Potential indicator of drip pricing: mandatory convenience fee observed at checkout.", '
                '"evidence_ids": ["snap_1"]}'
            )

    monkeypatch.setattr(classifier, "_execute_llm_request", fake_execute)

    candidate = {"category": "drip_pricing", "severity": "medium", "confidence": 0.90, "evidence_ids": ["snap_1"]}
    evidence = {"stage_captures": [{"snapshot_id": "snap_1"}], "disclosures": []}

    res = classifier.classify_candidate(candidate, evidence)

    assert call_count == 2
    assert res["source"] == "llm"
    telemetry = res["telemetry"]
    assert telemetry["first_pass_overall_valid"] is False
    assert telemetry["retry_attempted"] is True
    assert telemetry["retry_succeeded"] is True
    assert telemetry["fallback_used"] is False
    assert "potential indicator" in res["explanation"].lower()


def test_fallback_on_exhausted_retries(monkeypatch):
    """
    Simulate an LLM response containing prohibited adjudicative terms on both attempts.
    The classifier must intercept this, execute bounded retry, exhaust retries,
    and fall back to the safe, grounded template, never exposing an invalid explanation.
    """
    classifier = LLMClassifier(api_key="mock_key")
    call_count = 0

    def fake_execute(messages):
        nonlocal call_count
        call_count += 1
        return (
            '{"category": "drip_pricing", "severity": "high", "confidence": 0.95, '
            '"explanation": "The merchant committed an illegal deceptive act and is culpable.", '
            '"evidence_ids": ["snap_1"]}'
        )

    monkeypatch.setattr(classifier, "_execute_llm_request", fake_execute)

    candidate = {"category": "drip_pricing", "severity": "high", "confidence": 0.95, "evidence_ids": ["snap_1"]}
    evidence = {"stage_captures": [{"snapshot_id": "snap_1"}], "disclosures": []}

    res = classifier.classify_candidate(candidate, evidence)

    assert call_count == 2  # exactly 1 initial + 1 retry
    assert res["source"] == "llm_guarded_fallback"
    telemetry = res["telemetry"]
    assert telemetry["retry_attempted"] is True
    assert telemetry["retry_succeeded"] is False
    assert telemetry["fallback_used"] is True
    assert telemetry["fallback_validated"] is True
    assert "potential indicator" in res["explanation"].lower()
    for pp in PROHIBITED_ADJUDICATIVE_PATTERNS:
        assert not pp.search(res["explanation"])


def test_fallback_output_validation():
    """Verify that build_safe_grounded_template output deterministically passes validation."""
    categories = ["drip_pricing", "basket_sneaking", "false_urgency"]
    ccpa_defs = {
        "drip_pricing": {"official_id": "CCPA_2023_ANNEX_1_8", "name": "Drip Pricing", "definition": "Elements of prices not revealed upfront."},
        "basket_sneaking": {"official_id": "CCPA_2023_ANNEX_1_2", "name": "Basket Sneaking", "definition": "Inclusion of additional items without consent."},
        "false_urgency": {"official_id": "CCPA_2023_ANNEX_1_1", "name": "False Urgency", "definition": "Falsely stating urgency or countdown."},
    }

    for cat in categories:
        cand = {"category": cat, "severity": "medium", "confidence": 0.85, "explanation": f"Observed {cat}"}
        
        # Test under unknown disclosures
        template_unknown = build_safe_grounded_template(cand, {"disclosures": []}, ccpa_defs[cat])
        is_val, reason = validate_explanation(template_unknown, cat, {"disclosures": []}, cand)
        assert is_val, f"Fallback failed for {cat} under unknown disclosures: {reason}"
        assert "potential indicator" in template_unknown.lower()

        # Test under verified absence
        template_absent = build_safe_grounded_template(
            cand, {"disclosures": [{"state": "not_observed_verified"}]}, ccpa_defs[cat]
        )
        is_val, reason = validate_explanation(
            template_absent, cat, {"disclosures": [{"state": "not_observed_verified"}]}, cand
        )
        assert is_val, f"Fallback failed for {cat} under verified absence: {reason}"
        assert "potential indicator" in template_absent.lower()
