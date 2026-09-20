"""Reproducible baseline training with a separately authored validation split."""

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .classifier import CATEGORIES, DEFAULT_MODEL, EmailClassifier, email_text

DATA_DIR = Path(__file__).resolve().parent / "data"


def read_samples(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError(f"No labelled examples in {path}")
    for row in rows:
        if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key].strip() for key in ("id", "group", "subject", "body", "category")):
            raise ValueError("Each example requires nonempty id, group, subject, body and category strings.")
        if row["category"] not in CATEGORIES:
            raise ValueError(f"Unknown category: {row['category']}")
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Example IDs must be unique within each split.")
    if {row["category"] for row in rows} != set(CATEGORIES):
        raise ValueError("Each split must include all five categories.")
    return rows


def validate_splits(train: list[dict], validation: list[dict]) -> None:
    for key in ("id", "group"):
        if {row[key] for row in train} & {row[key] for row in validation}:
            raise ValueError(f"Train and validation splits share {key} values.")
    normalized = lambda rows: {" ".join(email_text(row).casefold().split()) for row in rows}
    if normalized(train) & normalized(validation):
        raise ValueError("Train and validation splits contain duplicate email text.")


def train_model(train_path: Path, validation_path: Path, model_path: Path) -> dict:
    import joblib
    import sklearn
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import classification_report, confusion_matrix
    from sklearn.pipeline import Pipeline

    train = read_samples(train_path)
    validation = read_samples(validation_path)
    validate_splits(train, validation)
    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, strip_accents="unicode")),
        ("classifier", LogisticRegression(C=4.0, max_iter=1000, class_weight="balanced", random_state=42)),
    ])
    pipeline.fit([email_text(row) for row in train], [row["category"] for row in train])
    train_hash = hashlib.sha256(train_path.read_bytes()).hexdigest()
    metadata = {
        "model_version": f"tfidf-logreg-v1-{train_hash[:12]}",
        "training_source": "synthetic_authored_bootstrap",
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "sklearn_version": sklearn.__version__,
        "train_sha256": train_hash,
        "train_counts": dict(Counter(row["category"] for row in train)),
        # Logistic-regression probabilities are uncalibrated. Route on a very
        # close top-two margin or poor vocabulary coverage instead of treating
        # a low absolute probability as uncertainty across five classes.
        "review_thresholds": {"confidence": 0.22, "margin": 0.005, "vocabulary_coverage": 0.10},
        "limitations": "Synthetic English bootstrap data. Probabilities are uncalibrated; review gates use ambiguity and vocabulary coverage. No claim of official dataset accuracy.",
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"format_version": 1, "pipeline": pipeline, "metadata": metadata}, model_path)
    classifier = EmailClassifier(model_path)
    predictions = [classifier.predict(row) for row in validation]
    labels = [row["category"] for row in validation]
    guessed = [p["predicted_category"] for p in predictions]
    report = {
        "metadata": metadata,
        "evaluation_scope": "Separately authored synthetic validation only, never used in fit. This is not official scoring or real-world accuracy.",
        "validation_sha256": hashlib.sha256(validation_path.read_bytes()).hexdigest(),
        "validation_count": len(validation), "label_order": list(CATEGORIES),
        "classification": classification_report(labels, guessed, labels=list(CATEGORIES), output_dict=True, zero_division=0),
        "confusion_matrix": confusion_matrix(labels, guessed, labels=list(CATEGORIES)).tolist(),
        "automatic_routing_count": sum(not p["needs_review"] for p in predictions),
        "classification_review_count": sum(p["needs_review"] for p in predictions),
        "examples": [{"id": row["id"], "expected_category": row["category"], **prediction} for row, prediction in zip(validation, predictions)],
    }
    model_path.with_suffix(".metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    model_path.with_suffix(".evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Train the synthetic-data email classification baseline.")
    parser.add_argument("--train", type=Path, default=DATA_DIR / "train.jsonl")
    parser.add_argument("--validation", type=Path, default=DATA_DIR / "validation.jsonl")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()
    try:
        report = train_model(args.train, args.validation, args.model)
    except (ValueError, OSError, ImportError) as exc:
        parser.exit(1, f"Training failed: {exc}\n")
    print(f"Model saved: {args.model}")
    print(f"Synthetic validation macro-F1: {report['classification']['macro avg']['f1-score']:.3f}")
    print(f"Auto-route: {report['automatic_routing_count']}/{report['validation_count']}; review: {report['classification_review_count']}")
    print("Synthetic baseline only; this is not the official dataset score.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
