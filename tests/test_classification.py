import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from model.classifier import EmailClassifier, email_text, explicit_workflow_intent
from backend.pipeline import process_email
from model.train import DATA_DIR, read_samples, train_model, validate_splits


class ClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.model_path = Path(cls.temp.name) / "classifier.joblib"
        cls.report = train_model(DATA_DIR / "train.jsonl", DATA_DIR / "validation.jsonl", cls.model_path)
        cls.classifier = EmailClassifier(cls.model_path)

    def test_saved_model_recognizes_each_training_intent(self):
        rows = read_samples(DATA_DIR / "train.jsonl")
        # Serialization/label mapping check, not an accuracy benchmark.
        for category in {row["category"] for row in rows}:
            row = next(row for row in rows if row["category"] == category)
            with self.subTest(category=category):
                prediction = self.classifier.predict(row)
                self.assertEqual(prediction["predicted_category"], category)
                self.assertAlmostEqual(sum(prediction["probabilities"].values()), 1.0)

    def test_empty_and_unknown_inputs_request_review(self):
        for body in ("", "zxqvvv qqqrrr zzznnn"):
            with self.subTest(body=body):
                prediction = self.classifier.predict({"subject": "", "body": body})
                self.assertTrue(prediction["needs_review"])

    def test_features_exclude_ids_sender_paths_signature_and_quoted_thread(self):
        first = {"subject": "Check", "body": "Compare SI and BL.\nBest Regards,\nSecret signature\nFrom: Old sender", "email_id": "secret", "from": "secret", "attachments": ["secret.txt"]}
        self.assertEqual(email_text(first), "Check\nCompare SI and BL.")
        self.assertEqual(email_text({"subject": "Check", "body": "New request\n______\nold invoice"}), "Check\nNew request")

    def test_split_overlap_is_rejected(self):
        train = read_samples(DATA_DIR / "train.jsonl")
        validation = read_samples(DATA_DIR / "validation.jsonl")
        validate_splits(train, validation)
        for key in ("id", "group"):
            changed = [dict(row) for row in validation]
            changed[0][key] = train[0][key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_splits(train, changed)
        changed = [dict(row) for row in validation]
        changed[0].update(subject=train[0]["subject"], body=train[0]["body"])
        with self.assertRaises(ValueError):
            validate_splits(train, changed)

    def test_evaluation_reports_unfiltered_predictions_and_review_coverage(self):
        self.assertEqual(self.report["validation_count"], 15)
        self.assertEqual(len(self.report["examples"]), 15)
        self.assertEqual(self.report["automatic_routing_count"] + self.report["classification_review_count"], 15)
        self.assertTrue(self.model_path.with_suffix(".evaluation.json").is_file())

    def test_real_email_routes_through_model_to_comparison(self):
        dataset = Path(__file__).resolve().parents[1] / "sdoc-hackathon-bundle"
        result = process_email(dataset, "email_001", self.classifier)
        self.assertEqual(result["routing_source"], "tfidf_logistic_regression")
        self.assertEqual(result["category"], "BL_COMPARISON")
        self.assertEqual(result["comparison_status"], "OK")

    def test_explicit_workflow_intent_only_resolves_clear_business_language(self):
        inline_si = """Please find Shipping instruction for 5ALT-12567.
POL: PORT KLANG
POD: KOPER
Shipper: Example Exporter
Consignee: Example Buyer
Notify Party: Example Agent
Please revert with draft BL once available."""
        self.assertEqual(explicit_workflow_intent(inline_si)[0], "SI_REQUEST")
        self.assertEqual(
            explicit_workflow_intent("Please assist to send the draft BL for checking asap.")[0],
            "BL_COMPARISON",
        )
        self.assertEqual(explicit_workflow_intent("Request to cancel invoice 123")[0], "INVOICE_QUERY")
        self.assertIsNone(explicit_workflow_intent("Please compare the attached SI and draft BL."))


class RoutingTests(unittest.TestCase):
    def result(self, category, needs_review=False):
        return {"predicted_category": category, "needs_review": needs_review,
                "review_details": ["Low confidence"] if needs_review else []}

    def test_noncomparison_and_uncertain_routes_do_not_read_attachments(self):
        for category, uncertain in (("GENERAL", False), ("INVOICE_QUERY", False), ("SI_REQUEST", False), ("SPAM", False), ("BL_COMPARISON", True)):
            with self.subTest(category=category, uncertain=uncertain):
                classifier = Mock()
                classifier.predict.return_value = self.result(category, uncertain)
                with patch("backend.pipeline.load_email", return_value={"email": {"subject": "demo", "body": "demo"}}) as loader, patch("backend.pipeline.compare_email") as compare:
                    result = process_email("demo", "demo_001", classifier)
                loader.assert_called_once_with("demo", "demo_001", read_attachments=False)
                compare.assert_not_called()
                self.assertIsNone(result["comparison_status"])
                self.assertEqual(result["category"], None if uncertain else category)
                self.assertEqual(result["routing_status"], "CLASSIFICATION_REVIEW" if uncertain else "CLASSIFIED_ONLY")

    def test_confident_comparison_does_not_skip_missing_attachment(self):
        classifier = Mock()
        classifier.predict.return_value = self.result("BL_COMPARISON")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "inbox").mkdir()
            (root / "inbox/demo.json").write_text(json.dumps({"email_id": "demo", "from": "demo@example.com", "subject": "Check SI and BL", "body": "Compare please", "attachments": ["attachments/missing.txt"]}), encoding="utf-8")
            result = process_email(root, "demo", classifier)
        self.assertEqual(result["comparison_status"], "NEEDS_REVIEW")
        self.assertEqual(result["review_reason"], "missing_attachment")

    def test_draft_bl_request_without_documents_is_classified_without_comparison(self):
        classifier = Mock()
        classifier.predict.return_value = self.result("BL_COMPARISON")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "inbox").mkdir()
            (root / "inbox/demo.json").write_text(json.dumps({
                "email_id": "demo",
                "from": "demo@example.com",
                "subject": "Request BL draft",
                "body": "Please assist to send the draft BL for checking asap.\nShipping Documentation",
                "attachments": [],
            }), encoding="utf-8")
            result = process_email(root, "demo", classifier)
        self.assertEqual(result["routing_status"], "DRAFT_BL_REQUEST")
        self.assertIsNone(result["comparison_status"])
        self.assertFalse(result["has_defect"])


if __name__ == "__main__":
    unittest.main()
