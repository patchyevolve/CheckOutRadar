"""Unit tests for Evaluation Pipeline."""

import pytest
from pathlib import Path
import json
import sys
from app.analysis.diff_engine import DiffEngine
from app.analysis.detectors import (
    detect_drip_pricing_indicators,
    detect_basket_sneaking_indicators,
    detect_false_urgency_indicators,
)


def get_ground_truth_path() -> Path:
    candidates = [
        Path(__file__).parent.parent.parent / "evaluation" / "ground_truth.json",
        Path("/evaluation/ground_truth.json"),
        Path("/app/evaluation/ground_truth.json"),
        Path("/home/daksh/working/checkout-radar/evaluation/ground_truth.json"),
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def test_ground_truth_bundle_count():
    gt_path = get_ground_truth_path()
    assert gt_path.exists()
    with open(gt_path, "r", encoding="utf-8") as f:
        bundles = json.load(f)
    assert len(bundles) == 45, f"Expected 45 bundles, got {len(bundles)}"


def test_evaluation_detection_and_classification():
    gt_path = get_ground_truth_path()
    with open(gt_path, "r", encoding="utf-8") as f:
        bundles = json.load(f)


    diff_engine = DiffEngine()
    correct_detections = 0
    correct_classifications = 0
    dark_patterns_count = 0

    for b in bundles:
        gt_label = b["ground_truth_label"]
        bundle = {
            "id": b["bundle_id"],
            "audit_id": "test_audit",
            "charges": b.get("charges", []),
            "disclosures": b.get("disclosures", []),
            "stage_captures": b.get("stage_captures", []),
            "preselected_addons": b.get("preselected_addons", []),
            "urgency_indicators": b.get("urgency_indicators", []),
        }

        diffs = diff_engine.compute_single_run_diffs(bundle)
        cands = []
        cands.extend(detect_drip_pricing_indicators(diffs, bundle))
        cands.extend(detect_basket_sneaking_indicators(bundle))

        if "urgency_t0" in b and "urgency_t1" in b:
            u = detect_false_urgency_indicators(b["urgency_t0"], b["urgency_t1"], 30, "test_audit")
            if u:
                cands.append(u)

        detected_label = cands[0]["category"] if cands else "clean"

        if gt_label != "clean":
            dark_patterns_count += 1
            if detected_label != "clean":
                correct_detections += 1
            if detected_label == gt_label:
                correct_classifications += 1
        else:
            if detected_label == "clean":
                correct_detections += 1

    # Verify high detection and classification rates
    assert correct_detections == 45
    assert correct_classifications == dark_patterns_count


def test_latency_aggregation_includes_validator_rejected_retries():
    """
    Regression test: Verifies that latency aggregation includes all received HTTP responses,
    specifically ensuring that retry responses rejected by the application-level validator
    are NOT excluded from the network-latency sample.
    """
    from app.analysis.classifier import aggregate_provider_latencies

    # Explicit set of known observations:
    # - 5 initial submissions with HTTP responses
    # - 1 retry that succeeded validation
    # - 2 retries that were rejected by application-level validation
    # - 1 submission that failed at provider layer (HTTP 429 rate limit; 0 HTTP responses)
    # - 1 retry that failed at provider layer (network failure; 0 retry HTTP responses)
    known_telemetry = [
        {"initial_response_received": True, "provider_http_latency_ms": 1000.0},
        {"initial_response_received": True, "provider_http_latency_ms": 1100.0},
        {
            "initial_response_received": True,
            "provider_http_latency_ms": 1200.0,
            "retry_attempted": True,
            "retry_response_received": True,
            "retry_validation_accepted": True,
            "retry_succeeded": True,
            "retry_http_latency_ms": 1300.0,
        },
        {
            "initial_response_received": True,
            "provider_http_latency_ms": 1400.0,
            "retry_attempted": True,
            "retry_response_received": True,
            "retry_validation_accepted": False,  # REJECTED by validator
            "retry_succeeded": False,
            "retry_http_latency_ms": 1500.0,
        },
        {
            "initial_response_received": True,
            "provider_http_latency_ms": 1800.0,
            "retry_attempted": True,
            "retry_response_received": True,
            "retry_validation_accepted": False,  # REJECTED by validator
            "retry_succeeded": False,
            "retry_http_latency_ms": 1600.0,
        },
        {
            "initial_response_received": False,  # Provider rate limit
            "provider_error": "429 Too Many Requests",
            "provider_http_latency_ms": None,
        },
        {
            "initial_response_received": False,  # Provider network failure
            "provider_error": "Connection Reset",
            "provider_http_latency_ms": None,
            "retry_attempted": True,
            "retry_response_received": False,
            "retry_provider_error": "Connection Reset",
            "retry_http_latency_ms": None,
        },
    ]

    summary = aggregate_provider_latencies(known_telemetry)

    # 5 initial + 3 retries (1 accepted + 2 rejected by validator) = 8 successful HTTP responses
    assert summary["sample_size"] == 8
    assert summary["initial_responses"] == 5
    assert summary["retry_responses"] == 3

    # All 8 values must be collected into raw_samples
    assert sorted(summary["raw_samples"]) == [1000.0, 1100.0, 1200.0, 1300.0, 1400.0, 1500.0, 1600.0, 1800.0]

    # Verify that the two rejected retries (1500.0 and 1600.0) are present in the sample
    assert 1500.0 in summary["raw_samples"]
    assert 1600.0 in summary["raw_samples"]

    # Recomputed statistics over all 8 values:
    # Sum = 10,900.0 / 8 = 1362.5
    # Sorted = [1000.0, 1100.0, 1200.0, 1300.0, 1400.0, 1500.0, 1600.0, 1800.0]
    # Median = (1300.0 + 1400.0) / 2 = 1350.0
    # p95 index: int(0.95 * 8) = 7 -> sorted[7] = 1800.0
    assert summary["mean_ms"] == 1362.5
    assert summary["median_ms"] == 1350.0
    assert summary["p95_ms"] == 1800.0


def test_attempt_records_instrumentation_in_classifier():
    """
    Verifies that LLMClassifier.classify_candidate instruments attempt-level records
    with all required empirical audit fields: candidate_id, attempt, attempt_type,
    http_outcome, response_received, latency_ms, validator_outcome, and fallback_reason.
    """
    from app.analysis.classifier import LLMClassifier

    classifier = LLMClassifier()
    candidate = {
        "id": "cand_eval_101",
        "category": "drip_pricing",
        "severity": "high",
        "confidence": 0.9,
        "explanation": "Potential drip pricing indicator: mandatory fee added at checkout.",
        "evidence_ids": ["snap_1"],
    }
    evidence = {
        "disclosures": [{"stage": "product", "text": "All taxes included"}],
        "charges": [{"stage": "checkout_summary", "amount_minor": 500, "label": "Handling Fee"}],
    }

    result = classifier.classify_candidate(candidate, evidence)
    assert "telemetry" in result
    telem = result["telemetry"]
    assert "attempt_records" in telem
    records = telem["attempt_records"]
    assert len(records) >= 1

    first_record = records[0]
    required_keys = [
        "candidate_id",
        "category",
        "attempt",
        "attempt_type",
        "http_status",
        "http_response_received",
        "model_output_received",
        "latency_ms",
        "transport_error",
        "http_outcome",
        "response_received",
        "validator_outcome",
        "fallback_reason",
    ]
    for k in required_keys:
        assert k in first_record, f"Missing required telemetry key '{k}' in attempt record"

    assert first_record["candidate_id"] == "cand_eval_101"
    assert first_record["category"] == "drip_pricing"
    assert first_record["attempt"] == 0
    assert first_record["attempt_type"] == "initial"


def test_dual_latency_and_http_status_accounting():
    """
    Verifies that calculate_metrics_from_records explicitly separates HTTP transport round-trips
    (including HTTP 429/403 with measured latencies) from usable model completions (HTTP 200),
    and correctly reports both successful_model_latency and all_http_latency.
    """
    from app.analysis.classifier import calculate_metrics_from_records

    # Fixture: 4 candidates
    # c1: HTTP 200 OK with usable model completion (1200.0 ms)
    # c2: HTTP 429 Rate Limit (measured round-trip 300.0 ms)
    # c3: HTTP 403 Forbidden (measured round-trip 200.0 ms)
    # c4: Transport failure (pre-HTTP failure, e.g. ConnectionResetError, None latency)
    attempt_records = [
        {
            "candidate_id": "c1",
            "category": "drip_pricing",
            "attempt": 0,
            "attempt_type": "initial",
            "http_status": 200,
            "http_response_received": True,
            "model_output_received": True,
            "response_received": True,
            "latency_ms": 1200.0,
            "transport_error": None,
            "http_outcome": "200_ok",
            "validator_outcome": "accepted",
            "fallback_reason": None,
            "schema_valid": True,
            "wording_valid": True,
            "category_concordance": True,
            "concept_keyword_coverage": True,
        },
        {
            "candidate_id": "c2",
            "category": "drip_pricing",
            "attempt": 0,
            "attempt_type": "initial",
            "http_status": 429,
            "http_response_received": True,
            "model_output_received": False,
            "response_received": False,
            "latency_ms": 300.0,
            "transport_error": None,
            "http_outcome": "429_rate_limit",
            "validator_outcome": "not_applicable",
            "fallback_reason": "provider_error",
            "schema_valid": None,
            "wording_valid": None,
            "category_concordance": None,
            "concept_keyword_coverage": None,
        },
        {
            "candidate_id": "c3",
            "category": "basket_sneaking",
            "attempt": 0,
            "attempt_type": "initial",
            "http_status": 403,
            "http_response_received": True,
            "model_output_received": False,
            "response_received": False,
            "latency_ms": 200.0,
            "transport_error": None,
            "http_outcome": "403_forbidden",
            "validator_outcome": "not_applicable",
            "fallback_reason": "provider_error",
            "schema_valid": None,
            "wording_valid": None,
            "category_concordance": None,
            "concept_keyword_coverage": None,
        },
        {
            "candidate_id": "c4",
            "category": "false_urgency",
            "attempt": 0,
            "attempt_type": "initial",
            "http_status": None,
            "http_response_received": False,
            "model_output_received": False,
            "response_received": False,
            "latency_ms": None,
            "transport_error": "ConnectionResetError: Remote end closed connection without response",
            "http_outcome": "error_ConnectionResetError",
            "validator_outcome": "not_applicable",
            "fallback_reason": "provider_error",
            "schema_valid": None,
            "wording_valid": None,
            "category_concordance": None,
            "concept_keyword_coverage": None,
        },
    ]

    candidate_telemetry = [
        {"candidate_id": "c1", "fallback_used": False, "evidence_grounding_valid": True, "post_guard_category_preserved": True, "post_guard_concept_keyword_coverage": True},
        {"candidate_id": "c2", "fallback_used": True, "evidence_grounding_valid": True, "post_guard_category_preserved": True, "post_guard_concept_keyword_coverage": True},
        {"candidate_id": "c3", "fallback_used": True, "evidence_grounding_valid": True, "post_guard_category_preserved": True, "post_guard_concept_keyword_coverage": True},
        {"candidate_id": "c4", "fallback_used": True, "evidence_grounding_valid": True, "post_guard_category_preserved": True, "post_guard_concept_keyword_coverage": True},
    ]

    metrics = calculate_metrics_from_records(attempt_records, candidate_telemetry)

    # 1. HTTP Accounting
    http_acc = metrics["http_accounting"]
    assert http_acc["total_requests"] == 4
    assert http_acc["http_responses_received"] == 3  # c1 (200), c2 (429), c3 (403)
    assert http_acc["transport_errors"] == 1          # c4 (no HTTP response received)
    assert http_acc["http_response_rate_pct"] == 75.0

    # 2. Model Accounting
    model_acc = metrics["model_accounting"]
    assert model_acc["candidates_submitted"] == 4
    assert model_acc["initial_model_responses"] == 1  # only c1 received usable completion
    assert model_acc["initial_model_failures"] == 3   # c2, c3, c4 routed to fallback
    assert model_acc["initial_model_coverage_pct"] == 25.0
    assert model_acc["total_model_responses"] == 1
    assert model_acc["successful_model_rate_pct"] == 25.0

    # 3. Dual Latencies
    model_lat = metrics["successful_model_latency"]
    assert model_lat["sample_size"] == 1
    assert model_lat["mean_ms"] == 1200.0
    assert model_lat["median_ms"] == 1200.0
    assert model_lat["p95_ms"] == 1200.0
    assert model_lat["raw_samples"] == [1200.0]

    all_lat = metrics["all_http_latency"]
    assert all_lat["sample_size"] == 3
    assert round(all_lat["mean_ms"], 1) == 566.7
    assert all_lat["median_ms"] == 300.0
    assert all_lat["p95_ms"] == 1200.0
    assert sorted(all_lat["raw_samples"]) == [200.0, 300.0, 1200.0]

    # 4. Pipeline Outputs
    assert metrics["pipeline_quality"]["deterministic_fallbacks"] == 3
    assert metrics["pipeline_quality"]["final_accepted_outputs"] == 4


def test_calculate_metrics_from_records_provenance():
    """
    Verifies that calculate_metrics_from_records strictly derives all evaluation metrics
    (coverage, retry breakdown, provider response rate, and latencies) from a discrete
    persisted attempt-level record set without reconstruction or fabrication.
    """
    from app.analysis.classifier import calculate_metrics_from_records

    # Explicit 10-candidate test set:
    # Candidates 1-7: First-attempt success (latencies 1000, 1100, 1200, 1300, 1400, 1500, 1600 ms)
    # Candidate 8: First-attempt 429 rate limit -> fallback
    # Candidate 9: First-attempt 429 rate limit -> fallback
    # Candidate 10: First-attempt validation failure (latency 1700 ms) -> Retry attempted (latency 1800 ms) -> Retry rejected by validator -> fallback
    attempt_records = [
        # 1-7: initial success
        {"candidate_id": "c1", "category": "drip_pricing", "attempt": 0, "response_received": True, "latency_ms": 1000.0, "validator_outcome": "accepted", "fallback_reason": None, "schema_valid": True, "wording_valid": True, "category_concordance": True, "concept_keyword_coverage": True},
        {"candidate_id": "c2", "category": "drip_pricing", "attempt": 0, "response_received": True, "latency_ms": 1100.0, "validator_outcome": "accepted", "fallback_reason": None, "schema_valid": True, "wording_valid": True, "category_concordance": True, "concept_keyword_coverage": True},
        {"candidate_id": "c3", "category": "basket_sneaking", "attempt": 0, "response_received": True, "latency_ms": 1200.0, "validator_outcome": "accepted", "fallback_reason": None, "schema_valid": True, "wording_valid": True, "category_concordance": True, "concept_keyword_coverage": True},
        {"candidate_id": "c4", "category": "basket_sneaking", "attempt": 0, "response_received": True, "latency_ms": 1300.0, "validator_outcome": "accepted", "fallback_reason": None, "schema_valid": True, "wording_valid": True, "category_concordance": True, "concept_keyword_coverage": True},
        {"candidate_id": "c5", "category": "false_urgency", "attempt": 0, "response_received": True, "latency_ms": 1400.0, "validator_outcome": "accepted", "fallback_reason": None, "schema_valid": True, "wording_valid": True, "category_concordance": True, "concept_keyword_coverage": True},
        {"candidate_id": "c6", "category": "false_urgency", "attempt": 0, "response_received": True, "latency_ms": 1500.0, "validator_outcome": "accepted", "fallback_reason": None, "schema_valid": True, "wording_valid": True, "category_concordance": True, "concept_keyword_coverage": True},
        {"candidate_id": "c7", "category": "drip_pricing", "attempt": 0, "response_received": True, "latency_ms": 1600.0, "validator_outcome": "accepted", "fallback_reason": None, "schema_valid": True, "wording_valid": True, "category_concordance": True, "concept_keyword_coverage": True},
        # 8-9: initial rate limits
        {"candidate_id": "c8", "category": "drip_pricing", "attempt": 0, "response_received": False, "latency_ms": None, "validator_outcome": "not_applicable", "fallback_reason": "provider_error"},
        {"candidate_id": "c9", "category": "drip_pricing", "attempt": 0, "response_received": False, "latency_ms": None, "validator_outcome": "not_applicable", "fallback_reason": "provider_error"},
        # 10: initial validation failure + retry rejected
        {"candidate_id": "c10", "category": "drip_pricing", "attempt": 0, "response_received": True, "latency_ms": 1700.0, "validator_outcome": "rejected_wording", "fallback_reason": None, "schema_valid": True, "wording_valid": False, "category_concordance": True, "concept_keyword_coverage": True},
        {"candidate_id": "c10", "category": "drip_pricing", "attempt": 1, "response_received": True, "latency_ms": 1800.0, "validator_outcome": "rejected_wording", "fallback_reason": "model_validation_exhausted"},
    ]

    candidate_telemetry = [
        {"candidate_id": "c1", "fallback_used": False, "evidence_grounding_valid": True, "post_guard_category_preserved": True, "post_guard_concept_keyword_coverage": True},
        {"candidate_id": "c2", "fallback_used": False, "evidence_grounding_valid": True, "post_guard_category_preserved": True, "post_guard_concept_keyword_coverage": True},
        {"candidate_id": "c3", "fallback_used": False, "evidence_grounding_valid": True, "post_guard_category_preserved": True, "post_guard_concept_keyword_coverage": True},
        {"candidate_id": "c4", "fallback_used": False, "evidence_grounding_valid": True, "post_guard_category_preserved": True, "post_guard_concept_keyword_coverage": True},
        {"candidate_id": "c5", "fallback_used": False, "evidence_grounding_valid": True, "post_guard_category_preserved": True, "post_guard_concept_keyword_coverage": True},
        {"candidate_id": "c6", "fallback_used": False, "evidence_grounding_valid": True, "post_guard_category_preserved": True, "post_guard_concept_keyword_coverage": True},
        {"candidate_id": "c7", "fallback_used": False, "evidence_grounding_valid": True, "post_guard_category_preserved": True, "post_guard_concept_keyword_coverage": True},
        {"candidate_id": "c8", "fallback_used": True, "evidence_grounding_valid": True, "post_guard_category_preserved": True, "post_guard_concept_keyword_coverage": True},
        {"candidate_id": "c9", "fallback_used": True, "evidence_grounding_valid": True, "post_guard_category_preserved": True, "post_guard_concept_keyword_coverage": True},
        {"candidate_id": "c10", "fallback_used": True, "evidence_grounding_valid": True, "post_guard_category_preserved": True, "post_guard_concept_keyword_coverage": True},
    ]

    metrics = calculate_metrics_from_records(attempt_records, candidate_telemetry)

    # 1. Coverage & Requests
    assert metrics["candidates_submitted"] == 10
    assert metrics["initial_responses_received"] == 8  # 7 valid + 1 rejected
    assert metrics["initial_provider_failures"] == 2   # c8, c9
    assert metrics["initial_provider_coverage_pct"] == 80.0
    assert metrics["total_http_requests"] == 11
    assert metrics["successful_http_responses"] == 9   # 8 initial + 1 retry
    assert round(metrics["successful_provider_rate_pct"], 1) == 81.8

    # 2. Retries
    assert metrics["retries_attempted"] == 1
    assert metrics["retry_responses_received"] == 1
    assert metrics["retry_validation_acceptances"] == 0
    assert metrics["retry_validation_rejections"] == 1

    # 3. Provider Latency (9 successful responses: 1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800)
    lat_q = metrics["provider_latency"]
    assert lat_q["sample_size"] == 9
    assert lat_q["initial_responses"] == 8
    assert lat_q["retry_responses"] == 1
    # Sum = 12600.0 / 9 = 1400.0
    assert lat_q["mean_ms"] == 1400.0
    assert lat_q["median_ms"] == 1400.0
    # p95 index = int(0.95 * 9) = 8 -> 1800.0
    assert lat_q["p95_ms"] == 1800.0

    # 4. Pipeline Outputs
    assert metrics["pipeline_quality"]["deterministic_fallbacks"] == 3
    assert metrics["pipeline_quality"]["final_accepted_outputs"] == 10


def test_telemetry_json_serialization_and_deserialization(tmp_path):
    """
    Verifies that attempt records and candidate telemetry serialize cleanly to disk JSON
    and that calculate_metrics_from_records can load and calculate metrics from the saved file.
    """
    from app.analysis.classifier import calculate_metrics_from_records

    sample_data = {
        "timestamp": "2026-10-14T22:00:00Z",
        "git_commit": "cb56b0b",
        "execution_mode": "Live Remote Provider (test-model)",
        "model": "test-model",
        "candidate_pacing_seconds": 2.0,
        "total_candidates": 2,
        "attempt_records": [
            {
                "candidate_id": "c1",
                "category": "drip_pricing",
                "attempt": 0,
                "attempt_type": "initial",
                "http_outcome": "200_ok",
                "response_received": True,
                "latency_ms": 1250.0,
                "validator_outcome": "accepted",
                "fallback_reason": None,
                "schema_valid": True,
                "wording_valid": True,
                "category_concordance": True,
                "concept_keyword_coverage": True,
            },
            {
                "candidate_id": "c2",
                "category": "basket_sneaking",
                "attempt": 0,
                "attempt_type": "initial",
                "http_outcome": "429_rate_limit",
                "response_received": False,
                "latency_ms": None,
                "validator_outcome": "not_applicable",
                "fallback_reason": "provider_error",
                "schema_valid": None,
                "wording_valid": None,
                "category_concordance": None,
                "concept_keyword_coverage": None,
            },
        ],
        "candidate_telemetry": [
            {"candidate_id": "c1", "fallback_used": False, "evidence_grounding_valid": True, "post_guard_category_preserved": True, "post_guard_concept_keyword_coverage": True},
            {"candidate_id": "c2", "fallback_used": True, "evidence_grounding_valid": True, "post_guard_category_preserved": True, "post_guard_concept_keyword_coverage": True},
        ],
    }

    test_file = tmp_path / "telemetry_test.json"
    with open(test_file, "w", encoding="utf-8") as f:
        json.dump(sample_data, f, indent=2)

    with open(test_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)

    metrics = calculate_metrics_from_records(loaded["attempt_records"], loaded["candidate_telemetry"])
    assert metrics["candidates_submitted"] == 2
    assert metrics["initial_responses_received"] == 1
    assert metrics["initial_provider_failures"] == 1
    assert metrics["pipeline_quality"]["final_accepted_outputs"] == 2
    assert metrics["provider_latency"]["sample_size"] == 1
    assert metrics["provider_latency"]["mean_ms"] == 1250.0
