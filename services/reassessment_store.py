"""
reassessment_store.py - the SQL for the re-assessment rule (migration 023): the administrator's waiting-period
setting (app_settings) and people's requests to the administrator to screen again early (reassessment_requests).

Only saving and reading lives here. The rules - who may ask, when, what approving does - are in
services/reassessment.py.
"""
import mysql.connector
from flask import current_app

import db

MONTHS_KEY = "reassessment_months"
STATUSES = ("pending", "approved", "declined", "closed")


class UnknownUserError(Exception):
    """A request was made for an account that does not exist."""


def get_reassessment_store():
    return current_app.extensions["reassessment_store"]


def _clean(row):
    return {"request_id": row["request_id"], "user_id": row["user_id"], "reason": row.get("reason"),
            "status": row["status"], "requested_at": row["requested_at"], "decided_at": row.get("decided_at"),
            "decided_by": row.get("decided_by")}


_COLUMNS = "request_id, user_id, reason, status, requested_at, decided_at, decided_by"


class MySQLReassessmentStore:
    default_months = 3          # the rule until an administrator saves one (and .env sets no REASSESSMENT_DAYS)

    # ---- the administrator's setting ----
    def get_months(self):
        """The waiting period in months, 0 for "no waiting period", or None if it was never set."""
        row = db.query_one("SELECT setting_value FROM app_settings WHERE setting_key = %s", (MONTHS_KEY,))
        if row is None:
            return None
        try:
            return int(row["setting_value"])
        except (TypeError, ValueError):
            return None

    def set_months(self, months, admin_user_id, now):
        db.execute("INSERT INTO app_settings (setting_key, setting_value, updated_at, updated_by) VALUES (%s, %s, %s, %s) "
                   "ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value), updated_at = VALUES(updated_at), "
                   "updated_by = VALUES(updated_by)", (MONTHS_KEY, str(months), now, admin_user_id))

    # ---- people's requests ----
    def add_request(self, user_id, reason, now):
        try:
            with db.transaction() as cursor:
                cursor.execute("INSERT INTO reassessment_requests (user_id, reason, status, requested_at) VALUES (%s, %s, 'pending', %s)",
                               (user_id, reason, now))
                return cursor.lastrowid
        except mysql.connector.IntegrityError as error:
            if error.errno == 1452:
                raise UnknownUserError(user_id) from error
            raise

    def get(self, request_id):
        row = db.query_one(f"SELECT {_COLUMNS} FROM reassessment_requests WHERE request_id = %s", (request_id,))
        return None if row is None else _clean(row)

    def latest_for(self, user_id):
        row = db.query_one(f"SELECT {_COLUMNS} FROM reassessment_requests WHERE user_id = %s "
                           "ORDER BY requested_at DESC, request_id DESC LIMIT 1", (user_id,))
        return None if row is None else _clean(row)

    def list(self, status=None):
        """Newest first; only one status when given."""
        if status:
            rows = db.query_all(f"SELECT {_COLUMNS} FROM reassessment_requests WHERE status = %s "
                                "ORDER BY requested_at DESC, request_id DESC", (status,))
        else:
            rows = db.query_all(f"SELECT {_COLUMNS} FROM reassessment_requests ORDER BY requested_at DESC, request_id DESC LIMIT 300")
        return [_clean(row) for row in rows]

    def decide(self, request_id, status, admin_user_id, now):
        """Moves a PENDING request to status. True if it changed (False: unknown, or already decided)."""
        with db.transaction() as cursor:
            cursor.execute("UPDATE reassessment_requests SET status = %s, decided_at = %s, decided_by = %s "
                           "WHERE request_id = %s AND status = 'pending'", (status, now, admin_user_id, request_id))
            return cursor.rowcount == 1

    def close_pending(self, user_id, now):
        """A new screening was saved: any request still waiting is no longer needed."""
        with db.transaction() as cursor:
            cursor.execute("UPDATE reassessment_requests SET status = 'closed', decided_at = %s "
                           "WHERE user_id = %s AND status = 'pending'", (now, user_id))
            return cursor.rowcount


class MemoryReassessmentStore:
    """For the automated tests. Starts with NO administrator setting, so the .env value (normally empty) applies."""

    default_months = None       # tests start with no waiting period unless they set one

    def __init__(self, user_store=None, months=None):
        self._user_store = user_store
        self._months = months
        self._rows = []

    def get_months(self):
        return self._months

    def set_months(self, months, admin_user_id, now):
        self._months = int(months)

    def add_request(self, user_id, reason, now):
        if self._user_store is not None and self._user_store.find_by_id(user_id) is None:
            raise UnknownUserError(user_id)
        row = {"request_id": len(self._rows) + 1, "user_id": user_id, "reason": reason, "status": "pending",
               "requested_at": now, "decided_at": None, "decided_by": None}
        self._rows.append(row)
        return row["request_id"]

    def get(self, request_id):
        row = next((r for r in self._rows if r["request_id"] == request_id), None)
        return None if row is None else _clean(row)

    def latest_for(self, user_id):
        rows = self._sorted([r for r in self._rows if r["user_id"] == user_id])
        return _clean(rows[0]) if rows else None

    def list(self, status=None):
        return [_clean(r) for r in self._sorted([r for r in self._rows if status is None or r["status"] == status])]

    def decide(self, request_id, status, admin_user_id, now):
        row = next((r for r in self._rows if r["request_id"] == request_id), None)
        if row is None or row["status"] != "pending":
            return False
        row.update(status=status, decided_at=now, decided_by=admin_user_id)
        return True

    def close_pending(self, user_id, now):
        count = 0
        for row in self._rows:
            if row["user_id"] == user_id and row["status"] == "pending":
                row.update(status="closed", decided_at=now)
                count += 1
        return count

    @staticmethod
    def _sorted(rows):
        return sorted(rows, key=lambda r: (r["requested_at"], r["request_id"]), reverse=True)
