"""
assessment_store.py - saving and reading assessments (the SQL for the `assessments` table lives only here).

Like user_store.py there are two stores with the same methods: MySQLAssessmentStore (the real one) and
MemoryAssessmentStore (for tests). tests/test_assessment_store.py runs the same checks against both.

An assessment row is a dictionary with: assessment_id, assessment_type, probability (a fraction 0 to 1),
classification, threshold_used (a fraction, or None), model_version (or None), assessed_at (UTC).
get_assessment() also gives `inputs`: the saved answers (a dictionary), or None if none were saved.
"""
import json

import mysql.connector
from flask import current_app

import db

MYSQL_FOREIGN_KEY_FAILED = 1452     # MySQL's error number for "that user does not exist"
PRECISION = 6                       # the column keeps six decimals, so both stores round to six


class UnknownUserError(Exception):
    """An assessment was offered for a user that does not exist."""


def get_assessment_store():
    return current_app.extensions["assessment_store"]


def _clean(row):
    """MySQL gives DECIMAL values as Decimal; the rest of Nephron works with plain floats."""
    return {
        "assessment_id": row["assessment_id"],
        "assessment_type": row["assessment_type"],
        "source_assessment_id": row.get("source_assessment_id"),
        "probability": float(row["probability"]),
        "classification": row["classification"],
        "threshold_used": None if row["threshold_used"] is None else float(row["threshold_used"]),
        "model_version": row["model_version"],
        "assessed_at": row["assessed_at"],
    }


def _age_only(raw_inputs):
    """The Age from saved answers (JSON text or bytes), or None - and nothing else from them."""
    if raw_inputs is None:
        return None
    if isinstance(raw_inputs, (bytes, bytearray)):
        raw_inputs = raw_inputs.decode("utf-8")
    try:
        age = json.loads(raw_inputs).get("Age")
    except (ValueError, AttributeError):
        return None
    return age if isinstance(age, (int, float)) and not isinstance(age, bool) else None


def _profile_only(raw_inputs):
    """{"age", "country", "gender"} from saved answers, and nothing else from them. Gender is the person's own
    answer; a screening saved before Gender was asked has only Sex (then Male/Female), which is used instead."""
    profile = {"age": _age_only(raw_inputs), "country": None, "gender": None}
    if raw_inputs is None:
        return profile
    if isinstance(raw_inputs, (bytes, bytearray)):
        raw_inputs = raw_inputs.decode("utf-8")
    try:
        saved = json.loads(raw_inputs)
    except ValueError:
        return profile
    if not isinstance(saved, dict):
        return profile
    text = lambda value: value if isinstance(value, str) and value else None      # noqa: E731
    profile["country"] = text(saved.get("Country"))
    profile["gender"] = text(saved.get("Gender")) or text(saved.get("Sex"))
    return profile


def _answers(raw_inputs):
    """Saved answers (JSON text or bytes) as a dict, or None."""
    if raw_inputs is None:
        return None
    if isinstance(raw_inputs, (bytes, bytearray)):
        raw_inputs = raw_inputs.decode("utf-8")
    try:
        answers = json.loads(raw_inputs)
    except ValueError:
        return None
    return answers if isinstance(answers, dict) else None


def _clean_with_inputs(row, raw_inputs):
    assessment = _clean(row)
    if isinstance(raw_inputs, (bytes, bytearray)):
        raw_inputs = raw_inputs.decode("utf-8")
    assessment["inputs"] = None if raw_inputs is None else json.loads(raw_inputs)
    return assessment


