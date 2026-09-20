"""Conservative, evidence-backed comparison of labelled TXT shipping documents."""

import re
import unicodedata
from decimal import Decimal


ALIASES = {
    "shipper": ["Shipper", "Shipper/Exporter", "Shipper (Principal or Seller)"],
    "consignee": ["Consignee", "Consignee (Non-Negotiable)", "To the Order of"],
    "notify_party": ["Notify", "Notify Party", "Notify Party/Intermediate Consignee"],
    "port_of_loading": ["Port of Loading", "Port of Loading (POL)", "Portof Loading", "Fortof Loading", "Load Port", "POL"],
    "port_of_discharge": ["Port of Discharge", "Port of Discharge (POD)", "Portof Discharge", "Discharge Port", "POD"],
    "container_count": ["No. of Containers", "No. of Containers or Packages", "Total Containers", "Container Count", "Containers"],
    "gross_weight_kg": [
        "Gross Weight", "Gross Weight (KG)", "Gross Weight(KGS)",
        "Gross Weightnn(KGS)", "Gross Weight毛重(KGS)", "Gross Wt (kgs)",
        "Total Gross Weight", "Total Gross Weight (KG)",
        "Total Gross Weightnn(KGS)", "Total Gross Wt (kgs)",
    ],
}


def clean(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


LABELS = {clean(label): field for field, labels in ALIASES.items() for label in labels}
NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
OCR_REVIEW_CONFIDENCE = 60.0


def normalize(field: str, value: str, label: str):
    value = clean(value)
    if value in {"", "-", "n/a", "na", "null", "none", "unknown", "tba", "tbc", "tbd"} or re.fullmatch(r"[_?\s]+", value) or re.search(r"_{2,}", value):
        raise ValueError("Required value is missing or a placeholder.")
    if field == "container_count":
        value = value.rstrip(" .:;")
        # Recognize a count or a single equipment expression, never container size.
        match = re.fullmatch(r"(\d+)(?:\s*(?:containers?|x\s*(?:20|40|45)\s*['’�°]?\s*(?:hc|gp|fcl|hq|dc)))?", value)
        if not match:
            raise ValueError("Container quantity is not an unambiguous supported format.")
        return int(match[1])
    if field == "gross_weight_kg":
        match = re.fullmatch(rf"({NUMBER})\s*(kg|kgs|kilograms?|mt|tonnes?|metric tons?)?", value)
        if not match:
            raise ValueError("Weight number or unit is missing, ambiguous or unsupported.")
        unit = match[2]
        # The workflow schema defines this field in kilograms. Carrier forms
        # commonly omit the unit beside an otherwise unambiguous number.
        amount = Decimal(match[1].replace(",", ""))
        if unit in {"mt", "tonne", "tonnes", "metric ton", "metric tons"}:
            amount *= 1000
        # Exact decimal representation, serialized as a string to avoid float loss.
        return format(amount.normalize(), "f")
    if field in {"shipper", "consignee", "notify_party"}:
        # Layout adapters represent the same address with newlines, pipes or
        # semicolons. Compare its words while retaining every name/number.
        return " ".join(re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE).split())
    if field in {"port_of_loading", "port_of_discharge"}:
        # UN/LOCODEs are optional display detail, e.g. Singapore (SGSIN).
        value = re.sub(r"\s*\([a-z]{5}\)\s*$", "", value)
        return " ".join(re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE).split())
    return value


def document_type(text: str):
    """Identify the document from its heading, allowing real form letterheads."""
    headings = [re.sub(r"^[^a-z0-9]+", "", clean(line)) for line in text.splitlines() if line.strip()][:6]
    # Check instruction first because "bill of lading instruction" contains
    # the words "bill of lading" but is the SI/reference document.
    if any(title in {
        "shipping instruction", "shipping instructions", "shipping instruction (si)",
    } or "bill of lading instruction" in title or title.startswith("bl instruction ")
           for title in headings):
        return "SI"
    if any(title in {"bill of lading", "bill of lading (draft)", "draft bill of lading"}
           or title.startswith("bill of lading ")
           or re.sub(r"[^a-z]", "", title) in {"billoflading", "billofladingdraft", "draftbilloflading"}
           for title in headings):
        return "BL"
    return None


