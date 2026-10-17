"""
lab_document_store.py - saving and reading lab_documents rows (the SQL for that table lives only here).

Same MySQL + Memory pattern as assessment_store.py: tests/test_lab_document_store.py runs the same checks against
both. A row moves through a small number of states (see database/migrations/006_create_lab_documents.sql):
  uploaded -> extracted -> confirmed          (the normal path)
  uploaded -> extracted -> discarded          (the person chose not to use it)
Only the file's OWNER can ever see or change their own row; every method here is scoped by user_id, the same way
assessment_store.py is, so a guessed id can never reach someone else's upload.
"""
import json

import mysql.connector
from flask import current_app

import db

STATUSES = ("uploaded", "extracted", "confirmed", "discarded")


class UnknownUserError(Exception):
    """A lab document was offered for a user that does not exist."""


def get_lab_document_store():
    return current_app.extensions["lab_document_store"]


def _clean(row):
    return {
        "lab_document_id": row["lab_document_id"],
        "status": row["status"],
        "original_filename": row["original_filename"],
        "stored_filename": row["stored_filename"],
        "content_type": row["content_type"],
        "ocr_values": None if row.get("ocr_values") is None else json.loads(row["ocr_values"]),
        "verification": None if row.get("verification") is None else json.loads(row["verification"]),
        "confirmed_values": None if row.get("confirmed_values") is None else json.loads(row["confirmed_values"]),
        "assessment_id": row.get("assessment_id"),
        "uploaded_at": row["uploaded_at"],
        "confirmed_at": row.get("confirmed_at"),
    }


class MySQLLabDocumentStore:
    def add_document(self, user_id, original_filename, stored_filename, content_type, uploaded_at):
        """A freshly uploaded file, before OCR has run. Returns the new lab_document_id."""
        try:
            with db.transaction() as cursor:
                cursor.execute(
                    "INSERT INTO lab_documents (user_id, status, original_filename, stored_filename, content_type, uploaded_at) "
                    "VALUES (%s, 'uploaded', %s, %s, %s, %s)",
                    (user_id, original_filename, stored_filename, content_type, uploaded_at),
                )
                return cursor.lastrowid
        except mysql.connector.IntegrityError as error:
            if error.errno == 1452:
                raise UnknownUserError(user_id) from error
            raise

    def set_ocr_values(self, user_id, lab_document_id, ocr_values):
        """Record what OCR proposed. Only affects a row that belongs to this user (silently does nothing otherwise)."""
        with db.transaction() as cursor:
            cursor.execute("UPDATE lab_documents SET status = 'extracted', ocr_values = %s WHERE lab_document_id = %s AND user_id = %s",
                           (json.dumps(ocr_values, sort_keys=True), lab_document_id, user_id))

    def set_verification(self, user_id, lab_document_id, verification):
        """The signs read from the report (services/lab_verification.py) - stored once, at upload."""
        db.execute("UPDATE lab_documents SET verification = %s WHERE lab_document_id = %s AND user_id = %s",
                   (json.dumps(verification, sort_keys=True), lab_document_id, user_id))

    def confirm(self, user_id, lab_document_id, confirmed_values, assessment_id, confirmed_at):
        """The person reviewed the values and an Enhanced Screening result now exists from them."""
        with db.transaction() as cursor:
            cursor.execute(
                "UPDATE lab_documents SET status = 'confirmed', confirmed_values = %s, assessment_id = %s, confirmed_at = %s "
                "WHERE lab_document_id = %s AND user_id = %s",
                (json.dumps(confirmed_values, sort_keys=True), assessment_id, confirmed_at, lab_document_id, user_id))

    def discard(self, user_id, lab_document_id):
        with db.transaction() as cursor:
            cursor.execute("UPDATE lab_documents SET status = 'discarded' WHERE lab_document_id = %s AND user_id = %s",
                           (lab_document_id, user_id))

    def get_document(self, user_id, lab_document_id):
        """One upload, but only if it belongs to THIS user (otherwise None, as if it did not exist)."""
        row = db.query_one(
            "SELECT lab_document_id, status, original_filename, stored_filename, content_type, ocr_values, confirmed_values, verification, "
            "assessment_id, uploaded_at, confirmed_at FROM lab_documents WHERE lab_document_id = %s AND user_id = %s",
            (lab_document_id, user_id),
        )
        return None if row is None else _clean(row)

    def list_documents(self, user_id):
        rows = db.query_all(
            "SELECT lab_document_id, status, original_filename, stored_filename, content_type, ocr_values, confirmed_values, verification, "
            "assessment_id, uploaded_at, confirmed_at FROM lab_documents WHERE user_id = %s ORDER BY uploaded_at DESC, lab_document_id DESC",
            (user_id,),
        )
        return [_clean(row) for row in rows]


class MemoryLabDocumentStore:
    """The same methods, kept in memory. It asks the user store whether the user exists, like the foreign key does."""

    def __init__(self, user_store):
        self._user_store = user_store
        self._rows = []
        self._next_id = 1

    def add_document(self, user_id, original_filename, stored_filename, content_type, uploaded_at):
        if self._user_store.find_by_id(user_id) is None:
            raise UnknownUserError(user_id)
        row = {"lab_document_id": self._next_id, "user_id": user_id, "status": "uploaded", "original_filename": original_filename,
              "stored_filename": stored_filename, "content_type": content_type, "ocr_values": None, "confirmed_values": None, "verification": None,
              "assessment_id": None, "uploaded_at": uploaded_at, "confirmed_at": None}
        self._next_id += 1
        self._rows.append(row)
        return row["lab_document_id"]

    def _find(self, user_id, lab_document_id):
        return next((row for row in self._rows if row["lab_document_id"] == lab_document_id and row["user_id"] == user_id), None)

    def set_ocr_values(self, user_id, lab_document_id, ocr_values):
        row = self._find(user_id, lab_document_id)
        if row is not None:
            row["status"] = "extracted"
            row["ocr_values"] = json.dumps(ocr_values, sort_keys=True)

    def set_verification(self, user_id, lab_document_id, verification):
        row = self._find(user_id, lab_document_id)
        if row is not None:
            row["verification"] = json.dumps(verification, sort_keys=True)

    def confirm(self, user_id, lab_document_id, confirmed_values, assessment_id, confirmed_at):
        row = self._find(user_id, lab_document_id)
        if row is not None:
            row["status"] = "confirmed"
            row["confirmed_values"] = json.dumps(confirmed_values, sort_keys=True)
            row["assessment_id"] = assessment_id
            row["confirmed_at"] = confirmed_at

    def discard(self, user_id, lab_document_id):
        row = self._find(user_id, lab_document_id)
        if row is not None:
            row["status"] = "discarded"

    def get_document(self, user_id, lab_document_id):
        row = self._find(user_id, lab_document_id)
        return None if row is None else _clean(row)

    def list_documents(self, user_id):
        mine = [row for row in self._rows if row["user_id"] == user_id]
        mine.sort(key=lambda row: (row["uploaded_at"], row["lab_document_id"]), reverse=True)
        return [_clean(row) for row in mine]
