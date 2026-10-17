"""
patient_records_routes.py - a professional's own patients (see migration 015 and services/patient_records.py for
what a "patient record" is and why it is not the same thing as an authorized General User).

A professional can register a new patient, see their own patient list, open a patient's profile, and perform a
Preliminary screening on that patient's behalf - the SAME validation and model used everywhere else
(services/screening_contract.py, the model service), just saved under the patient record's own shadow user_id
instead of the signed-in professional's. Enhanced Screening for a patient record is not built yet: the
assessment-type page says so rather than offering a form that goes nowhere.
"""
from datetime import timedelta

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from routes.decorators import role_required
from services import assessments, clock, explanations, fixed_answers, lab_contract, lab_documents, lab_ocr, lab_verification, screening_drafts, patient_records, professional_overview, screening_contract
from services.egfr import estimate_gfr
from services.model_service_stage2 import stage2_describer
from services.assessment_store import get_assessment_store
from services.authorization_store import get_authorization_store
from services.clinical_review_store import get_clinical_review_store
from services.followup_appointment_store import get_followup_appointment_store
from services.patient_records_store import get_patient_records_store
from services.screening_draft_store import get_screening_draft_store
from services.lab_document_store import get_lab_document_store
from services.user_store import get_user_store

patient_records_bp = Blueprint("patient_records", __name__)

DUPLICATE_WINDOW = timedelta(seconds=60)      # the same answers sent again within this time are the same submission


def _catalog():
    return current_app.extensions["catalog"]


def _model():
    return current_app.extensions["model_service"]


def _owned_or_404(patient_code):
    """The patient record, only if it belongs to the signed-in professional - the one check every route below
    makes before doing anything else. A code that exists but belongs to someone else is answered exactly like a
    code that does not exist at all."""
    record = get_patient_records_store().get_by_code(patient_code)
    if record is None or record["professional_user_id"] != g.user["user_id"]:
        abort(404)
    return record


@patient_records_bp.route("/assessments")
@role_required("professional")
def assessment_list():
    term = request.args.get("q", "").strip()
    risk = request.args.get("risk") or None
    period = request.args.get("period") or professional_overview.PERIOD_ALL
    valid_periods = (professional_overview.PERIOD_1_DAY, professional_overview.PERIOD_7_DAYS,
                     professional_overview.PERIOD_30_DAYS, professional_overview.PERIOD_ALL)
    if period not in valid_periods:
        period = professional_overview.PERIOD_ALL
    rows = professional_overview.assessment_list(
        get_patient_records_store(), get_authorization_store(), get_user_store(), get_assessment_store(),
        get_clinical_review_store(), g.user["user_id"], current_app.config["APP_TIMEZONE"],
        term=term, risk=risk, period=period,
    )
    return render_template("patients/assessments.html", page_title="Assessments", records=rows, query=term, risk=risk, period=period)


@patient_records_bp.route("/patient-records")
@role_required("professional")
def index():
    term = request.args.get("q", "").strip()
    risk = request.args.get("risk") or None
    category = request.args.get("category") or professional_overview.CATEGORY_ALL
    if category not in (professional_overview.CATEGORY_ALL, professional_overview.CATEGORY_PENDING,
                        professional_overview.CATEGORY_REVIEWED, professional_overview.CATEGORY_FOLLOW_UP):
        category = professional_overview.CATEGORY_ALL

    # The search term and risk filter narrow the pool the category TABS themselves count from, so a tab's number
    # always matches what choosing it would show - only the category itself is applied twice (once per tab).
    matching = professional_overview.patient_list(
        get_patient_records_store(), get_authorization_store(), get_user_store(), get_assessment_store(),
        get_clinical_review_store(), get_followup_appointment_store(), g.user["user_id"],
        current_app.config["APP_TIMEZONE"], term=term, risk=risk,
    )
    counts = {
        professional_overview.CATEGORY_ALL: len(matching),
        professional_overview.CATEGORY_PENDING: sum(1 for row in matching if row["is_pending"]),
        professional_overview.CATEGORY_REVIEWED: sum(1 for row in matching if not row["is_pending"] and row["latest"] is not None),
        professional_overview.CATEGORY_FOLLOW_UP: sum(1 for row in matching if row["has_follow_up"]),
    }
    if category == professional_overview.CATEGORY_PENDING:
        records = [row for row in matching if row["is_pending"]]
    elif category == professional_overview.CATEGORY_REVIEWED:
        records = [row for row in matching if not row["is_pending"] and row["latest"] is not None]
    elif category == professional_overview.CATEGORY_FOLLOW_UP:
        records = [row for row in matching if row["has_follow_up"]]
    else:
        records = matching
    draft_store = get_screening_draft_store()
    for row in records:
        row["has_draft"] = row["source"] == "record" and bool(draft_store.list_drafts(row["user_id"]))
    return render_template("patients/index.html", page_title="Patients", records=records, query=term,
                           risk=risk, category=category, counts=counts)


