"""Run Independent Detection and Classification Evaluation on Ground Truth Bundles.

Unit of evaluation:
Run-level evidence bundle (product, cart, checkout observations).

Independent Metrics:
1. Detection: Did the pipeline identify a potential dark pattern condition at all?
   (Binary: Clean vs Dark Pattern) -> Precision, Recall, F1, False Positive Rate.
2. Classification: Given a detected condition, was the CCPA category assigned correctly?
   -> Multiclass Accuracy, Precision, Recall per category.
"""

import sys
import os
import json
from pathlib import Path
from collections import defaultdict

# Insert backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.analysis.diff_engine import DiffEngine
from app.analysis.detectors import (
    detect_drip_pricing_indicators,
    detect_basket_sneaking_indicators,
    detect_false_urgency_indicators,
)
from app.analysis.classifier import LLMClassifier


def evaluate_pipeline(use_llm: bool = False):
    diff_engine = DiffEngine(expected_disclosure_stage="product")
    classifier = LLMClassifier() if use_llm else None

    gt_path = Path(__file__).parent / "ground_truth.json"
    with open(gt_path, "r", encoding="utf-8") as f:
        bundles = json.load(f)

    total_bundles = len(bundles)
    
    # Detection counts (Clean vs Dark Pattern)
    tp_det = 0
    fp_det = 0
    fn_det = 0
    tn_det = 0

    # Classification counts (Category-level)
    cat_correct = 0
    cat_total_detected = 0

    confusion_matrix = defaultdict(lambda: defaultdict(int))
    classes = ["clean", "drip_pricing", "basket_sneaking", "false_urgency"]

    for b in bundles:
        gt_label = b["ground_truth_label"]
        bundle_id = b["bundle_id"]

        # Run pipeline
        run_bundle = {
            "id": bundle_id,
            "audit_id": "eval_audit",
            "charges": b.get("charges", []),
            "disclosures": b.get("disclosures", []),
            "stage_captures": b.get("stage_captures", []),
            "preselected_addons": b.get("preselected_addons", []),
            "urgency_indicators": b.get("urgency_indicators", []),
        }

        single_diffs = diff_engine.compute_single_run_diffs(run_bundle)

        # Detect candidate findings
        candidates = []
        candidates.extend(detect_drip_pricing_indicators(single_diffs, run_bundle))
        candidates.extend(detect_basket_sneaking_indicators(run_bundle))

        if "urgency_t0" in b and "urgency_t1" in b:
            uf = detect_false_urgency_indicators(
                b["urgency_t0"], b["urgency_t1"], b.get("elapsed_seconds", 30), "eval_audit"
            )
            if uf:
                candidates.append(uf)

        # Classify findings
        predicted_category = "clean"
        if candidates:
            # Pick highest confidence finding as bundle-level prediction
            cand = max(candidates, key=lambda c: c.get("confidence", 0.0))
            if use_llm and classifier:
                classified = classifier.classify_candidate(cand, run_bundle)
                predicted_category = classified.get("category", cand["category"])
            else:
                predicted_category = cand["category"]

        confusion_matrix[gt_label][predicted_category] += 1

        # Detection Evaluation
        is_gt_positive = (gt_label != "clean")
        is_pred_positive = (predicted_category != "clean")

        if is_gt_positive and is_pred_positive:
            tp_det += 1
        elif not is_gt_positive and is_pred_positive:
            fp_det += 1
        elif is_gt_positive and not is_pred_positive:
            fn_det += 1
        else:
            tn_det += 1

        # Classification Evaluation (evaluated when a condition is detected)
        if is_gt_positive and is_pred_positive:
            cat_total_detected += 1
            if predicted_category == gt_label:
                cat_correct += 1

    # Calculate metrics
    precision_det = tp_det / (tp_det + fp_det) if (tp_det + fp_det) > 0 else 0.0
    recall_det = tp_det / (tp_det + fn_det) if (tp_det + fn_det) > 0 else 0.0
    f1_det = 2 * (precision_det * recall_det) / (precision_det + recall_det) if (precision_det + recall_det) > 0 else 0.0
    classification_acc = cat_correct / cat_total_detected if cat_total_detected > 0 else 0.0

    print("=" * 65)
    mode_name = "Rules + LLM Classifier" if use_llm else "Rules-Only Deterministic Detectors"
    print(f"EVALUATION RESULTS: {mode_name}")
    print("=" * 65)
    print(f"Total Evaluated Run Bundles: {total_bundles}")
    print("\n1. DETECTION PERFORMANCE (Clean vs Dark Pattern Indicator):")
    print(f"   True Positives (TP):  {tp_det}")
    print(f"   False Positives (FP): {fp_det}")
    print(f"   True Negatives (TN):  {tn_det}")
    print(f"   False Negatives (FN): {fn_det}")
    print(f"   Detection Precision:  {precision_det:.3f} ({precision_det*100:.1f}%)")
    print(f"   Detection Recall:     {recall_det:.3f} ({recall_det*100:.1f}%)")
    print(f"   Detection F1-Score:   {f1_det:.3f}")

    print("\n2. CLASSIFICATION PERFORMANCE (Conditional on Detection):")
    print(f"   Correctly Classified: {cat_correct} / {cat_total_detected}")
    print(f"   Classification Accuracy: {classification_acc:.3f} ({classification_acc*100:.1f}%)")

    print("\n3. CLASS-LEVEL CONFUSION MATRIX:")
    header = f"{'Actual \\ Predicted':<20} | " + " | ".join([f"{c:<15}" for c in classes])
    print(header)
    print("-" * len(header))
    for actual in classes:
        row = f"{actual:<20} | " + " | ".join([f"{confusion_matrix[actual][pred]:<15}" for pred in classes])
        print(row)
    print("=" * 65)


if __name__ == "__main__":
    evaluate_pipeline(use_llm=False)
