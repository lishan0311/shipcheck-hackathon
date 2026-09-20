"""Five-class text model; no labels are inferred from filenames or attachments."""

import re
from pathlib import Path

CATEGORIES = ("BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM")
DEFAULT_MODEL = Path(__file__).resolve().parent / "artifacts" / "email_classifier.joblib"


def email_text(email: dict) -> str:
    """Use the current subject/body, removing common signature and reply blocks."""
    subject = email.get("subject", "")
    body = email.get("body", "")
    if not isinstance(subject, str) or not isinstance(body, str):
        raise ValueError("Email subject and body must be strings.")
    kept = []
    for line in body.splitlines():
        stripped = line.strip()
        if re.match(r"^(best regards|kind regards|regards)\s*[,!.:]?\s*$", stripped, re.I):
            break
        if re.match(r"^(?:_{5,}|-{5,}|from:\s|on .+wrote:)", stripped, re.I):
            break
        if stripped.lower().startswith("warning: this email originated outside"):
            continue
        kept.append(line)
    return subject + "\n" + "\n".join(kept)


def explicit_workflow_intent(text: str) -> tuple[str, str] | None:
    """Recognize a few unambiguous workflow phrases before model routing.

    The rules describe business intent rather than relying on sender, ID, or
    filename. Free-form messages continue to use the statistical classifier.
    """
    normalized = " ".join(text.casefold().split())
    has_inline_si = all(
        marker in normalized
        for marker in ("shipper:", "consignee:", "notify party:", "pol:", "pod:")
    )
    comparison_cues = (
        "compare" in normalized
        or "cross-check" in normalized
        or "cross check" in normalized
        or ("check" in normalized and " si " in f" {normalized} " and " bl " in f" {normalized} ")
    )
    if (
        "please find shipping instruction" in normalized
        and has_inline_si
        and not comparison_cues
    ):
        return "SI_REQUEST", "An inline shipping instruction was supplied for preparation of a draft BL."
    if (
        "please assist to send the draft bl" in normalized
        and not comparison_cues
    ):
        return "BL_COMPARISON", "The sender asks for a draft BL to be returned for checking."
    if "requesting to cancel invoice" in normalized or "request to cancel invoice" in normalized:
        return "INVOICE_QUERY", "The message asks the billing team to cancel an invoice."
    return None


class EmailClassifier:
    def __init__(self, model_path: str | Path = DEFAULT_MODEL):
        # Import lazily so reading and manual comparison stay dependency-free.
        import joblib

        try:
            artifact = joblib.load(model_path)
        except FileNotFoundError as exc:
            raise ValueError("Classifier model is missing. Run: python -m model.train") from exc
        if not isinstance(artifact, dict) or artifact.get("format_version") != 1:
            raise ValueError("Unsupported classifier artifact. Retrain the model.")
        self.model = artifact["pipeline"]
        self.metadata = artifact["metadata"]
        if set(self.model.classes_) != set(CATEGORIES):
            raise ValueError("Classifier must contain all five expected categories.")

    def predict(self, email: dict) -> dict:
        text = email_text(email)
        probabilities = self.model.predict_proba([text])[0]
        ranked = sorted(zip(self.model.classes_, probabilities), key=lambda pair: pair[1], reverse=True)
        category, confidence = ranked[0]
        margin = float(confidence - ranked[1][1])
        vectorizer = self.model.named_steps["tfidf"]
        tokens = vectorizer.build_tokenizer()(vectorizer.build_preprocessor()(text))
        known = sum(token in vectorizer.vocabulary_ for token in tokens)
        coverage = known / len(tokens) if tokens else 0.0
        gates = self.metadata["review_thresholds"]
        reasons = []
        if not tokens or known == 0:
            reasons.append("No recognized text features; confirm category manually.")
        if float(confidence) < gates["confidence"]:
            reasons.append("Top class probability is below the review threshold.")
        if margin < gates["margin"]:
            reasons.append("The two leading categories are too close.")
        if coverage < gates["vocabulary_coverage"]:
            reasons.append("Too little of the email text is represented in the training vocabulary.")
        prediction = {
            "predicted_category": str(category),
            "confidence": float(confidence), "margin": margin,
            "probabilities": {str(label): float(p) for label, p in ranked},
            "vocabulary_coverage": coverage,
            "needs_review": bool(reasons), "review_details": reasons,
            "model_version": self.metadata["model_version"],
            "training_source": self.metadata["training_source"],
            "review_thresholds": gates,
            "decision_source": "tfidf_logistic_regression",
        }
        intent = explicit_workflow_intent(text)
        if intent:
            resolved_category, explanation = intent
            prediction.update(
                model_predicted_category=str(category),
                predicted_category=resolved_category,
                needs_review=False,
                review_details=[],
                decision_source="explicit_workflow_intent",
                decision_explanation=explanation,
            )
        return prediction
