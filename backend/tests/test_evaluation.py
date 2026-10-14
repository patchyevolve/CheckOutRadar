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