def extract_fields(text: str, path: str) -> dict:
    """Recognize labelled fields and their indented continuation lines."""
    lines = text.splitlines()
    occurrences = {field: [] for field in ALIASES}
    aliases = sorted(
        ((alias, field) for field, names in ALIASES.items() for alias in names),
        key=lambda item: len(item[0]), reverse=True,
    )

    def match_label(line):
        # Some carrier forms place a translated label between the English
        # label and its value. Remove just that annotation before matching.
        candidate = re.sub(r"\s*\([^)]*[\u3400-\u9fff][^)]*\)\s*", " ", line.strip())
        candidate = re.sub(r"[\u3400-\u9fff]+", "", candidate)
        candidate = re.sub(r"^[^A-Za-z0-9]+", "", candidate)

        # Some generated/real PDFs place the notify-party value so close to
        # "Consignee" that pdfplumber interleaves both character streams, for
        # example "ConsCigEnReIEeX" (Consignee + CERIEX). Recover the value by
        # removing the known remaining label characters as a subsequence.
        overlapped = re.match(r"^Notify\s+Party/Intermediate\s+Cons(.*)$", candidate, re.I)
        if overlapped:
            tail = overlapped.group(1)
            remainder = iter("ignee")
            expected = next(remainder, None)
            recovered = []
            for char in tail:
                if expected is not None and char.casefold() == expected:
                    expected = next(remainder, None)
                else:
                    recovered.append(char)
            if expected is None:
                return "notify_party", "Notify Party/Intermediate Consignee", "".join(recovered).strip()

        for alias, field in aliases:
            words = re.escape(alias).replace(r"\ ", r"\s+")
            matched = re.match(rf"^({words})\s*(?:[:,.]\s*|\s+)(.*)$", candidate, re.I)
            if matched:
                return field, matched.group(1), matched.group(2).strip()
            if re.fullmatch(rf"{words}\s*[:,.]?", candidate, re.I):
                return field, candidate.rstrip(":,.").strip(), ""
        return None

    stop_heading = re.compile(
        r"^(?:vessel|voy(?:age|\.)?|description|commodity|kinds of packages|hs\s*code|"
        r"freight|booking|b/?l\s+(?:no|number)|order\s+no)\b", re.I,
    )
    for index, line in enumerate(lines):
        matched = match_label(line)
        if not matched:
            continue
        field, label, raw = matched
        end = index + 1
        continuation = []
        while end < len(lines) and lines[end].strip():
            if match_label(lines[end]):
                break
            if raw and field in {'port_of_loading', 'port_of_discharge', 'container_count', 'gross_weight_kg'}:
                break
            if stop_heading.match(lines[end].strip()) or document_type(lines[end]) is not None or set(lines[end].strip()) <= {'=', '-'}:
                break
            continuation.append(lines[end].strip())
            end += 1
        raw = "\n".join([raw.strip(), *continuation]).strip()
        item = {
            "raw_value": raw,
            "normalized_value": None,
            "source": {"attachment_path": path, "quote": "\n".join(lines[index:end]),
                       "locator": {"line_start": index + 1, "line_end": end}},
            "issue": None,
        }
        try:
            item["normalized_value"] = normalize(field, raw, label)
        except ValueError as exc:
            item["issue"] = str(exc)
        occurrences[field].append(item)

    fields = {}
    for field, items in occurrences.items():
        if not items:
            fields[field] = {"raw_value": None, "normalized_value": None, "source": None, "issue": "Required field not found."}
        elif len(items) > 1:
            fields[field] = {"raw_value": None, "normalized_value": None, "source": None,
                             "issue": "Repeated field requires review.", "candidates": items}
        else:
            fields[field] = items[0]
    return fields


def apply_ai_field_suggestions(text: str, path: str, extracted: dict, kind: str, ai_assistant) -> dict:
    """Fill only fields the deterministic parser could not locate.

    Gemini never replaces a parsed value. A suggestion is accepted only when
    its value and its quoted evidence both occur in the attachment text and
    the existing normalizer accepts the value.
    """
    if ai_assistant is None:
        return extracted
    unresolved = [
        field for field, item in extracted.items()
        if item.get('source') is None and item.get('issue') == 'Required field not found.'
    ]
    suggestions = ai_assistant.suggest_fields(kind, text, unresolved)
    if not suggestions:
        return extracted
    lines = text.splitlines()
    normalized_text = clean(text)
    for field in unresolved:
        suggestion = suggestions.get(field)
        if not isinstance(suggestion, dict):
            continue
        value = suggestion.get('value')
        evidence = suggestion.get('evidence')
        if not isinstance(value, str) or not isinstance(evidence, str):
            continue
        value, evidence = value.strip(), evidence.strip()
        if not value or not evidence or clean(value) not in normalized_text or clean(evidence) not in normalized_text:
            continue
        if clean(value) not in clean(evidence):
            continue
        try:
            normalized_value = normalize(field, value, field)
        except ValueError:
            continue
        start = next((index + 1 for index, line in enumerate(lines) if clean(value) in clean(line)), 1)
        extracted[field] = {
            'raw_value': value, 'normalized_value': normalized_value,
            'source': {
                'attachment_path': path, 'quote': evidence,
                'locator': {'line_start': start, 'line_end': start, 'method': 'gemini_verified'},
            },
            'issue': None,
        }
    return extracted


