"""Model-driven routing from inbox metadata to document comparison."""

import re
from pathlib import Path

from model.classifier import EmailClassifier
from .cases import auto_complete
from .comparison import compare_email
from .ingestion import load_email


def is_draft_bl_request(email: dict) -> bool:
    """Return true when the message requests a draft rather than a comparison.

    Those messages have no pair to compare yet. They are valid classified work,
    while a message explicitly asking to compare SI and BL without both files
    is an attachment failure that must be escalated.
    """
    if email.get("attachments"):
        return False
    body = str(email.get("body", "")).casefold()
    asks_for_draft = "draft bl" in body and any(
        phrase in body for phrase in ("send the draft", "provide the draft", "prepare the draft")
    )
    explicit_comparison = (
        "compare" in body
        or "cross-check" in body
        or "cross check" in body
        or (re.search(r"\bsi\b", body) and "draft bl" in body and "confirm" in body)
    )
    return asks_for_draft and not explicit_comparison


def process_email(dataset: str | Path, email_id: str, classifier: EmailClassifier, ai_assistant=None, ai_min_confidence=0.90) -> dict:
    ingested = load_email(dataset, email_id, read_attachments=False)
    classification = classifier.predict(ingested["email"])
    # Gemini is an optional second opinion only for the local model's uncertain
    # cases. Its absence or failure deliberately preserves human review.
    if classification["needs_review"] and ai_assistant is not None:
        suggestion = ai_assistant.suggest_category(ingested["email"])
        if suggestion and suggestion["confidence"] >= ai_min_confidence:
            classification.update(
                model_predicted_category=classification["predicted_category"],
                predicted_category=suggestion["category"], confidence=suggestion["confidence"],
                needs_review=False, review_details=[], decision_source="gemini_fallback",
                decision_explanation=suggestion["rationale"],
                ai_assistance={"provider": "gemini", "model": ai_assistant.model, "used": True},
            )
        elif suggestion:
            classification["review_details"].append(
                f'Gemini suggested {suggestion["category"]} at {suggestion["confidence"]:.0%}; below the automatic-routing threshold.'
            )
    result = {
        "email_id": email_id, "processing_status": "COMPLETED",
        "category": None, "classification": classification,
        "routing_source": classification.get("decision_source", "ai_classifier"),
        "routing_status": "CLASSIFICATION_REVIEW", "comparison_status": None,
        "fields": {}, "defect_fields": [], "has_defect": None,
        "review_reason": None, "review_details": classification["review_details"],
        "error": None, "review_history": [],
    }
    if classification["needs_review"]:
        return result
    result["category"] = classification["predicted_category"]
    if result["category"] != "BL_COMPARISON":
        result["routing_status"] = "CLASSIFIED_ONLY"
        return result
    if is_draft_bl_request(ingested["email"]):
        result.update(
            routing_status="DRAFT_BL_REQUEST",
            has_defect=False,
        )
        return result
    compared = compare_email(load_email(dataset, email_id), ai_assistant=ai_assistant)
    compared.update(category=result["category"], classification=classification,
                    routing_source=result["routing_source"], routing_status="COMPARED")
    return auto_complete(compared)
