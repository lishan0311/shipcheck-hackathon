import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

from backend.comparison import compare_email, document_type, extract_fields, normalize
from backend.ingestion import load_email


SI = """SHIPPING INSTRUCTION
Shipper/Exporter: Example Export Ltd
  12 Main Road
  City, Country
CONSIGNEE: Example Buyer Ltd
Notify Party: Example Agent
Port of Loading: PORT A
Discharge Port: PORT B
No. of Containers: 3 x 40'HC
Gross Weight (KG): 22,000 KG
Freight: PREPAID
"""
BL = """BILL OF LADING (DRAFT)
Shipper: EXAMPLE EXPORT LTD
  12 Main Road
  City, Country
Consignee (Non-Negotiable): Example Buyer Ltd
Notify: Example Agent
POL: port a
POD: port b
Container Count: 3
Gross Wt (kgs): 22 MT
Freight: PREPAID
"""


def sample():
    return {"email": {"email_id": "demo_compare"}, "documents": [
        {"path": "attachments/one.txt", "status": "READ", "text": SI, "error": None},
        {"path": "attachments/two.txt", "status": "READ", "text": BL, "error": None},
    ]}


class ComparisonTests(unittest.TestCase):
    def test_document_type_allows_letterhead_and_real_form_headings(self):
        self.assertEqual(document_type("Company Name\nBL INSTRUCTION 12345\nShipper: A"), "SI")
        self.assertEqual(document_type("BILL OF LADING INSTRUCTION\nShipper A"), "SI")
        self.assertEqual(document_type("Company Name\nBILL OF LADING 12345\nShipper: A"), "BL")
        self.assertEqual(document_type("BILL OF LADING (DRAFT)\nShipper A"), "BL")
        self.assertEqual(document_type("BILLOF LADING (DRAFT)\nShipper. A"), "BL")
        self.assertEqual(document_type("�SHIPPING INSTRUCTION\nShipper: A"), "SI")
        self.assertIsNone(document_type("COMMERCIAL INVOICE\nSeller: A"))

    def test_common_ocr_label_noise_still_extracts_shipping_fields(self):
        fields = extract_fields("""SHIPPING INSTRUCTION
Shipper. APRIL FINE PAPER TRADING
Consignee: KPP-ANTALIS (SINGAPORE) PTE. LTD.
Notify. EAST BRIGHT FZ-LLC
Fortof Loading: NHAVA SHEVA INDIA
Port of Discharge: VALPARAISO, CHILE
Containers 10 x 40�FCL.
Gross Weight 237,750 KG
""", "scan.pdf")
        self.assertEqual(fields["shipper"]["normalized_value"], "april fine paper trading")
        self.assertEqual(fields["port_of_loading"]["normalized_value"], "nhava sheva india")
        self.assertEqual(fields["container_count"]["normalized_value"], 10)
        self.assertEqual(fields["gross_weight_kg"]["normalized_value"], "237750")

    def test_recovers_pdf_interleaved_notify_party_label_and_value(self):
        examples = {
            "Notify Party/Intermediate ConsCigEnReIEeX": "ceriex",
            "Notify Party/Intermediate ConsKiTgPne CeO., LTD": "ktp co ltd",
            "Notify Party/Intermediate ConsNigAnGeAePPA EXPORTS": "nagappa exports",
        }
        for line, expected in examples.items():
            with self.subTest(line=line):
                field = extract_fields(
                    f"SHIPPING INSTRUCTION\n{line}\nPOL: SINGAPORE",
                    "overlap.pdf",
                )["notify_party"]
                self.assertEqual(field["normalized_value"], expected)

    def test_pdf_and_bilingual_docx_style_labels_without_colons(self):
        fields = extract_fields("""BILL OF LADING (DRAFT)
Shipper (发货人) Example Export Ltd
12 Main Road
Consignee (收货人) Example Buyer Ltd
Notify Party (通知人) Example Agent
Port of Loading (装货港) PORT A
POD (卸货港) PORT B
Total Containers (箱数) 3 x 40'HC
Gross Wt (kgs) (毛重 KGS) 22,000
Vessel Name Demo Vessel
""", "demo.docx")
        self.assertEqual(fields["shipper"]["raw_value"], "Example Export Ltd\n12 Main Road")
        self.assertEqual(fields["port_of_loading"]["normalized_value"], "port a")
        self.assertEqual(fields["container_count"]["normalized_value"], 3)
        self.assertEqual(fields["gross_weight_kg"]["normalized_value"], "22000")

    def test_pdf_style_unindented_address_is_not_discarded(self):
        data = sample()
        for document in data['documents']:
            document['text'] = document['text'].replace('  12 Main Road', '12 Main Road').replace('  City, Country', 'City, Country')
        data['documents'][1]['text'] = data['documents'][1]['text'].replace('12 Main Road', '13 Main Road')
        self.assertEqual(compare_email(data)['defect_fields'], ['shipper'])

    def test_aliases_units_case_and_multiline_addresses_match(self):
        result = compare_email(sample())
        self.assertEqual(result["comparison_status"], "OK")
        self.assertEqual(len(result["fields"]), 7)
        self.assertEqual(result["fields"]["gross_weight_kg"]["bl"]["normalized_value"], "22000")
        item = result["fields"]["shipper"]["si"]
        self.assertIn("City, Country", item["raw_value"])
        self.assertEqual(item["source"]["locator"], {"line_start": 2, "line_end": 4})
        self.assertIsNone(result["category"])

    def test_ocr_match_still_requires_source_verification(self):
        data = sample()
        for document in data['documents']:
            document['warnings'] = ['Page 1 used OCR; confirm the extracted values before approval.']
            document['line_sources'] = [
                {'page': 1, 'method': 'tesseract', 'confidence': 90}
                for _ in document['text'].splitlines()
            ]
        result = compare_email(data)
        self.assertEqual(result['comparison_status'], 'NEEDS_REVIEW')
        self.assertTrue(any('used OCR' in detail for detail in result['review_details']))

    def test_low_confidence_ocr_field_still_requires_manual_review(self):
        data = sample()
        for document in data['documents']:
            document['warnings'] = ['Page 1 used OCR; confirm the extracted values before approval.']
            document['line_sources'] = [
                {'page': 1, 'method': 'tesseract', 'confidence': 40}
                for _ in document['text'].splitlines()
            ]
        result = compare_email(data)
        self.assertEqual(result['comparison_status'], 'NEEDS_REVIEW')
        self.assertTrue(any('OCR confidence is low' in detail for detail in result['review_details']))

    def test_reports_only_changed_count(self):
        data = sample()
        data["documents"][1]["text"] = BL.replace("Container Count: 3", "Container Count: 4")
        result = compare_email(data)
        self.assertEqual(result["comparison_status"], "MISMATCH")
        self.assertEqual(result["defect_fields"], ["container_count"])

    def test_address_change_is_not_discarded(self):
        data = sample()
        data["documents"][1]["text"] = BL.replace("12 Main Road", "13 Main Road")
        self.assertEqual(compare_email(data)["defect_fields"], ["shipper"])

    def test_party_layout_and_optional_port_codes_do_not_create_false_defects(self):
        self.assertEqual(
            normalize("shipper", "Example Ltd | 12 Main Road; City", "Shipper"),
            normalize("shipper", "Example Ltd\n12 Main Road, City", "Shipper"),
        )
        self.assertEqual(
            normalize("port_of_loading", "Singapore (SGSIN)", "POL"),
            normalize("port_of_loading", "SINGAPORE", "Port of Loading"),
        )

    def test_missing_field_on_both_sides_is_not_a_match(self):
        data = sample()
        for doc in data["documents"]:
            doc["text"] = "\n".join(line for line in doc["text"].splitlines() if not line.startswith("Notify"))
        result = compare_email(data)
        self.assertEqual(result["comparison_status"], "NEEDS_REVIEW")
        self.assertEqual(result["fields"]["notify_party"]["state"], "UNKNOWN")
        self.assertIsNone(result["has_defect"])

    def test_preserves_known_defect_when_another_field_is_unknown(self):
        data = sample()
        data["documents"][1]["text"] = BL.replace("Container Count: 3", "Container Count: 4").replace("22 MT", "____MT")
        result = compare_email(data)
        self.assertEqual(result["comparison_status"], "NEEDS_REVIEW")
        self.assertEqual(result["defect_fields"], ["container_count"])
        self.assertTrue(result["has_defect"])

    def test_missing_unsupported_wrong_and_duplicate_documents(self):
        for status, expected in (("MISSING", "missing_attachment"), ("UNSUPPORTED", "unreadable")):
            with self.subTest(status=status):
                data = sample()
                data["documents"][1].update(status=status, text=None, error="demo failure")
                self.assertEqual(compare_email(data)["review_reason"], expected)
        data = sample()
        data["documents"][1]["text"] = BL.replace("BILL OF LADING (DRAFT)", "COMMERCIAL INVOICE")
        self.assertEqual(compare_email(data)["review_reason"], "wrong_doc_type")
        data = sample()
        data["documents"].append(copy.deepcopy(data["documents"][0]))
        self.assertEqual(compare_email(data)["comparison_status"], "NEEDS_REVIEW")
        self.assertIsNone(compare_email(data)["fields"]["shipper"]["si"])

    def test_duplicate_fields_retain_both_sources(self):
        fields = extract_fields(SI + "Gross Weight (KG): 23,000 KG\n", "demo.txt")
        self.assertIsNone(fields["gross_weight_kg"]["normalized_value"])
        self.assertEqual(len(fields["gross_weight_kg"]["candidates"]), 2)

    def test_ambiguous_numbers_and_missing_units_are_not_guessed(self):
        for value in ("22,5 KG", "22.000,50 KG", "22 tons", "-1 KG"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize("gross_weight_kg", value, "GROSS WEIGHT")
        for value in ("3 + 2", "40'HC", "3 x 40'HC + 2 x 20'GP"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize("container_count", value, "Container Count")
        self.assertEqual(normalize("gross_weight_kg", "22000.50", "Gross Weight (KG)"), "22000.5")
        self.assertEqual(normalize("gross_weight_kg", "22000", "Gross Weight"), "22000")
        for value in ("TBA", "____MT"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize("port_of_loading", value, "POL")

    def test_real_email_001_and_json_cli(self):
        root = Path(__file__).resolve().parents[1]
        result = compare_email(load_email(root / "sdoc-hackathon-bundle", "email_001"))
        self.assertEqual(result["comparison_status"], "OK")
        process = subprocess.run([sys.executable, "-m", "backend", "--compare", "--json"], cwd=root, capture_output=True, encoding="utf-8")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["comparison_status"], "OK")


if __name__ == "__main__":
    unittest.main()