class MySQLAssessmentStore:
    def add_assessment(self, user_id, values, inputs=None):
        """Save the result, and the answers behind it if given, together or not at all. Returns the new assessment_id.
        values may include source_assessment_id: for an 'enhanced' assessment, the 'preliminary' one it extends."""
        try:
            with db.transaction() as cursor:
                cursor.execute(
                    "INSERT INTO assessments (user_id, assessment_type, source_assessment_id, probability, classification, "
                    "threshold_used, model_version, assessed_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (user_id, values["assessment_type"], values.get("source_assessment_id"), round(values["probability"], PRECISION),
                     values["classification"], None if values.get("threshold_used") is None else round(values["threshold_used"], PRECISION),
                     values.get("model_version"), values["assessed_at"]),
                )
                assessment_id = cursor.lastrowid
                if inputs is not None:
                    cursor.execute("INSERT INTO assessment_inputs (assessment_id, inputs) VALUES (%s, %s)",
                                   (assessment_id, json.dumps(inputs, sort_keys=True)))
        except mysql.connector.IntegrityError as error:
            if error.errno == MYSQL_FOREIGN_KEY_FAILED:
                raise UnknownUserError(user_id) from error
            raise
        return assessment_id

    def get_assessment(self, user_id, assessment_id):
        """One assessment with its saved answers, but only if it belongs to THIS user (otherwise None, as if it did not exist)."""
        row = db.query_one(
            "SELECT a.assessment_id, a.assessment_type, a.source_assessment_id, a.probability, a.classification, "
            "a.threshold_used, a.model_version, a.assessed_at, i.inputs AS saved_inputs FROM assessments AS a "
            "LEFT JOIN assessment_inputs AS i ON i.assessment_id = a.assessment_id "
            "WHERE a.assessment_id = %s AND a.user_id = %s",
            (assessment_id, user_id),
        )
        return None if row is None else _clean_with_inputs(row, row["saved_inputs"])

    def find_owner(self, assessment_id):
        """Just the user_id an assessment id belongs to, or None - for a search feature that needs to know WHO
        an id belongs to before deciding whether the person asking may see it. Never returns the assessment
        itself: that ownership check is the caller's job, exactly like get_assessment()'s own WHERE clause."""
        row = db.query_one("SELECT user_id FROM assessments WHERE assessment_id = %s", (assessment_id,))
        return None if row is None else row["user_id"]

    def latest_per_person(self):
        """[(classification, age or None), ...] - each person's MOST RECENT result, with only their age kept from
        its answers. Deliberately anonymous: no id, no name, no other answer leaves this method (admin KPIs)."""
        return [(profile["level"], profile["age"]) for profile in self.latest_profiles()]

    def saved_answers(self, assessment_type, latest_only=True):
        """[answers dict, ...] of every saved screening of one type (or each person's latest one) - the answers ONLY:
        no id, no date, no result. For the de-identified research export (services/research_export.py)."""
        if latest_only:
            rows = db.query_all(
                "SELECT ai.inputs FROM assessments AS a "
                "JOIN (SELECT user_id, MAX(assessment_id) AS latest_id FROM assessments WHERE assessment_type = %s GROUP BY user_id) AS l "
                "ON l.latest_id = a.assessment_id JOIN assessment_inputs AS ai ON ai.assessment_id = a.assessment_id", (assessment_type,))
        else:
            rows = db.query_all("SELECT ai.inputs FROM assessments AS a JOIN assessment_inputs AS ai ON ai.assessment_id = a.assessment_id "
                                "WHERE a.assessment_type = %s", (assessment_type,))
        return [_answers(row["inputs"]) for row in rows if _answers(row["inputs"])]

    def latest_levels(self):
        """{user_id: classification} of each person's MOST RECENT result - only the level, for the area heatmap,
        which joins it to a place and then drops the id (services/location_heatmap.py)."""
        rows = db.query_all(
            "SELECT a.user_id, a.classification FROM assessments AS a "
            "JOIN (SELECT user_id, MAX(assessment_id) AS latest_id FROM assessments GROUP BY user_id) AS l ON l.latest_id = a.assessment_id")
        return {row["user_id"]: row["classification"] for row in rows}

    def latest_profiles(self):
        """[{"level", "age", "country", "gender"}, ...] - each person's MOST RECENT result with only those three
        answers kept. Anonymous by design: no id, no name, no date, no other answer (services/community_stats.py)."""
        rows = db.query_all(
            "SELECT a.classification, ai.inputs FROM assessments AS a "
            "JOIN (SELECT user_id, MAX(assessment_id) AS latest_id FROM assessments GROUP BY user_id) AS l "
            "ON l.latest_id = a.assessment_id LEFT JOIN assessment_inputs AS ai ON ai.assessment_id = a.assessment_id")
        return [{"level": row["classification"], **_profile_only(row["inputs"])} for row in rows]

    def totals(self, since):
        """System-wide COUNTS only, for the administrator: [(assessment_type, classification, all-time count,
        count since `since`)]. Never a person, a probability, or an answer - just how many."""
        rows = db.query_all(
            "SELECT assessment_type, classification, COUNT(*) AS total, SUM(assessed_at >= %s) AS recent "
            "FROM assessments GROUP BY assessment_type, classification", (since,))
        return [(r["assessment_type"], r["classification"], int(r["total"]), int(r["recent"] or 0)) for r in rows]

    def list_assessments(self, user_id):
        """This user's assessments, newest first. The user_id in the WHERE is what keeps one person's data from another."""
        rows = db.query_all(
            "SELECT assessment_id, assessment_type, source_assessment_id, probability, classification, threshold_used, "
            "model_version, assessed_at FROM assessments WHERE user_id = %s ORDER BY assessed_at DESC, assessment_id DESC",
            (user_id,),
        )
        return [_clean(row) for row in rows]


