"""Read participant emails without changing the original dataset."""

import json
import re
from pathlib import Path
from .documents import read_document, UnsupportedDocument


class IngestionError(ValueError):
    """An email cannot be loaded safely or does not match the input format."""


def _dataset_path(root: Path, relative: str) -> Path:
    path = Path(relative)
    resolved = (root / path).resolve()
    if path.is_absolute() or path.drive or not resolved.is_relative_to(root):
        raise IngestionError(f"Path must stay inside the dataset: {relative}")
    return resolved


def load_email(dataset: str | Path, email_id: str, *, read_attachments: bool = True) -> dict:
    """Return email metadata, attachment text and explicit per-file issues.

    A readable attachment does not imply that it is an SI or BL, or that its
    fields match. Classification and verification are separate later stages.
    """
    root = Path(dataset).resolve()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", email_id):
        raise IngestionError("Email ID may contain only letters, numbers, _ and -.")
    email_path = _dataset_path(root, f"inbox/{email_id}.json")
    try:
        email = json.loads(email_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IngestionError(f"Cannot read email {email_id}: {exc}") from exc

    if not isinstance(email, dict):
        raise IngestionError("Email JSON must be an object.")
    for key in ("email_id", "from", "subject", "body"):
        if not isinstance(email.get(key), str):
            raise IngestionError(f"Email field '{key}' must be a string.")
    if email["email_id"] != email_id:
        raise IngestionError("Email ID in JSON does not match the requested ID.")
    paths = email.get("attachments")
    if not isinstance(paths, list) or any(not isinstance(p, str) or not p for p in paths):
        raise IngestionError("Email attachments must be a list of nonempty path strings.")

    documents = []
    for relative in paths if read_attachments else []:
        document = {"path": relative, "status": "READ", "text": None, "error": None}
        try:
            path = _dataset_path(root, relative)
            if not path.is_file():
                document.update(status="MISSING", error="Attachment file is missing.")
            else:
                document.update(read_document(path))
        except IngestionError as exc:
            document.update(status="INVALID_PATH", error=str(exc))
        except UnsupportedDocument as exc:
            document.update(status="UNSUPPORTED", error=str(exc))
        except Exception as exc:
            document.update(status="UNREADABLE", error=f"Cannot read attachment: {exc}")
        documents.append(document)

    return {
        "email": email,
        "ingestion_status": ("PARTIAL" if any(d["status"] != "READ" for d in documents) else "LOADED") if read_attachments else "METADATA_ONLY",
        "documents": documents,
    }
