"""
report_routes.py - a downloadable PDF: one specific assessment, or the whole history, with an explicit choice of
whether to include clinical review notes. Two audiences, same underlying services/reports.py + pdf_report.py:

  Patient (role 'general'):
    GET  /reports                       choose what to download
    POST /reports/download              the PDF itself

  Professional (role 'professional'), for an authorized patient:
    POST /patients/<id>/reports/download the same choice, answered from the patient_history page's own form
"""
from flask import Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request, url_for

from routes.decorators import role_required
from services import assessments, authorizations, clock, reports
from services.assessment_store import get_assessment_store
from services.authorization_store import get_authorization_store
from services.clinical_review_store import get_clinical_review_store
from services.pdf_report import build_assessment_report, build_history_report
from services.user_store import get_user_store

reports_bp = Blueprint("reports", __name__)


def _pdf_response(pdf_bytes, filename):
    return Response(pdf_bytes, mimetype="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ------------------------------------------------------------------ patient side
@reports_bp.route("/reports")
@role_required("general")
def patient_reports():
    zone = current_app.config["APP_TIMEZONE"]
    records = assessments.load_records(get_assessment_store(), g.user["user_id"], zone)
    return render_template("reports/select.html", page_title="Reports", records=records)


@reports_bp.route("/reports/download", methods=["POST"])
@role_required("general")
def download_patient_report():
    zone = current_app.config["APP_TIMEZONE"]
    include_reviews = request.form.get("include_reviews") == "on"
    review_store = get_clinical_review_store()
    if request.form.get("report_type") == "history":
        records = assessments.load_records(get_assessment_store(), g.user["user_id"], zone)
        data = reports.history_report_data(records, g.user["full_name"], g.user["email"], zone, include_reviews, review_store)
        return _pdf_response(build_history_report(data), "nephron-history-report.pdf")

    try:
        assessment_id = int(request.form.get("assessment_id", ""))
    except ValueError:
        abort(400)
    row = get_assessment_store().get_assessment(g.user["user_id"], assessment_id)
    if row is None:
        abort(404)
    data = reports.assessment_report_data(row, g.user["full_name"], g.user["email"], zone, include_reviews, review_store)
    return _pdf_response(build_assessment_report(data), f"nephron-report-{data['record']['date_text'].replace(' ', '-').replace(',', '')}.pdf")


# ------------------------------------------------------------------ professional side, for their own patient records
@reports_bp.route("/patient-records/<patient_code>/reports/download", methods=["POST"])
@role_required("professional")
def download_patient_record_report(patient_code):
    from services.patient_records_store import get_patient_records_store
    record = get_patient_records_store().get_by_code(patient_code)
    if record is None or record["professional_user_id"] != g.user["user_id"]:
        abort(404)                                       # not this professional's own patient: answered like it does not exist
    patient_user_id = record["user_id"]
    zone = current_app.config["APP_TIMEZONE"]
    include_reviews = request.form.get("include_reviews") == "on"
    review_store = get_clinical_review_store()
    if request.form.get("report_type") == "history":
        records = assessments.load_records(get_assessment_store(), patient_user_id, zone)
        data = reports.history_report_data(records, record["full_name"], record["patient_code"], zone, include_reviews, review_store)
        return _pdf_response(build_history_report(data), f"nephron-history-report-{patient_code}.pdf")

    try:
        assessment_id = int(request.form.get("assessment_id", ""))
    except ValueError:
        abort(400)
    row = get_assessment_store().get_assessment(patient_user_id, assessment_id)
    if row is None:
        abort(404)
    data = reports.assessment_report_data(row, record["full_name"], record["patient_code"], zone, include_reviews, review_store)
    return _pdf_response(build_assessment_report(data), f"nephron-report-{data['record']['date_text'].replace(' ', '-').replace(',', '')}.pdf")


@reports_bp.route("/patients/<int:patient_id>/reports/download", methods=["POST"])
@role_required("professional")
def download_patient_report_for_professional(patient_id):
    auth_store, user_store = get_authorization_store(), get_user_store()
    if not authorizations.is_authorized(auth_store, patient_id, g.user["user_id"]):
        abort(404)
    patient = user_store.find_by_id(patient_id)
    if patient is None:
        abort(404)
    zone = current_app.config["APP_TIMEZONE"]
    include_reviews = request.form.get("include_reviews") == "on"
    review_store = get_clinical_review_store()
    if request.form.get("report_type") == "history":
        records = assessments.load_records(get_assessment_store(), patient_id, zone)
        data = reports.history_report_data(records, patient["full_name"], patient["email"], zone, include_reviews, review_store)
        return _pdf_response(build_history_report(data), "nephron-history-report.pdf")

    try:
        assessment_id = int(request.form.get("assessment_id", ""))
    except ValueError:
        abort(400)
    row = get_assessment_store().get_assessment(patient_id, assessment_id)
    if row is None:
        abort(404)
    data = reports.assessment_report_data(row, patient["full_name"], patient["email"], zone, include_reviews, review_store)
    return _pdf_response(build_assessment_report(data), f"nephron-report-{data['record']['date_text'].replace(' ', '-').replace(',', '')}.pdf")
