"""
lab_routes.py - Enhanced Screening: uploading a lab document, confirming its values (or entering them by hand),
and computing the Stage 2 result.

The rules this file keeps:
  * Only a signed-in General User can use this, and only ever sees their OWN uploads and results.
  * Enhanced Screening is an EXTENSION of a person's most recent Preliminary screening: it needs one to exist first,
    and pulls its 27 non-laboratory answers from it rather than asking again (see Stage2ModelService).
  * Nothing OCR proposes is ever saved on its own. The person must open the confirmation page and submit it -
    the same as anything they typed by hand - and services/lab_contract.py checks it again from scratch there.
  * If the Stage 2 model is not ready, nothing is analysed and nothing is saved.
"""
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from routes.decorators import role_required
from services import assessments, clock, followups, lab_contract, lab_documents, lab_ocr, lab_verification, reassessment
from services.egfr import estimate_gfr
from services.assessment_store import get_assessment_store
from services.followup_store import get_followup_store
from services.reassessment_store import get_reassessment_store
from services.lab_document_store import get_lab_document_store
from services.model_service_stage2 import stage2_describer

lab_bp = Blueprint("lab", __name__)


def _model():
    return current_app.extensions["model_service_stage2"]


def _catalog():
    return current_app.extensions["lab_catalog"]


def _latest_preliminary():
    """This user's most recent 'preliminary' assessment, with its saved answers, or None if they have none yet."""
    store = get_assessment_store()
    for row in store.list_assessments(g.user["user_id"]):
        if row["assessment_type"] == "preliminary":
            return store.get_assessment(g.user["user_id"], row["assessment_id"])
    return None


def _blocked():
    """None if Enhanced Screening may proceed; otherwise the page (and its reason) to show instead."""
    if _latest_preliminary() is None:
        return render_template("lab/unavailable.html", page_title="Enhanced Screening", kind="no_preliminary",
                               title="Complete a preliminary screening first")
    if not _model().ready:
        return render_template("lab/unavailable.html", page_title="Enhanced Screening", kind="unavailable",
                               title="Enhanced Screening is temporarily unavailable")
    return None


@lab_bp.route("/enhanced-screening")
@role_required("general")
def start():
    blocked = _blocked()
    return blocked if blocked else render_template("lab/upload.html", page_title="Enhanced Screening")


@lab_bp.route("/enhanced-screening/upload", methods=["POST"])
@role_required("general")
def upload():
    blocked = _blocked()
    if blocked:
        return blocked
    file_storage = request.files.get("document")
    if file_storage is None or not file_storage.filename:
        flash("Choose a file to upload.", "error")
        return redirect(url_for("lab.start"))
    try:
        stored_filename, content_type, original_filename = lab_documents.save_upload(file_storage, current_app.config["UPLOAD_DIR"])
    except lab_documents.RejectedUpload as error:
        if error.__cause__ is not None:
            current_app.logger.error("Lab document upload failed (user_id=%s, UPLOAD_DIR=%s): %s: %s",
                                     g.user["user_id"], current_app.config["UPLOAD_DIR"], type(error.__cause__).__name__, error.__cause__)
        flash(str(error)[0].upper() + str(error)[1:], "error")
        return redirect(url_for("lab.start"))

    store = get_lab_document_store()
    lab_document_id = store.add_document(g.user["user_id"], original_filename, stored_filename, content_type, clock.now_utc())
    try:
        text = lab_ocr.extract_text(lab_documents.path_for(current_app.config["UPLOAD_DIR"], stored_filename), content_type,
                                    tesseract_cmd=current_app.config.get("TESSERACT_CMD") or None)
        found = lab_ocr.extract_candidate_values(text, _catalog())
    except lab_ocr.UnreadableDocument as error:
        text = ""
        # Never fatal: the upload still succeeds, just with nothing suggested - the person fills the form in by
        # hand instead, exactly as if no lab report had been uploaded at all. This is the ONLY place OCR is asked
        # to do anything, so a broken tesseract install shows up here and nowhere else.
        current_app.logger.warning("Lab document could not be read (user_id=%s, lab_document_id=%s): %s", g.user["user_id"], lab_document_id, error)
        found = {}
    store.set_ocr_values(g.user["user_id"], lab_document_id, found)
    store.set_verification(g.user["user_id"], lab_document_id,
                           lab_verification.check(text, g.user["full_name"], clock.local_today(current_app.config["APP_TIMEZONE"])))
    current_app.logger.info("Lab document uploaded and read (user_id=%s, lab_document_id=%s, %d value(s) found)",
                            g.user["user_id"], lab_document_id, len(found))
    return redirect(url_for("lab.confirm", lab_document_id=lab_document_id))


