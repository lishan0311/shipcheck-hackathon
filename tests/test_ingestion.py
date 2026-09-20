import json
import tempfile
import unittest
from pathlib import Path

from backend.ingestion import IngestionError, load_email


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "inbox").mkdir()
        (self.root / "attachments").mkdir()

    def email(self, attachments):
        payload = {"email_id": "demo_001", "from": "demo@example.com", "subject": "核对", "body": "Please check.", "attachments": attachments}
        (self.root / "inbox/demo_001.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_reads_paths_from_email_and_preserves_unicode(self):
        self.email(["attachments/custom-name.txt"])
        (self.root / "attachments/custom-name.txt").write_text("Shipper: 测试公司\n", encoding="utf-8-sig")
        result = load_email(self.root, "demo_001")
        self.assertEqual(result["ingestion_status"], "LOADED")
        self.assertEqual(result["documents"][0]["text"], "Shipper: 测试公司\n")

    def test_missing_file_does_not_discard_readable_attachment(self):
        self.email(["attachments/si.txt", "attachments/bl.txt"])
        (self.root / "attachments/si.txt").write_text("SI", encoding="utf-8")
        result = load_email(self.root, "demo_001")
        self.assertEqual(result["ingestion_status"], "PARTIAL")
        self.assertEqual([d["status"] for d in result["documents"]], ["READ", "MISSING"])

    def test_unsupported_invalid_encoding_and_empty_files(self):
        self.email(["attachments/doc.bin", "attachments/bad.txt", "attachments/empty.txt"])
        (self.root / "attachments/doc.bin").write_bytes(b"binary")
        (self.root / "attachments/bad.txt").write_bytes(b"\xff")
        (self.root / "attachments/empty.txt").write_text("  ")
        result = load_email(self.root, "demo_001")
        self.assertEqual([d["status"] for d in result["documents"]], ["UNSUPPORTED", "UNREADABLE", "UNREADABLE"])

    def test_rejects_paths_outside_dataset(self):
        self.email(["../outside.txt", str(self.root / "attachments/absolute.txt")])
        result = load_email(self.root, "demo_001")
        self.assertTrue(all(d["status"] == "INVALID_PATH" for d in result["documents"]))
        with self.assertRaises(IngestionError):
            load_email(self.root, "../outside")

    def test_bad_json_and_schema_are_explicit_errors(self):
        path = self.root / "inbox/demo_001.json"
        for text in ("{", "[]", '{"email_id": "demo_001"}'):
            with self.subTest(text=text):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(IngestionError):
                    load_email(self.root, "demo_001")

    def test_no_attachments_is_valid_ingestion_not_verification(self):
        self.email([])
        result = load_email(self.root, "demo_001")
        self.assertEqual(result["documents"], [])
        self.assertNotIn("comparison_status", result)


if __name__ == "__main__":
    unittest.main()
