"""
research_export.py - de-identified screening data, for improving the model with real-world data later.

Nephron's models were trained on SYNTHETIC datasets. Every valid screening people complete is real data, so the
administrator can download them as a CSV - PREDICTORS ONLY (the model's own input columns), de-identified:

  - no name, email, username, id, assessment number, date or time;
  - no gender, address or location (not predictors, and they would help re-identify someone);
  - no result, probability or threshold (the model's own guess is not a fact to learn from);
  - Age at or above 90 is written as 90 (the usual de-identification rule for very old ages);
  - rows are shuffled, so their order says nothing about who screened when;
  - by default only each person's LATEST screening, so one person does not appear many times.

A screening only exists if every answer passed the website's own checks (services/screening_contract.py), so every
row is a valid set of answers. To retrain a model, each row would still need a CONFIRMED outcome (for example a
doctor's diagnosis); this file deliberately has none, and the page says so.
"""
import csv
import io
import secrets

AGE_CAP = 90
TYPES = {"preliminary": "Preliminary Screening", "enhanced": "Enhanced Screening"}


def columns(assessment_type, stage2_service=None):
    """The predictor columns, in the model's own order."""
    if assessment_type == "preliminary":
        from services import screening_contract
        return screening_contract.feature_names(screening_contract.load_catalog())
    meta = getattr(stage2_service, "metadata", None) or {}
    if meta.get("features"):
        return list(meta["features"])
    from services import lab_contract
    from services.model_service_stage2 import STAGE1_LIKE_FIELDS
    return list(STAGE1_LIKE_FIELDS) + [f["name"] for f in lab_contract.load_lab_catalog()["fields"]] + ["eGFR"]


def _cell(name, value):
    if value is None:
        return ""
    if name == "Age" and isinstance(value, (int, float)) and value >= AGE_CAP:
        return AGE_CAP
    return value


def rows(store, assessment_type, cols, latest_only=True):
    """The de-identified rows: predictors only, shuffled."""
    out = [[_cell(name, answers.get(name)) for name in cols] for answers in store.saved_answers(assessment_type, latest_only)]
    secrets.SystemRandom().shuffle(out)
    return out


def to_csv(cols, data):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(cols)
    writer.writerows(data)
    return buffer.getvalue()
