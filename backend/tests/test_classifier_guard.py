"""Regression tests for LLM Classifier Output Validation & Non-Judicial Wording Guard."""

import pytest
from app.analysis.classifier import (
    validate_explanation,
    build_safe_grounded_template,
    PROHIBITED_LEGAL_TERMS,
    ClassifiedFinding,
    LLMClassifier,
)


def test_validator_rejects_prohibited_legal_terms():
    for term in ["guilty", "convicted", "verdict", "criminal", "illegal", "violates the law", "unlawful"]:
        expl = f"The merchant is {term} under CCPA guidelines."
        is_valid, reason = validate_explanation(
            explanation=expl,
            category="drip_pricing",
            evidence_context={},
        )
        assert not is_valid, f"Expected validator to reject term '{term}'"
        assert "prohibited adjudicative term" in reason.lower()


def test_validator_rejects_missing_potential_indicator_framing():
    expl = "A mandatory fee was charged at checkout without earlier display."
    is_valid, reason = validate_explanation(
        explanation=expl,
        category="drip_pricing",
        evidence_context={},
    )
    assert not is_valid
    assert "missing mandatory non-judicial framing" in reason.lower()


def test_validator_rejects_ungrounded_absence_assertions():
    expl = "Potential indicator of drip pricing: convenience fee was absent at product stage."
    is_valid, reason = validate_explanation(
        explanation=expl,
        category="drip_pricing",
        evidence_context={"disclosures": []},
    )
    assert not is_valid
    assert "cannot be claimed as absent" in reason.lower() or "not_observed_verified" in reason.lower()


def test_validator_accepts_verified_absence():
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
    expl = (
        "Potential indicator of drip pricing: fee observed at checkout, while disclosure status "
        "at earlier stages was unobserved or unknown in this capture."
    )
    is_valid, reason = validate_explanation(
        explanation=expl,
        category="drip_pricing",
        evidence_context={"disclosures": [{"state": "unknown"}]},
    )
    assert is_valid
    assert reason is None


def test_safe_grounded_template_generation():
    ccpa_def = {
        "official_id": "CCPA_2023_ANNEX_1_8",
        "name": "Drip Pricing",
        "definition": "Drip pricing means a practice whereby elements of prices are not revealed upfront.",
    }
    candidate = {"category": "drip_pricing", "severity": "medium", "confidence": 0.85}

    # 1. With unobserved disclosures
    template_unknown = build_safe_grounded_template(candidate, {"disclosures": []}, ccpa_def)
    assert "potential indicator" in template_unknown.lower()
    assert "unknown" in template_unknown.lower() or "unobserved" in template_unknown.lower()
    assert not any(t in template_unknown.lower() for t in PROHIBITED_LEGAL_TERMS)

    # 2. With verified absence
    template_absent = build_safe_grounded_template(
        candidate,
        {"disclosures": [{"state": "not_observed_verified"}]},
        ccpa_def,
    )
    assert "potential indicator" in template_absent.lower()
    assert "verified absent" in template_absent.lower()
    assert not any(t in template_absent.lower() for t in PROHIBITED_LEGAL_TERMS)


def test_classifier_guarded_fallback_on_invalid_response(monkeypatch):
    """
    Simulate an LLM response containing prohibited adjudicative terms.
    The classifier must intercept this and fall back to the safe, grounded template,
    never exposing an invalid explanation to the caller.
    """
    classifier = LLMClassifier(api_key="mock_key")

    def fake_execute(messages):
        return (
            '{"category": "drip_pricing", "severity": "high", "confidence": 0.95, '
            '"explanation": "The merchant is guilty of illegal drip pricing and violated CCPA laws.", '
            '"evidence_ids": ["snap_1"]}'
        )

    monkeypatch.setattr(classifier, "_execute_llm_request", fake_execute)

    candidate = {"category": "drip_pricing", "severity": "high", "confidence": 0.95}
    res = classifier.classify_candidate(candidate, {"disclosures": []})

    assert res["category"] == "drip_pricing"
    assert "potential indicator" in res["explanation"].lower()
    assert not any(t in res["explanation"].lower() for t in PROHIBITED_LEGAL_TERMS)
    assert res["source"] == "llm_guarded_fallback"