class MemoryAssessmentStore:
    """The same methods, kept in memory. It asks the user store whether the user exists, like the foreign key does."""

    def __init__(self, user_store):
        self._user_store = user_store
        self._rows = []
        self._next_id = 1

    def latest_per_person(self):
        return [(profile["level"], profile["age"]) for profile in self.latest_profiles()]

    def saved_answers(self, assessment_type, latest_only=True):
        rows = [r for r in self._rows if r["assessment_type"] == assessment_type and r.get("inputs")]
        if latest_only:
            latest = {}
            for row in rows:
                if row["user_id"] not in latest or row["assessment_id"] > latest[row["user_id"]]["assessment_id"]:
                    latest[row["user_id"]] = row
            rows = list(latest.values())
        return [_answers(row["inputs"]) for row in rows if _answers(row["inputs"])]

    def latest_levels(self):
        latest = {}
        for row in self._rows:
            if row["user_id"] not in latest or row["assessment_id"] > latest[row["user_id"]]["assessment_id"]:
                latest[row["user_id"]] = row
        return {user_id: row["classification"] for user_id, row in latest.items()}

    def latest_profiles(self):
        latest = {}
        for row in self._rows:
            if row["user_id"] not in latest or row["assessment_id"] > latest[row["user_id"]]["assessment_id"]:
                latest[row["user_id"]] = row
        return [{"level": row["classification"], **_profile_only(row.get("inputs"))} for row in latest.values()]

    def totals(self, since):
        counts = {}
        for row in self._rows:
            key = (row["assessment_type"], row["classification"])
            total, recent = counts.get(key, (0, 0))
            counts[key] = (total + 1, recent + (1 if row["assessed_at"] >= since else 0))
        return [(kind, level, total, recent) for (kind, level), (total, recent) in counts.items()]

    def add_assessment(self, user_id, values, inputs=None):
        if self._user_store.find_by_id(user_id) is None:
            raise UnknownUserError(user_id)
        threshold = values.get("threshold_used")
        row = {
            "assessment_id": self._next_id, "user_id": user_id, "assessment_type": values["assessment_type"],
            "source_assessment_id": values.get("source_assessment_id"),
            "probability": round(values["probability"], PRECISION), "classification": values["classification"],
            "threshold_used": None if threshold is None else round(threshold, PRECISION),
            "model_version": values.get("model_version"), "assessed_at": values["assessed_at"],
            "inputs": None if inputs is None else json.dumps(inputs, sort_keys=True),
        }
        self._next_id += 1
        self._rows.append(row)
        return row["assessment_id"]

    def get_assessment(self, user_id, assessment_id):
        for row in self._rows:
            if row["assessment_id"] == assessment_id and row["user_id"] == user_id:
                return _clean_with_inputs(row, row["inputs"])
        return None

    def find_owner(self, assessment_id):
        for row in self._rows:
            if row["assessment_id"] == assessment_id:
                return row["user_id"]
        return None

    def list_assessments(self, user_id):
        mine = [row for row in self._rows if row["user_id"] == user_id]
        mine.sort(key=lambda row: (row["assessed_at"], row["assessment_id"]), reverse=True)
        return [_clean(row) for row in mine]