@patient_records_bp.route("/assessments/new")
@role_required("professional")
def new_assessment():
    """Section 12: choose whether this assessment is for an existing patient (search and select) or a brand new
    one (the registration form). Two plain choice cards - no assessment has started yet either way."""
    return render_template("patients/new_assessment.html", page_title="New assessment")


@patient_records_bp.route("/assessments/new/existing")
@role_required("professional")
def assess_existing():
    """Section 13: search this professional's own patient records, see each match's basic info before choosing,
    then go straight to the assessment-type page for the one selected. Scoped to patient records only - a shared
    patient already has their own account and screens themselves, so there is no "assess them" action here."""
    term = request.args.get("q", "").strip()
    results = patient_records.for_professional(get_patient_records_store(), g.user["user_id"], term) if term else []
    zone = current_app.config["APP_TIMEZONE"]
    store = get_assessment_store()
    described = []
    for record in results:
        rows = store.list_assessments(record["user_id"])
        described.append({**record, "latest": assessments.to_record(rows[0], zone) if rows else None})
    return render_template("patients/assess_existing.html", page_title="Assess an existing patient", query=term, results=described)


@patient_records_bp.route("/patient-records/new", methods=["GET", "POST"])
@role_required("professional")
def new_patient():
    if request.method == "GET":
        return render_template("patients/new.html", page_title="New patient", values={}, errors={})
    values, errors = patient_records.validate_new_patient(request.form, clock.local_today(current_app.config["APP_TIMEZONE"]))
    if errors:
        return render_template("patients/new.html", page_title="New patient", values=request.form, errors=errors)
    user_id, code = patient_records.register_patient(get_patient_records_store(), g.user["user_id"],
                                                      values["full_name"], values["age"], values["sex"], clock.now_utc(),
                                                      date_of_birth=values["date_of_birth"], country=values["country"],
                                                      gender=values["gender"], location=values["location"])
    current_app.logger.info("Patient record created (user_id=%s, code=%s, professional_user_id=%s)", user_id, code, g.user["user_id"])
    flash(f"{values['full_name']} ({code}) has been added.", "success")
    return redirect(url_for("patient_records.choose_assessment", patient_code=code))


@patient_records_bp.route("/patient-records/<patient_code>")
@role_required("professional")
def profile(patient_code):
    record = _owned_or_404(patient_code)
    rows = assessments.load_records(get_assessment_store(), record["user_id"], current_app.config["APP_TIMEZONE"])
    drafts = screening_drafts.describe_for_dashboard(get_screening_draft_store(), record["user_id"], current_app.config["APP_TIMEZONE"],
                                                     {"preliminary": [step["key"] for step in _catalog()["steps"]]})
    return render_template("patients/profile.html", page_title=record["full_name"], record=record, drafts=drafts,
                           assessment_records=rows, latest=rows[0] if rows else None,
                           added_date=clock.to_local_date(record["created_at"], current_app.config["APP_TIMEZONE"]))


