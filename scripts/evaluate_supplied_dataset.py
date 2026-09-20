"""Evaluate classification and the saved submission against supplied labels.

This script is for evaluation only. Never train on the supplied ground-truth
file: doing so would leak the answers into the model and make the metrics
meaningless for new email.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sklearn.metrics import accuracy_score, confusion_matrix, f1_score


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "sdoc-hackathon-docker" / "data_v2"
DEFAULT_SUBMISSION = ROOT / "runtime" / "submission-current.json"
DEFAULT_OUTPUT = ROOT / "runtime" / "evaluation-current.json"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sdoc-hackathon-docker" / "server"))

from model.classifier import CATEGORIES, EmailClassifier  # noqa: E402
from backend.pipeline import process_email  # noqa: E402
import scoring  # noqa: E402


def evaluate_classification(dataset: Path) -> dict:
    truth = json.loads((dataset / "ground_truth.json").read_text(encoding="utf-8"))
    classifier = EmailClassifier()
    expected: list[str] = []
    model_only: list[str] = []
    full_pipeline: list[str] = []
    decision_sources: dict[str, int] = {}

    for email_path in sorted((dataset / "inbox").glob("*.json")):
        email = json.loads(email_path.read_text(encoding="utf-8"))
        email_id = email["email_id"]
        prediction = classifier.predict(email)
        expected.append(truth[email_id]["category"])
        model_only.append(
            prediction.get("model_predicted_category", prediction["predicted_category"])
        )
        full_pipeline.append(prediction["predicted_category"])
        source = prediction["decision_source"]
        decision_sources[source] = decision_sources.get(source, 0) + 1

    labels = list(CATEGORIES)

    def metrics(predicted: list[str]) -> dict:
        return {
            "accuracy": accuracy_score(expected, predicted),
            "macro_f1": f1_score(expected, predicted, labels=labels, average="macro"),
            "correct": sum(a == b for a, b in zip(expected, predicted)),
            "total": len(expected),
            "label_order": labels,
            "confusion_matrix": confusion_matrix(expected, predicted, labels=labels).tolist(),
        }

    return {
        "model_only": metrics(model_only),
        "rules_plus_model": metrics(full_pipeline),
        "decision_sources": decision_sources,
    }


def evaluate_submission(dataset: Path, submission: Path) -> dict | None:
    if not submission.exists():
        return None
    truth = json.loads((dataset / "ground_truth.json").read_text(encoding="utf-8"))
    predictions = json.loads(submission.read_text(encoding="utf-8"))
    return scoring.score_all(truth, predictions)


def run_full_pipeline(dataset: Path) -> dict:
    """Process every email directly, without using saved reports or labels."""
    classifier = EmailClassifier()
    submission = {}
    for email_path in sorted((dataset / "inbox").glob("*.json")):
        email_id = email_path.stem
        result = process_email(dataset, email_id, classifier)
        category = result.get("category")
        is_comparison = category == "BL_COMPARISON"
        if result.get("routing_status") == "DRAFT_BL_REQUEST" or not is_comparison:
            status = "OK"
        else:
            status = result.get("comparison_status")
        if category not in CATEGORIES or status not in {"OK", "MISMATCH", "NEEDS_REVIEW"}:
            raise ValueError(f"Pipeline did not produce a scorable result for {email_id}: {result}")
        submission[email_id] = {
            "category": category,
            "status": status,
            "has_defect": status == "MISMATCH",
            "defect_fields": result.get("defect_fields", []) if status == "MISMATCH" else [],
            "review_reason": result.get("review_reason") if status == "NEEDS_REVIEW" else None,
        }
    truth = json.loads((dataset / "ground_truth.json").read_text(encoding="utf-8"))
    return scoring.score_all(truth, submission)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--submission", type=Path, default=DEFAULT_SUBMISSION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--run-pipeline",
        action="store_true",
        help="Process the selected dataset from source instead of reading a saved submission.",
    )
    args = parser.parse_args()

    report = {
        "warning": (
            "Evaluation labels are a test key. Do not use them for fitting or rule tuning. "
            "Keep a separate frozen holdout for honest future performance estimates."
        ),
        "classification": evaluate_classification(args.dataset),
        "organizer_score": (
            run_full_pipeline(args.dataset)
            if args.run_pipeline
            else evaluate_submission(args.dataset, args.submission)
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    model = report["classification"]["model_only"]
    pipeline = report["classification"]["rules_plus_model"]
    print(f"Model only: {model['correct']}/{model['total']} accuracy={model['accuracy']:.4f}, macro-F1={model['macro_f1']:.4f}")
    print(f"Rules + model: {pipeline['correct']}/{pipeline['total']} accuracy={pipeline['accuracy']:.4f}, macro-F1={pipeline['macro_f1']:.4f}")
    if report["organizer_score"]:
        score = report["organizer_score"]
        print(f"Organizer full-pipeline score: {score['final_score']:.4f}")
        print(f"End-to-end: {score['end_to_end']['success']}/{score['end_to_end']['total']}")
    print(f"Saved report: {args.output}")


if __name__ == "__main__":
    main()
