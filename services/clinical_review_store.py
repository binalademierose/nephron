"""
clinical_review_store.py - saving and reading clinical_reviews rows (the SQL for that table lives only here).

Same MySQL + Memory pattern as the other stores. Append-only on purpose (see the migration's own comment): there is
no update or delete here, only add_review() and the two ways to read them back. Business rules (who may write one -
only a professional currently authorized for the assessment's owner) live in services/clinical_reviews.py, NOT here.
"""
import mysql.connector
from flask import current_app

import db

MAX_NOTE_LENGTH = 2000


class UnknownAssessmentError(Exception):
    """A review was offered for an assessment that does not exist."""


def get_clinical_review_store():
    return current_app.extensions["clinical_review_store"]


def _clean(row):
    return {
        "review_id": row["review_id"],
        "assessment_id": row["assessment_id"],
        "professional_user_id": row.get("professional_user_id"),
        "professional_name": row["professional_name"],
        "profession_title": row.get("profession_title"),
        "note": row["note"],
        "created_at": row["created_at"],
    }


class MySQLClinicalReviewStore:
    def add_review(self, assessment_id, professional_user_id, professional_name, profession_title, note, created_at):
        """Returns the new review_id. Raises UnknownAssessmentError if the assessment does not exist."""
        try:
            with db.transaction() as cursor:
                cursor.execute(
                    "INSERT INTO clinical_reviews (assessment_id, professional_user_id, professional_name, profession_title, "
                    "note, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                    (assessment_id, professional_user_id, professional_name, profession_title, note, created_at),
                )
                return cursor.lastrowid
        except mysql.connector.IntegrityError as error:
            if error.errno == 1452:
                raise UnknownAssessmentError(assessment_id) from error
            raise

    def list_for_assessment(self, assessment_id):
        """Every review of ONE assessment, oldest first (a running conversation, read top to bottom)."""
        rows = db.query_all(
            "SELECT review_id, assessment_id, professional_user_id, professional_name, profession_title, note, created_at "
            "FROM clinical_reviews WHERE assessment_id = %s ORDER BY created_at ASC, review_id ASC",
            (assessment_id,),
        )
        return [_clean(row) for row in rows]

    def list_for_assessments(self, assessment_ids):
        """{assessment_id: [reviews]} for a whole batch at once (a history page showing several results)."""
        if not assessment_ids:
            return {}
        placeholders = ", ".join(["%s"] * len(assessment_ids))
        rows = db.query_all(
            f"SELECT review_id, assessment_id, professional_user_id, professional_name, profession_title, note, created_at "
            f"FROM clinical_reviews WHERE assessment_id IN ({placeholders}) ORDER BY created_at ASC, review_id ASC",
            tuple(assessment_ids),
        )
        by_assessment = {assessment_id: [] for assessment_id in assessment_ids}
        for row in rows:
            by_assessment[row["assessment_id"]].append(_clean(row))
        return by_assessment


class MemoryClinicalReviewStore:
    """The same methods, kept in memory. It asks the assessment store whether each assessment exists, like the
    foreign key does."""

    def __init__(self, assessment_store):
        self._assessment_store = assessment_store
        self._rows = []
        self._next_id = 1

    def _assessment_exists(self, assessment_id):
        # The assessment store is scoped by user_id, so a direct existence check needs its own small back door:
        # every in-memory assessment row is kept on the store itself for exactly this.
        return any(row["assessment_id"] == assessment_id for row in getattr(self._assessment_store, "_rows", []))

    def add_review(self, assessment_id, professional_user_id, professional_name, profession_title, note, created_at):
        if not self._assessment_exists(assessment_id):
            raise UnknownAssessmentError(assessment_id)
        row = {"review_id": self._next_id, "assessment_id": assessment_id, "professional_user_id": professional_user_id,
              "professional_name": professional_name, "profession_title": profession_title, "note": note, "created_at": created_at}
        self._next_id += 1
        self._rows.append(row)
        return row["review_id"]

    def list_for_assessment(self, assessment_id):
        mine = [row for row in self._rows if row["assessment_id"] == assessment_id]
        mine.sort(key=lambda row: (row["created_at"], row["review_id"]))
        return [_clean(row) for row in mine]

    def list_for_assessments(self, assessment_ids):
        by_assessment = {assessment_id: [] for assessment_id in assessment_ids}
        for row in sorted(self._rows, key=lambda row: (row["created_at"], row["review_id"])):
            if row["assessment_id"] in by_assessment:
                by_assessment[row["assessment_id"]].append(_clean(row))
        return by_assessment
