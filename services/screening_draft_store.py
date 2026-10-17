"""
screening_draft_store.py - saving and reading an unfinished screening's answers.

Same MySQL + Memory pattern as the other stores. One row per (user_id, assessment_type): save_draft() is an
UPSERT (see the migration's own comment) - starting over, or simply continuing to type, always updates the SAME
row rather than creating another one. Business rules (turning saved JSON back into form values, deciding when a
draft counts as "in progress" enough to show on the dashboard) live in services/screening_drafts.py, NOT here.
"""
import json

import mysql.connector
from flask import current_app

import db


def get_screening_draft_store():
    return current_app.extensions["screening_draft_store"]


def _clean(row):
    return {
        "draft_id": row["draft_id"],
        "user_id": row["user_id"],
        "assessment_type": row["assessment_type"],
        "answers": json.loads(row["answers_json"]),
        "current_step": row.get("current_step"),
        "updated_at": row["updated_at"],
    }


class MySQLScreeningDraftStore:
    def save_draft(self, user_id, assessment_type, answers, current_step, now):
        answers_json = json.dumps(answers)
        db.execute(
            "INSERT INTO screening_drafts (user_id, assessment_type, answers_json, current_step, updated_at) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE answers_json = VALUES(answers_json), current_step = VALUES(current_step), updated_at = VALUES(updated_at)",
            (user_id, assessment_type, answers_json, current_step, now),
        )

    def get_draft(self, user_id, assessment_type):
        row = db.query_one(
            "SELECT draft_id, user_id, assessment_type, answers_json, current_step, updated_at "
            "FROM screening_drafts WHERE user_id = %s AND assessment_type = %s",
            (user_id, assessment_type),
        )
        return None if row is None else _clean(row)

    def list_drafts(self, user_id):
        """All of this person's own open drafts (never more than one per type), newest first."""
        rows = db.query_all(
            "SELECT draft_id, user_id, assessment_type, answers_json, current_step, updated_at "
            "FROM screening_drafts WHERE user_id = %s ORDER BY updated_at DESC",
            (user_id,),
        )
        return [_clean(row) for row in rows]

    def discard_draft(self, user_id, assessment_type):
        """True if a draft existed and was removed."""
        with db.transaction() as cursor:
            cursor.execute("DELETE FROM screening_drafts WHERE user_id = %s AND assessment_type = %s", (user_id, assessment_type))
            return cursor.rowcount > 0


class MemoryScreeningDraftStore:
    def __init__(self):
        self._rows = {}          # (user_id, assessment_type) -> row
        self._next_id = 1

    def save_draft(self, user_id, assessment_type, answers, current_step, now):
        key = (user_id, assessment_type)
        row = self._rows.get(key)
        if row is None:
            row = {"draft_id": self._next_id, "user_id": user_id, "assessment_type": assessment_type}
            self._next_id += 1
            self._rows[key] = row
        row["answers_json"] = json.dumps(answers)
        row["current_step"] = current_step
        row["updated_at"] = now

    def get_draft(self, user_id, assessment_type):
        row = self._rows.get((user_id, assessment_type))
        return None if row is None else _clean(row)

    def list_drafts(self, user_id):
        mine = [row for (uid, _type), row in self._rows.items() if uid == user_id]
        mine.sort(key=lambda row: row["updated_at"], reverse=True)
        return [_clean(row) for row in mine]

    def discard_draft(self, user_id, assessment_type):
        return self._rows.pop((user_id, assessment_type), None) is not None