@patient_records_bp.route("/patient-records/<patient_code>/assess")
@role_required("professional")
def choose_assessment(patient_code):
    record = _owned_or_404(patient_code)
    return render_template("patients/choose_assessment.html", page_title="New assessment", record=record,
                           has_preliminary=_latest_preliminary_for(record["user_id"]) is not None)


@patient_records_bp.route("/patient-records/<patient_code>/screening/draft", methods=["POST"])
@role_required("professional")
def save_screening_draft(patient_code):
    """The form's own background autosave for a patient record (a tiny JSON answer, never a page)."""
    record = _owned_or_404(patient_code)
    screening_drafts.save_draft(get_screening_draft_store(), record["user_id"], "preliminary",
                                request.form, request.form.get("current_step"), clock.now_utc())
    return {"status": "saved"}


def _same_submission(store, user_id, inputs, answer, now):
    """A double click or a resend sends the same answers again within seconds: that is one assessment, not two -
    the same rule routes/screening_routes.py applies for a person screening themselves. Only inputs, the time
    window, and model_version are compared (never the computed probability): inputs are the raw form answers, so
    unlike probability they carry no floating-point rounding to worry about, and are already a complete signal -
    the same inputs through the same model version always produce the same result."""
    rows = store.list_assessments(user_id)
    if not rows:
        return None
    newest = store.get_assessment(user_id, rows[0]["assessment_id"])
    if newest and newest["inputs"] == inputs and now - newest["assessed_at"] < DUPLICATE_WINDOW \
            and newest["model_version"] == answer["model_version"]:
        return newest["assessment_id"]
    return None


def _fixed_for(record):
    """The same fixed answers as a General User's own screening (services/fixed_answers.py): age from the record's
    date of birth, country from the record, and Sex/Ethnicity/Country kept from its first preliminary. A record
    made before birthdays were asked has only its stored age and sex, which are fixed the same way."""
    today = clock.local_today(current_app.config["APP_TIMEZONE"])
    fixed = fixed_answers.fixed_for(record.get("date_of_birth"), record.get("country"),
                                    fixed_answers.earliest_preliminary_inputs(get_assessment_store(), record["user_id"]), today)
    fixed.setdefault("Age", {"value": record["age"], "reason": "From the patient record."})
    fixed.setdefault("Sex", {"value": record["sex"], "reason": "From the patient record."})
    if record.get("gender"):          # a record made before Gender was asked has none: it is asked in the screening
        fixed.setdefault("Gender", {"value": record["gender"], "reason": "From the patient record."})
    return fixed


def _screening_form(catalog, answers, errors, patient_code, record, start_step=-1):
    steps = [step["key"] for step in catalog["steps"]]
    failing = screening_contract.steps_with_errors(catalog, errors)
    first_error_step = next((i for i, key in enumerate(steps) if key in failing), start_step)
    return render_template("patients/screening_form.html", page_title="Preliminary screening", catalog=catalog,
                           answers=answers, errors=errors, first_error_step=first_error_step, step_keys=steps,
                           patient_code=patient_code, record=record, fixed=_fixed_for(record))


