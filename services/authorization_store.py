"""
authorization_store.py - saving and reading authorizations rows (the SQL for that table lives only here).

Same MySQL + Memory pattern as assessment_store.py and lab_document_store.py. Business rules (who may request whom,
what a status change means, what "accepted" lets a professional see) live in services/authorizations.py, NOT here -
this file only ever does what it is told, and every method is scoped so one person's rows are never reachable
through another person's request.
"""
import mysql.connector
from flask import current_app

import db

STATUSES = ("pending", "accepted", "declined", "revoked")


class UnknownUserError(Exception):
    """An authorization was offered for a patient or professional that does not exist."""


def get_authorization_store():
    return current_app.extensions["authorization_store"]


def _clean(row):
    return {
        "authorization_id": row["authorization_id"],
        "patient_user_id": row["patient_user_id"],
        "professional_user_id": row["professional_user_id"],
        "status": row["status"],
        "requested_at": row["requested_at"],
        "responded_at": row.get("responded_at"),
    }


class MySQLAuthorizationStore:
    def request(self, patient_user_id, professional_user_id, requested_at):
        """
        A patient asking a professional for access, or asking again after a decline or a revoke - the SAME row is
        reused either way (see the migration's own comment for why), moved back to 'pending'. Returns the row.
        Raises UnknownUserError if either side does not exist.
        """
        try:
            with db.transaction() as cursor:
                cursor.execute(
                    "INSERT INTO authorizations (patient_user_id, professional_user_id, status, requested_at) "
                    "VALUES (%s, %s, 'pending', %s) "
                    "ON DUPLICATE KEY UPDATE status = 'pending', requested_at = VALUES(requested_at), responded_at = NULL",
                    (patient_user_id, professional_user_id, requested_at),
                )
        except mysql.connector.IntegrityError as error:
            if error.errno == 1452:
                raise UnknownUserError((patient_user_id, professional_user_id)) from error
            raise
        return self.get(patient_user_id, professional_user_id)

    def _respond(self, patient_user_id, professional_user_id, new_status, from_status, responded_at):
        with db.transaction() as cursor:
            cursor.execute(
                "UPDATE authorizations SET status = %s, responded_at = %s "
                "WHERE patient_user_id = %s AND professional_user_id = %s AND status = %s",
                (new_status, responded_at, patient_user_id, professional_user_id, from_status),
            )
            return cursor.rowcount == 1

    def accept(self, patient_user_id, professional_user_id, responded_at):
        """True if a 'pending' row for this pair was moved to 'accepted'; False if there was none (already
        answered, withdrawn, or never asked - the caller decides what that means)."""
        return self._respond(patient_user_id, professional_user_id, "accepted", "pending", responded_at)

    def decline(self, patient_user_id, professional_user_id, responded_at):
        return self._respond(patient_user_id, professional_user_id, "declined", "pending", responded_at)

    def revoke(self, patient_user_id, professional_user_id, responded_at):
        """True if an 'accepted' row for this pair was moved to 'revoked'."""
        return self._respond(patient_user_id, professional_user_id, "revoked", "accepted", responded_at)

    def get(self, patient_user_id, professional_user_id):
        row = db.query_one(
            "SELECT authorization_id, patient_user_id, professional_user_id, status, requested_at, responded_at "
            "FROM authorizations WHERE patient_user_id = %s AND professional_user_id = %s",
            (patient_user_id, professional_user_id),
        )
        return None if row is None else _clean(row)

    def list_for_patient(self, patient_user_id, statuses=None):
        """This patient's own authorizations (any status, unless narrowed), newest request first."""
        rows = db.query_all(
            "SELECT authorization_id, patient_user_id, professional_user_id, status, requested_at, responded_at "
            "FROM authorizations WHERE patient_user_id = %s ORDER BY requested_at DESC, authorization_id DESC",
            (patient_user_id,),
        )
        return [_clean(row) for row in rows if statuses is None or row["status"] in statuses]

    def list_for_professional(self, professional_user_id, statuses=None):
        rows = db.query_all(
            "SELECT authorization_id, patient_user_id, professional_user_id, status, requested_at, responded_at "
            "FROM authorizations WHERE professional_user_id = %s ORDER BY requested_at DESC, authorization_id DESC",
            (professional_user_id,),
        )
        return [_clean(row) for row in rows if statuses is None or row["status"] in statuses]


class MemoryAuthorizationStore:
    """The same methods, kept in memory. It asks the user store whether each side exists, like the foreign keys do."""

    def __init__(self, user_store):
        self._user_store = user_store
        self._rows = []
        self._next_id = 1

    def _find(self, patient_user_id, professional_user_id):
        return next((row for row in self._rows
                    if row["patient_user_id"] == patient_user_id and row["professional_user_id"] == professional_user_id), None)

    def request(self, patient_user_id, professional_user_id, requested_at):
        if self._user_store.find_by_id(patient_user_id) is None or self._user_store.find_by_id(professional_user_id) is None:
            raise UnknownUserError((patient_user_id, professional_user_id))
        row = self._find(patient_user_id, professional_user_id)
        if row is None:
            row = {"authorization_id": self._next_id, "patient_user_id": patient_user_id, "professional_user_id": professional_user_id,
                  "status": "pending", "requested_at": requested_at, "responded_at": None}
            self._next_id += 1
            self._rows.append(row)
        else:
            row["status"], row["requested_at"], row["responded_at"] = "pending", requested_at, None
        return self.get(patient_user_id, professional_user_id)

    def _respond(self, patient_user_id, professional_user_id, new_status, from_status, responded_at):
        row = self._find(patient_user_id, professional_user_id)
        if row is None or row["status"] != from_status:
            return False
        row["status"], row["responded_at"] = new_status, responded_at
        return True

    def accept(self, patient_user_id, professional_user_id, responded_at):
        return self._respond(patient_user_id, professional_user_id, "accepted", "pending", responded_at)

    def decline(self, patient_user_id, professional_user_id, responded_at):
        return self._respond(patient_user_id, professional_user_id, "declined", "pending", responded_at)

    def revoke(self, patient_user_id, professional_user_id, responded_at):
        return self._respond(patient_user_id, professional_user_id, "revoked", "accepted", responded_at)

    def get(self, patient_user_id, professional_user_id):
        row = self._find(patient_user_id, professional_user_id)
        return None if row is None else _clean(row)

    def list_for_patient(self, patient_user_id, statuses=None):
        mine = [row for row in self._rows if row["patient_user_id"] == patient_user_id and (statuses is None or row["status"] in statuses)]
        mine.sort(key=lambda row: (row["requested_at"], row["authorization_id"]), reverse=True)
        return [_clean(row) for row in mine]

    def list_for_professional(self, professional_user_id, statuses=None):
        mine = [row for row in self._rows if row["professional_user_id"] == professional_user_id and (statuses is None or row["status"] in statuses)]
        mine.sort(key=lambda row: (row["requested_at"], row["authorization_id"]), reverse=True)
        return [_clean(row) for row in mine]
