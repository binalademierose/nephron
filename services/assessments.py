"""
assessments.py - the rules for saved assessments, and turning stored rows into what the dashboard draws.

An assessment is one screening result: the model's predicted probability, the low/high classification it gave, and
which model and threshold produced them. Phase 4 (the screening itself) calls record_assessment() to save one. The
dashboard calls load_records() to read a person's own assessments. Nothing here invents a value.
"""
import json
import math
from datetime import datetime

from services import clock

ASSESSMENT_TYPES = ("preliminary", "enhanced")
TYPE_LABELS = {"preliminary": "Preliminary screening", "enhanced": "Enhanced screening"}
CLASSIFICATIONS = ("low", "high")


def _is_fraction(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1


def validate_assessment(values):
    """Raise ValueError (with a plain sentence) if a result to be saved makes no sense. Returns nothing when fine."""
    if values.get("assessment_type") not in ASSESSMENT_TYPES:
        raise ValueError(f"assessment_type must be one of {ASSESSMENT_TYPES}")
    if values.get("classification") not in CLASSIFICATIONS:
        raise ValueError(f"classification must be one of {CLASSIFICATIONS}")
    if not _is_fraction(values.get("probability")):
        raise ValueError("probability must be a number from 0 to 1 (0.31 means 31 percent)")
    threshold = values.get("threshold_used")
    if threshold is not None and not _is_fraction(threshold):
        raise ValueError("threshold_used must be a number from 0 to 1, or left out")
    version = values.get("model_version")
    if version is not None and (not isinstance(version, str) or not version or len(version) > 100):
        raise ValueError("model_version must be text of up to 100 characters, or left out")
    if not isinstance(values.get("assessed_at"), datetime):
        raise ValueError("assessed_at must be a date and time")
    source_id = values.get("source_assessment_id")
    if source_id is not None and (isinstance(source_id, bool) or not isinstance(source_id, int) or source_id < 1):
        raise ValueError("source_assessment_id must be a positive whole number, or left out")
    if values.get("assessment_type") == "enhanced" and source_id is None:
        raise ValueError("an 'enhanced' assessment must record which 'preliminary' assessment it extends (source_assessment_id)")


MAX_INPUTS_BYTES = 20_000


def validate_inputs(inputs):
    """The saved answers must be a plain dictionary of names and simple values, of a sensible size. ValueError if not."""
    if not isinstance(inputs, dict) or not inputs:
        raise ValueError("inputs must be a dictionary of the answers that were used")
    for name, value in inputs.items():
        if not isinstance(name, str) or isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError(f"input '{name}' must be text or a number")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"input '{name}' is not a real number")
    if len(json.dumps(inputs)) > MAX_INPUTS_BYTES:
        raise ValueError("inputs are too large")


def record_assessment(store, user_id, values, inputs=None):
    """
    Check a result (and the answers behind it, if given) and save them as a new permanent row.
    Returns the new assessment_id. Nothing is saved if anything is wrong.
    """
    validate_assessment(values)
    if inputs is not None:
        validate_inputs(inputs)
    return store.add_assessment(user_id, values, inputs)


def to_record(row, timezone_name):
    """One stored row in the shape services/visuals.py expects (probability and threshold as percentages, local date)."""
    threshold = row["threshold_used"]
    return {
        "assessment_id": row["assessment_id"],
        "assessment_type": row["assessment_type"],
        "source_assessment_id": row.get("source_assessment_id"),
        "date": clock.to_local_date(row["assessed_at"], timezone_name),
        "type": TYPE_LABELS[row["assessment_type"]],
        "probability": round(row["probability"] * 100, 4),
        "level": row["classification"],
        "threshold": None if threshold is None else round(threshold * 100, 4),
        "model_version": row["model_version"],
    }


def load_records(store, user_id, timezone_name):
    """
    A person's own assessments, newest first, ready for the dashboard's charts.
    Only THIS user's rows are ever asked for.
    """
    return [to_record(row, timezone_name) for row in store.list_assessments(user_id)]