@patient_records_bp.route("/patient-records/<patient_code>/screening", methods=["GET", "POST"])
@role_required("professional")
def screening(patient_code):
    record = _owned_or_404(patient_code)
    model, catalog = _model(), _catalog()
    if not model.ready:
        return render_template("screening/unavailable.html", page_title="Screening", kind="unavailable",
                               title="Screening is temporarily unavailable"), 503

    fixed = _fixed_for(record)
    draft_store = get_screening_draft_store()
    if request.method == "GET":
        # Like a General User's own screening: a refresh, a Back, or a closed tab picks up where the professional left
        # off - the draft belongs to the patient record's own account, so it is this patient's, not the professional's.
        answers = fixed_answers.apply(screening_drafts.resume_values(draft_store, record["user_id"], "preliminary") or {}, fixed)
        start = screening_drafts.resume_step_index(draft_store, record["user_id"], "preliminary", [step["key"] for step in catalog["steps"]])
        return _screening_form(catalog, answers, {}, patient_code, record, start_step=start)

    form = fixed_answers.apply(request.form, fixed)          # the server decides the fixed answers, not the page
    values, inputs, errors = screening_contract.validate_answers(catalog, form, fixed=fixed)
    if errors:
        return _screening_form(catalog, form, errors, patient_code, record)

    try:
        answer = model.predict(values)
    except Exception as error:                            # the model failed for any reason: say so, save nothing
        current_app.logger.error("Screening could not be analysed: %s: %s", type(error).__name__, error)
        return render_template("screening/unavailable.html", page_title="Screening", kind="unavailable",
                               title="We could not analyse these answers"), 503

    store, now = get_assessment_store(), clock.now_utc()
    duplicate = _same_submission(store, record["user_id"], inputs, answer, now)
    if duplicate:
        return redirect(url_for("patient_records.risk_analysis", patient_code=patient_code, assessment_id=duplicate))
    assessment_id = assessments.record_assessment(store, record["user_id"], {
        "assessment_type": answer["assessment_type"], "probability": answer["probability"],
        "classification": answer["classification"], "threshold_used": answer["threshold"],
        "model_version": answer["model_version"], "assessed_at": now,
    }, inputs)
    screening_drafts.discard(draft_store, record["user_id"], "preliminary")
    current_app.logger.info("Assessment saved for a patient record (user_id=%s, assessment_id=%s, professional_user_id=%s, %s)",
                            record["user_id"], assessment_id, g.user["user_id"], answer["classification"])
    flash("The result is ready and saved to this patient's history.", "success")
    return redirect(url_for("patient_records.risk_analysis", patient_code=patient_code, assessment_id=assessment_id))


@patient_records_bp.route("/patient-records/<patient_code>/results/<int:assessment_id>")
@role_required("professional")
def risk_analysis(patient_code, assessment_id):
    record = _owned_or_404(patient_code)
    config = current_app.config
    store = get_assessment_store()
    row = store.get_assessment(record["user_id"], assessment_id)
    if row is None:
        abort(404)                                        # not this patient's, or it does not exist: the same answer

    result_record = assessments.to_record(row, config["APP_TIMEZONE"])
    all_rows = assessments.load_records(store, record["user_id"], config["APP_TIMEZONE"])
    older = [r for r in all_rows if r["assessment_id"] != assessment_id and (r["date"], r["assessment_id"]) <= (result_record["date"], assessment_id)]
    previous = older[0] if older else None
    catalog = _catalog()
    if row["assessment_type"] == "enhanced":
        lab_catalog = lab_contract.load_lab_catalog()
        model, describer = current_app.extensions["model_service_stage2"], stage2_describer(lab_catalog)
        answers = (screening_contract.describe_inputs(catalog, row["inputs"]) + lab_contract.describe_lab_values(lab_catalog, row["inputs"])) if row["inputs"] else []
    else:
        model, describer = _model(), catalog
        answers = screening_contract.describe_inputs(catalog, row["inputs"]) if row["inputs"] else []
    explanation = explanations.explain_saved_result(model, describer, row)
    outside = screening_contract.outside_training(catalog, row["inputs"]) if row["inputs"] else []
    return render_template("patients/risk_analysis.html", page_title="Risk analysis", record=record, result=result_record, outside=outside,
                           previous=previous, explanation=explanation, explanation_unavailable=explanations.UNAVAILABLE,
                           answers=answers, level=result_record["level"], threshold=result_record["threshold"])


