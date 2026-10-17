"""
followup_store.py - saving and reading follow_up_requests rows (the SQL for that table lives only here).

A request is "open" while fulfilled_at is NULL. mark_fulfilled() is the only way that changes, and it is meant to be
called once, right after a NEW assessment (either stage) is saved for that patient - see services/followups.py.
Business rules (who may request whom, whether an open request lets a patient skip the normal waiting period) live
in services/followups.py and services/eligibility.py, NOT here.
"""
import mysql.connector
from flask import current_app

import db

MAX_MESSAGE_LENGTH = 500


class UnknownUserError(Exception):
    """A follow-up was offered for a patient or professional that does not exist."""


def get_followup_store():
    return current_app.extensions["followup_store"]


def _clean(row):
    return {
        "follow_up_id": row["follow_up_id"],
        "patient_user_id": row["patient_user_id"],
        "professional_user_id": row.get("professional_user_id"),
        "professional_name": row["professional_name"],
        "profession_title": row.get("profession_title"),
        "message": row.get("message"),
        "requested_at": row["requested_at"],
        "fulfilled_at": row.get("fulfilled_at"),
    }


class MySQLFollowUpStore:
    def request(self, patient_user_id, professional_user_id, professional_name, profession_title, message, requested_at):
        try:
            with db.transaction() as cursor:
                cursor.execute(
                    "INSERT INTO follow_up_requests (patient_user_id, professional_user_id, professional_name, "
                    "profession_title, message, requested_at) VALUES (%s, %s, %s, %s, %s, %s)",
                    (patient_user_id, professional_user_id, professional_name, profession_title, message, requested_at),
                )
                return cursor.lastrowid
        except mysql.connector.IntegrityError as error:
            if error.errno == 1452:
                raise UnknownUserError((patient_user_id, professional_user_id)) from error
            raise

    def mark_fulfilled(self, patient_user_id, fulfilled_at):
        """Closes every OPEN request for this patient (there is normally at most one at a time, but this closes
        all of them if several exist). Returns how many were closed."""
        with db.transaction() as cursor:
            cursor.execute(
                "UPDATE follow_up_requests SET fulfilled_at = %s WHERE patient_user_id = %s AND fulfilled_at IS NULL",
                (fulfilled_at, patient_user_id),
            )
            return cursor.rowcount

    def get_open(self, patient_user_id):
        """This patient's open request, or None. If somehow more than one is open, the most recently requested."""
        row = db.query_one(
            "SELECT follow_up_id, patient_user_id, professional_user_id, professional_name, profession_title, message, "
            "requested_at, fulfilled_at FROM follow_up_requests WHERE patient_user_id = %s AND fulfilled_at IS NULL "
            "ORDER BY requested_at DESC, follow_up_id DESC LIMIT 1",
            (patient_user_id,),
        )
        return None if row is None else _clean(row)

    def list_for_patient(self, patient_user_id):
        """This patient's own requests, newest first."""
        rows = db.query_all(
            "SELECT follow_up_id, patient_user_id, professional_user_id, professional_name, profession_title, message, "
            "requested_at, fulfilled_at FROM follow_up_requests WHERE patient_user_id = %s ORDER BY requested_at DESC, follow_up_id DESC",
            (patient_user_id,),
        )
        return [_clean(row) for row in rows]

    def list_for_professional(self, professional_user_id):
        rows = db.query_all(
            "SELECT follow_up_id, patient_user_id, professional_user_id, professional_name, profession_title, message, "
            "requested_at, fulfilled_at FROM follow_up_requests WHERE professional_user_id = %s ORDER BY requested_at DESC, follow_up_id DESC",
            (professional_user_id,),
        )
        return [_clean(row) for row in rows]


class MemoryFollowUpStore:
    def __init__(self, user_store):
        self._user_store = user_store
        self._rows = []
        self._next_id = 1

    def request(self, patient_user_id, professional_user_id, professional_name, profession_title, message, requested_at):
        if self._user_store.find_by_id(patient_user_id) is None or self._user_store.find_by_id(professional_user_id) is None:
            raise UnknownUserError((patient_user_id, professional_user_id))
        row = {"follow_up_id": self._next_id, "patient_user_id": patient_user_id, "professional_user_id": professional_user_id,
              "professional_name": professional_name, "profession_title": profession_title, "message": message,
              "requested_at": requested_at, "fulfilled_at": None}
        self._next_id += 1
        self._rows.append(row)
        return row["follow_up_id"]

    def mark_fulfilled(self, patient_user_id, fulfilled_at):
        count = 0
        for row in self._rows:
            if row["patient_user_id"] == patient_user_id and row["fulfilled_at"] is None:
                row["fulfilled_at"] = fulfilled_at
                count += 1
        return count

    def get_open(self, patient_user_id):
        open_rows = [row for row in self._rows if row["patient_user_id"] == patient_user_id and row["fulfilled_at"] is None]
        if not open_rows:
            return None
        open_rows.sort(key=lambda row: (row["requested_at"], row["follow_up_id"]), reverse=True)
        return _clean(open_rows[0])

    def list_for_patient(self, patient_user_id):
        mine = [row for row in self._rows if row["patient_user_id"] == patient_user_id]
        mine.sort(key=lambda row: (row["requested_at"], row["follow_up_id"]), reverse=True)
        return [_clean(row) for row in mine]

    def list_for_professional(self, professional_user_id):
        mine = [row for row in self._rows if row["professional_user_id"] == professional_user_id]
        mine.sort(key=lambda row: (row["requested_at"], row["follow_up_id"]), reverse=True)
        return [_clean(row) for row in mine]
