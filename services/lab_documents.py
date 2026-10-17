"""
lab_documents.py - saving an uploaded lab document to disk under UPLOAD_DIR, and reading it back for OCR.

The file itself lives OUTSIDE static/ (never reachable by guessing a URL) and is named by a random token, never by
anything the uploader chose - the original filename is kept only as text in lab_document_store, for display. Only
image/jpeg, image/png and application/pdf are accepted, and only up to MAX_UPLOAD_BYTES: this is checked from the
file's OWN bytes (not just the browser's claimed content type, which a person could send incorrectly or, on
purpose, dishonestly).
"""
import os
import secrets

from services.lab_ocr import ALLOWED_CONTENT_TYPES, MAX_UPLOAD_BYTES

_SIGNATURES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"%PDF-": "application/pdf",
}


class RejectedUpload(ValueError):
    """The uploaded file is too large, or is not really one of the accepted types."""


def sniff_content_type(head):
    """The real content type of a file, read from its own first bytes - never trust a claimed one alone."""
    for signature, content_type in _SIGNATURES.items():
        if head.startswith(signature):
            return content_type
    return None


def save_upload(file_storage, upload_dir):
    """
    Save an uploaded file (a werkzeug FileStorage, or anything with .read()) under upload_dir with a random name.
    Returns (stored_filename, content_type, original_filename). Raises RejectedUpload for anything too large or
    not a real JPEG, PNG or PDF - checked from the bytes themselves, so a mislabelled or disguised file is refused
    just as if it had announced itself honestly.
    """
    data = file_storage.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise RejectedUpload(f"the file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if not data:
        raise RejectedUpload("the file is empty.")
    content_type = sniff_content_type(data[:16])
    if content_type is None:
        raise RejectedUpload("only JPEG, PNG or PDF files are accepted.")

    stored_filename = secrets.token_hex(16) + ALLOWED_CONTENT_TYPES[content_type]
    try:
        os.makedirs(upload_dir, exist_ok=True)
        with open(os.path.join(upload_dir, stored_filename), "wb") as handle:
            handle.write(data)
    except OSError as error:
        # A real, environment-specific problem (no permission to write there, the disk is full, the folder is
        # locked by another program) - never a raw crash. UPLOAD_DIR and its cause are only in the server log,
        # never shown to the person, since the exact path is not something they can act on.
        raise RejectedUpload(f"the file could not be saved on the server ({type(error).__name__}). "
                             f"The team has been told through the server log.") from error
    original_filename = getattr(file_storage, "filename", None) or "upload"
    return stored_filename, content_type, original_filename


def path_for(upload_dir, stored_filename):
    return os.path.join(upload_dir, stored_filename)