@patient_records_bp.route("/patient-reports")
@role_required("professional")
def reports():
    """Sections 48-51: report stats (each assessment is a report, available to download), searchable and
    filterable the same way as the Assessments section - reusing the same assessment_list() aggregation."""
    term = request.args.get("q", "").strip()
    risk = request.args.get("risk") or None
    review_status = request.args.get("review_status") or None
    rows = professional_overview.assessment_list(
        get_patient_records_store(), get_authorization_store(), get_user_store(), get_assessment_store(),
        get_clinical_review_store(), g.user["user_id"], current_app.config["APP_TIMEZONE"], term=term, risk=risk,
    )
    if review_status in ("awaiting_review", "reviewed"):
        rows = [row for row in rows if row["review_status"] == review_status
               or (review_status == "reviewed" and row["review_status"] == "self_recorded")]
    all_rows = professional_overview.assessment_list(
        get_patient_records_store(), get_authorization_store(), get_user_store(), get_assessment_store(),
        get_clinical_review_store(), g.user["user_id"], current_app.config["APP_TIMEZONE"],
    )
    stats = {
        "total": len(all_rows),
        "high_risk": sum(1 for row in all_rows if row["level"] == "high"),
        "pending": sum(1 for row in all_rows if row["review_status"] == "awaiting_review"),
        "reviewed": sum(1 for row in all_rows if row["review_status"] in ("reviewed", "self_recorded")),
    }
    return render_template("patients/reports.html", page_title="Reports", records=rows, stats=stats,
                           query=term, risk=risk, review_status=review_status)



def _latest_preliminary_for(user_id):
    """This patient record's most recent Preliminary screening, with its saved answers, or None."""
    store = get_assessment_store()
    for row in store.list_assessments(user_id):
        if row["assessment_type"] == "preliminary":
            return store.get_assessment(user_id, row["assessment_id"])
    return None


def _patient_document(record, lab_document_id):
    """An uploaded lab report that belongs to THIS patient record, still waiting to be confirmed - or None."""
    if not lab_document_id:
        return None
    try:
        document = get_lab_document_store().get_document(record["user_id"], int(lab_document_id))
    except (TypeError, ValueError):
        return None
    return document if document and document["status"] not in ("confirmed", "discarded") else None   # same rule as lab_routes.confirm


def _enhanced_form(record, values, errors, document=None):
    return render_template("lab/confirm.html", page_title="Enhanced assessment", catalog=current_app.extensions["lab_catalog"],
                           values=values, errors=errors, document=document, nav_key="patients",
                           upload_action=url_for("patient_records.enhanced_upload", patient_code=record["patient_code"]),
                           heading="Enhanced / Laboratory assessment",
                           subheading=f"For {record['full_name']} ({record['patient_code']}) - enter the lab values you have; leave the rest blank.",
                           form_action=url_for("patient_records.enhanced", patient_code=record["patient_code"],
                                               document=document["lab_document_id"] if document else None))


