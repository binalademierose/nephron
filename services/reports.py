"""
reports.py - gathers everything a downloadable PDF needs, in the exact shape services/pdf_report.py expects.

This is the ONLY place that decides what a report may contain: the same "only explain a result the running model
actually produced" rule as the result page (services/explanations.py), and clinical review notes are included only
when the caller says include_reviews=True - the person generating the report chooses that, every time, never a
standing preference.
"""
from flask import current_app

from services import assessments, clinical_reviews, clock, explanations, lab_contract, screening_contract, visuals

WHAT_THIS_MEANS = {
    "high": "Higher-risk group. This is screening information, not a diagnosis. Consider professional evaluation.",
    "low": "Lower-risk group. It does not mean you are free of kidney disease.",
}


def _describe_assessment(row):
    """(model, describer, answers) for one saved assessment row - the same rule screening_routes.result() uses:
    which model and catalog apply depends on whether it was a preliminary or an enhanced assessment."""
    if row["assessment_type"] == "enhanced":
        from services.model_service_stage2 import stage2_describer

        model = current_app.extensions["model_service_stage2"]
        lab_catalog = lab_contract.load_lab_catalog()
        describer = stage2_describer(lab_catalog)
        stage1_answers = screening_contract.describe_inputs(current_app.extensions["catalog"], row["inputs"]) if row["inputs"] else []
        lab_answers = lab_contract.describe_lab_values(lab_catalog, row["inputs"]) if row["inputs"] else []
        answers = stage1_answers + lab_answers
    else:
        model = current_app.extensions["model_service"]
        describer = current_app.extensions["catalog"]
        answers = screening_contract.describe_inputs(current_app.extensions["catalog"], row["inputs"]) if row["inputs"] else []
    return model, describer, answers


def _factor_lines(effects):
    return [f"{e['label']}: {e['answer']}" for e in effects]


def assessment_report_data(row, patient_name, patient_email, timezone_name, include_reviews, review_store=None):
    """Everything build_assessment_report() needs for one saved assessment row (as returned by
    assessment_store.get_assessment - it already belongs to the right person; this function does not check that)."""
    record = assessments.to_record(row, timezone_name)
    model, describer, answers = _describe_assessment(row)
    explanation = explanations.explain_saved_result(model, describer, row)
    reviews = []
    if include_reviews and review_store is not None:
        reviews = [dict(r, date=clock.to_local_date(r["created_at"], timezone_name))
                  for r in clinical_reviews.for_assessment(review_store, row["assessment_id"])]
    now_local = clock.to_local_date(clock.now_utc(), timezone_name)
    return {
        "patient_name": patient_name,
        "patient_email": patient_email,
        "generated_at_text": f"{now_local:%b} {now_local.day}, {now_local.year}",
        "record": {
            "date_text": visuals.format_date(record["date"]),
            "type": record["type"],
            "probability_text": f"{visuals.percent_text(record['probability'])}%",
            "classification": record["level"],
            "classification_text": visuals.level_label(record["level"], record["assessment_type"]),
            "threshold_text": f"Validated threshold: {visuals.percent_text(record['threshold'])}%" if record["threshold"] is not None else "",
            "what_this_means": WHAT_THIS_MEANS[record["level"]],
        },
        "answers": answers,
        "factors_up": _factor_lines(explanation["raises"]) if explanation else [],
        "factors_down": _factor_lines(explanation["lowers"]) if explanation else [],
        "reviews": reviews,
        "disclaimer": current_app.config["MEDICAL_DISCLAIMER"],
    }


def history_report_data(records, patient_name, patient_email, timezone_name, include_reviews, review_store=None):
    """records: assessments.load_records()'s own output (newest first) for one person."""
    rows = [{
        "assessment_id": r["assessment_id"],
        "date_text": visuals.format_date(r["date"]),
        "type": r["type"],
        "probability_text": f"{visuals.percent_text(r['probability'])}%",
        "classification": r["level"],
        "classification_text": visuals.level_label(r["level"], r["assessment_type"]),
    } for r in records]
    reviews_by_assessment = {}
    if include_reviews and review_store is not None and records:
        raw = clinical_reviews.for_assessments(review_store, [r["assessment_id"] for r in records])
        reviews_by_assessment = {assessment_id: [dict(review, date=clock.to_local_date(review["created_at"], timezone_name))
                                                 for review in reviews] for assessment_id, reviews in raw.items()}
    now_local = clock.to_local_date(clock.now_utc(), timezone_name)
    return {
        "patient_name": patient_name,
        "patient_email": patient_email,
        "generated_at_text": f"{now_local:%b} {now_local.day}, {now_local.year}",
        "rows": rows,
        "reviews_by_assessment": reviews_by_assessment,
        "disclaimer": current_app.config["MEDICAL_DISCLAIMER"],
    }