@lab_bp.route("/enhanced-screening/manual")
@role_required("general")
def manual():
    blocked = _blocked()
    return blocked if blocked else _confirm_form({}, {})


@lab_bp.route("/enhanced-screening/confirm/<int:lab_document_id>", methods=["GET", "POST"])
@role_required("general")
def confirm(lab_document_id):
    blocked = _blocked()
    if blocked:
        return blocked
    document = get_lab_document_store().get_document(g.user["user_id"], lab_document_id)
    if document is None:
        abort(404)                                     # not yours, or it does not exist: the same answer
    if document["status"] == "confirmed":
        return redirect(url_for("screening.result", assessment_id=document["assessment_id"]))
    if document["status"] == "discarded":
        return redirect(url_for("lab.start"))
    if request.method == "GET":
        return _confirm_form(document["ocr_values"] or {}, {}, document=document)
    return _submit(document["ocr_values"], request.form, document=document)


@lab_bp.route("/enhanced-screening/confirm", methods=["POST"])
@role_required("general")
def confirm_manual():
    blocked = _blocked()
    return blocked if blocked else _submit(None, request.form, document=None)


def _confirm_form(values, errors, document=None):
    return render_template("lab/confirm.html", page_title="Confirm your lab values", catalog=_catalog(),
                           values=values, errors=errors, document=document)


def _submit(ocr_values, form, document):
    values, errors = lab_contract.validate_lab_values(_catalog(), form)
    if document is not None and form.get("attest") != "1":           # an uploaded report: the person vouches for it
        errors["attest"] = "Please confirm that this report is yours and that the values match it."
    if errors:
        return _confirm_form({**(ocr_values or {}), **{k: v for k, v in form.items() if v}}, errors, document=document)

    source = _latest_preliminary()                  # re-read: it must still be there, even though _blocked() just checked
    row = dict(source["inputs"])
    row.update(values)
    try:
        answer = _model().predict(row)
    except Exception as error:
        current_app.logger.error("Enhanced Screening could not be analysed (user_id=%s): %s: %s", g.user["user_id"], type(error).__name__, error)
        return render_template("lab/unavailable.html", page_title="Enhanced Screening", kind="unavailable",
                               title="We could not analyse these values"), 200

    # The 27 pulled Stage 1 answers (plus BMI's own height/weight), the given labs, and eGFR: computed once here and
    # stored explicitly (unlike Stage 1's Obesity, which is also always stored) so that opening this result again -
    # to explain it, or just to read it - never needs to recompute it from a possibly-changed formula or a
    # possibly-changed Preliminary answer. It is still never asked for, and never anything other than this computation.
    saved_inputs = dict(row)
    saved_inputs["eGFR"] = estimate_gfr(row["Serum_Creatinine"], row["Age"], row["Sex"])
    store, now = get_assessment_store(), clock.now_utc()
    assessment_id = assessments.record_assessment(store, g.user["user_id"], {
        "assessment_type": "enhanced", "source_assessment_id": source["assessment_id"], "probability": answer["probability"],
        "classification": answer["classification"], "threshold_used": answer["threshold"], "model_version": answer["model_version"],
        "assessed_at": now,
    }, saved_inputs)
    followups.mark_fulfilled_by_new_assessment(get_followup_store(), g.user["user_id"], now)
    reassessment.screening_saved(get_reassessment_store(), g.user["user_id"], now)
    if document is not None:
        get_lab_document_store().confirm(g.user["user_id"], document["lab_document_id"], values, assessment_id, now)
    current_app.logger.info("Enhanced Screening saved (user_id=%s, assessment_id=%s, %s)", g.user["user_id"], assessment_id, answer["classification"])
    flash("Your Enhanced Screening result is ready and saved to your history.", "success")
    return redirect(url_for("screening.result", assessment_id=assessment_id))
