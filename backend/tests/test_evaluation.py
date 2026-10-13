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
