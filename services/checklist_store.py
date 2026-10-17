"""
checklist_store.py - which of a person's own kidney-health tips they have marked complete TODAY (the list resets each day).

A tip's own text, category and source always come fresh from services/kidney_tips.py; this only ever stores the
completed/not-completed state, keyed by the tip's stable id string, so improving a tip's wording later never
loses anyone's progress. Toggling is an upsert-or-delete: marking complete inserts a row (or leaves it, if
already there); marking incomplete simply deletes the row - there is no "completed: false" row to keep in sync.
"""
from datetime import date

import mysql.connector
from flask import current_app

import db


def get_checklist_store():
    return current_app.extensions["checklist_store"]


class MySQLChecklistStore:
    """One row per tip per DAY (migration 017): the checklist starts fresh every day. day is a local date; it
    defaults to today when a caller does not say."""

    def completed_tip_ids(self, user_id, day=None):
        rows = db.query_all("SELECT tip_id FROM checklist_daily WHERE user_id = %s AND completed_on = %s", (user_id, day or date.today()))
        return {row["tip_id"] for row in rows}

    def mark_complete(self, user_id, tip_id, now, day=None):
        db.execute(
            "INSERT INTO checklist_daily (user_id, tip_id, completed_on, completed_at) VALUES (%s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE completed_at = VALUES(completed_at)",
            (user_id, tip_id, day or date.today(), now),
        )

    def mark_incomplete(self, user_id, tip_id, day=None):
        with db.transaction() as cursor:
            cursor.execute("DELETE FROM checklist_daily WHERE user_id = %s AND tip_id = %s AND completed_on = %s",
                           (user_id, tip_id, day or date.today()))
            return cursor.rowcount > 0


class MemoryChecklistStore:
    def __init__(self):
        self._done = {}          # (user_id, day) -> set of tip_id

    def completed_tip_ids(self, user_id, day=None):
        return set(self._done.get((user_id, day or date.today()), set()))

    def mark_complete(self, user_id, tip_id, now, day=None):
        self._done.setdefault((user_id, day or date.today()), set()).add(tip_id)

    def mark_incomplete(self, user_id, tip_id, day=None):
        key = (user_id, day or date.today())
        had_it = tip_id in self._done.get(key, set())
        self._done.get(key, set()).discard(tip_id)
        return had_it