def compare_email(ingested: dict, ai_assistant=None) -> dict:
    """Explicit comparison request; does not predict the email category."""
    result = {
        "email_id": ingested["email"]["email_id"], "processing_status": "COMPLETED",
        "category": None, "classification": None, "routing_source": "manual_comparison",
        "comparison_status": None, "fields": {}, "defect_fields": [],
        "has_defect": None, "review_reason": None, "review_details": [],
        "error": None, "review_history": [],
    }
    documents = {"SI": [], "BL": []}
    reasons = []

    def review(reason, detail):
        reasons.append(reason)
        result["review_details"].append(detail)

    for document in ingested["documents"]:
        if document["status"] != "READ":
            reason = "missing_attachment" if document["status"] == "MISSING" else "unreadable"
            review(reason, f"{document['path']}: {document['error']}")
            continue
        kind = document_type(document["text"])
        if kind is None:
            review("wrong_doc_type", f"{document['path']}: unrecognized document title; expected SI or BL.")
        else:
            extracted = extract_fields(document["text"], document["path"])
            extracted = apply_ai_field_suggestions(document["text"], document["path"], extracted, kind, ai_assistant)
            def locate(item):
                if item.get('source') and document.get('line_sources'):
                    loc = item['source']['locator']
                    loc['locations'] = document['line_sources'][loc['line_start'] - 1:loc['line_end']]
                for candidate in item.get('candidates', []):
                    locate(candidate)
            for item in extracted.values():
                locate(item)
            documents[kind].append(extracted)
            for warning in document.get('warnings', []):
                # Matching OCR output only proves that the extracted strings
                # agree. It does not prove that either scan was read correctly.
                # Keep the extracted comparison visible, but require a person
                # to verify the source image before the case can complete.
                review('unreadable', f"{document['path']}: {warning}")
            for field, item in extracted.items():
                locations = ((item.get('source') or {}).get('locator') or {}).get('locations', [])
                confidences = [
                    float(location['confidence']) for location in locations
                    if location.get('method') == 'tesseract' and location.get('confidence') is not None
                ]
                if confidences and min(confidences) < OCR_REVIEW_CONFIDENCE:
                    review(
                        'unreadable',
                        f"{document['path']}: OCR confidence is low for {field.replace('_', ' ')}; confirm the source value.",
                    )

    for kind, matches in documents.items():
        if len(matches) > 1:
            review("wrong_doc_type", f"Multiple {kind} documents; select the intended shipment pair.")
        elif not matches:
            # Keep the concrete read/type error as primary reason, if present.
            review("missing_attachment", f"No readable, uniquely identified {kind} document available.")

    for field in ALIASES:
        si = documents["SI"][0][field] if len(documents["SI"]) == 1 else None
        bl = documents["BL"][0][field] if len(documents["BL"]) == 1 else None
        state = "UNKNOWN"
        for kind, item in (("SI", si), ("BL", bl)):
            if item and item["issue"]:
                review("missing_value", f"{kind}.{field}: {item['issue']}")
        if si and bl and not si["issue"] and not bl["issue"]:
            same = si["normalized_value"] == bl["normalized_value"]
            locations = [
                *(((si.get('source') or {}).get('locator') or {}).get('locations', [])),
                *(((bl.get('source') or {}).get('locator') or {}).get('locations', [])),
            ]
            used_ocr = any(location.get('method') == 'tesseract' for location in locations)
            if not same and used_ocr and field in {'shipper', 'consignee', 'notify_party'}:
                same = re.sub(r'\W+', '', str(si['normalized_value'])) == re.sub(r'\W+', '', str(bl['normalized_value']))
            state = "MATCH" if same else "MISMATCH"
            if state == "MISMATCH":
                result["defect_fields"].append(field)
                if used_ocr:
                    review('unreadable', f"OCR produced different values for {field.replace('_', ' ')}; confirm both source documents.")
        result["fields"][field] = {"si": si, "bl": bl, "state": state}

    if reasons:
        result.update(comparison_status="NEEDS_REVIEW", review_reason=reasons[0])
        if result["defect_fields"]:
            result["has_defect"] = True
    else:
        defect = bool(result["defect_fields"])
        result.update(comparison_status="MISMATCH" if defect else "OK", has_defect=defect)
    return result