@patient_records_bp.route("/patient-records/<patient_code>/enhanced", methods=["GET", "POST"])
@role_required("professional")
def enhanced(patient_code):
    """Enhanced / Laboratory assessment for a patient record: the SAME lab validation, Stage 2 model, and eGFR as a
    General User's own Enhanced Screening (routes/lab_routes.py), built on this patient's most recent Preliminary
    screening and saved under the patient record's own account."""
    record = _owned_or_404(patient_code)
    source = _latest_preliminary_for(record["user_id"])
    if source is None:
        flash("Complete a Preliminary Screening for this patient first - the Enhanced assessment builds on it.", "error")
        return redirect(url_for("patient_records.choose_assessment", patient_code=patient_code))
    model = current_app.extensions["model_service_stage2"]
    if not model.ready:
        return render_template("lab/unavailable.html", page_title="Enhanced assessment", kind="unavailable",
                               title="Enhanced assessment is temporarily unavailable"), 503
    document = _patient_document(record, request.values.get("document"))
    if request.method == "GET":
        return _enhanced_form(record, (document or {}).get("ocr_values") or {}, {}, document)

    values, errors = lab_contract.validate_lab_values(current_app.extensions["lab_catalog"], request.form)
    if document is not None and request.form.get("attest") != "1":    # an uploaded report: the professional vouches for it
        errors["attest"] = "Please confirm that this report is the patient's and that the values match it."
    if errors:
        return _enhanced_form(record, {k: v for k, v in request.form.items() if v}, errors, document)
    row = dict(source["inputs"])
    row.update(values)
    try:
        answer = model.predict(row)
    except Exception as error:                            # the model failed for any reason: say so, save nothing
        current_app.logger.error("Enhanced assessment could not be analysed (patient user_id=%s): %s: %s", record["user_id"], type(error).__name__, error)
        return render_template("lab/unavailable.html", page_title="Enhanced assessment", kind="unavailable",
                               title="We could not analyse these values"), 503
    saved_inputs = dict(row)
    saved_inputs["eGFR"] = estimate_gfr(row["Serum_Creatinine"], row["Age"], row["Sex"])
    assessment_id = assessments.record_assessment(get_assessment_store(), record["user_id"], {
        "assessment_type": "enhanced", "source_assessment_id": source["assessment_id"], "probability": answer["probability"],
        "classification": answer["classification"], "threshold_used": answer["threshold"], "model_version": answer["model_version"],
        "assessed_at": clock.now_utc(),
    }, saved_inputs)
    if document is not None:
        get_lab_document_store().confirm(record["user_id"], document["lab_document_id"], values, assessment_id, clock.now_utc())
    current_app.logger.info("Enhanced assessment saved for a patient record (user_id=%s, assessment_id=%s, professional_user_id=%s)",
                            record["user_id"], assessment_id, g.user["user_id"])
    flash("The Enhanced assessment is ready and saved to this patient's history.", "success")
    return redirect(url_for("patient_records.risk_analysis", patient_code=patient_code, assessment_id=assessment_id))



@patient_records_bp.route("/patient-records/<patient_code>/enhanced/upload", methods=["POST"])
@role_required("professional")
def enhanced_upload(patient_code):
    """A lab report for a patient record, read by the SAME Tesseract OCR as a General User's own upload
    (services/lab_ocr.py) - the values it finds only PRE-FILL the form; the professional checks every one before
    anything is analysed. A report OCR cannot read is never an error: the form simply opens empty."""
    record = _owned_or_404(patient_code)
    back = url_for("patient_records.enhanced", patient_code=patient_code)
    file_storage = request.files.get("document")
    if file_storage is None or not file_storage.filename:
        flash("Choose a file to upload.", "error")
        return redirect(back)
    try:
        stored_filename, content_type, original_filename = lab_documents.save_upload(file_storage, current_app.config["UPLOAD_DIR"])
    except lab_documents.RejectedUpload as error:
        flash(str(error)[0].upper() + str(error)[1:], "error")
        return redirect(back)
    store = get_lab_document_store()
    lab_document_id = store.add_document(record["user_id"], original_filename, stored_filename, content_type, clock.now_utc())
    try:
        text = lab_ocr.extract_text(lab_documents.path_for(current_app.config["UPLOAD_DIR"], stored_filename), content_type,
                                    tesseract_cmd=current_app.config.get("TESSERACT_CMD") or None)
        found = lab_ocr.extract_candidate_values(text, current_app.extensions["lab_catalog"])
    except lab_ocr.UnreadableDocument as error:
        text = ""
        current_app.logger.warning("Patient lab document could not be read (patient user_id=%s, lab_document_id=%s): %s",
                                   record["user_id"], lab_document_id, error)
        found = {}
    store.set_ocr_values(record["user_id"], lab_document_id, found)
    store.set_verification(record["user_id"], lab_document_id,
                           lab_verification.check(text, record["full_name"], clock.local_today(current_app.config["APP_TIMEZONE"])))
    flash(f"Read {len(found)} value{'s' if len(found) != 1 else ''} from the report - check every one before analysing." if found
          else "No values could be read from that report - enter them below.", "success" if found else "info")
    return redirect(url_for("patient_records.enhanced", patient_code=patient_code, document=lab_document_id))
