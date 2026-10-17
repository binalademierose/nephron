"""
screening_routes.py - the preliminary screening: the guided form, the analysis, and the result page.

The rules this file keeps:
  * Only a signed-in General User can screen, and only ever sees their OWN results (an id that belongs to someone
    else is answered exactly like an id that does not exist).
  * If the model is not ready (missing, changed, or not matching the questions) nothing is analysed and nothing is
    saved. The person is told screening is unavailable. A result is never invented.
  * The analysis is one POST. The answers are checked by the server (services/screening_contract.py), the model is
    asked once (services/model_service.py), and the result and the answers are saved together as a new permanent row.
    The person is then REDIRECTED to the saved result, so pressing Refresh cannot save it a second time.
"""
from datetime import timedelta

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from routes.decorators import role_required
from services import activity, assessments, clinical_reviews, clock, explanations, fixed_answers, followups, kidney_tips, lab_contract, reassessment, screening_contract, screening_drafts, visuals
from services.assessment_store import get_assessment_store
from services.user_store import get_user_store
from services.clinical_review_store import get_clinical_review_store
from services.followup_store import get_followup_store
from services.reassessment_store import get_reassessment_store
from services.screening_draft_store import get_screening_draft_store

screening_bp = Blueprint("screening", __name__)

DUPLICATE_WINDOW = timedelta(seconds=60)      # the same answers sent again within this time are the same submission


def _model():
    return current_app.extensions["model_service"]


def _catalog():
    return current_app.extensions["catalog"]


def _stage2_describer():
    from services.model_service_stage2 import stage2_describer
    return stage2_describer(lab_contract.load_lab_catalog())


def _records():
    config = current_app.config
    return assessments.load_records(get_assessment_store(), g.user["user_id"], config["APP_TIMEZONE"])


def _unavailable(message="Screening is temporarily unavailable"):
    return render_template("screening/unavailable.html", page_title="Screening", kind="unavailable", title=message), 503


def _wait_summary():
    """This person's summary, with the waiting period in force and any early screening a professional or the
    administrator has opened for them (services/reassessment.py)."""
    config = current_app.config
    open_follow_up = followups.open_request(get_followup_store(), g.user["user_id"])
    return visuals.summarize_assessments(_records(), today=clock.local_today(config["APP_TIMEZONE"]),
                                         reassessment_days=reassessment.current_period(), follow_up_open=open_follow_up is not None)


def _waiting_page(summary, form_reason="", error=None):
    return render_template("screening/unavailable.html", page_title="Screening", kind="waiting", title="Your next screening is not open yet",
                           summary=summary, latest=summary["latest"], period=reassessment.current_period(),
                           admin_request=get_reassessment_store().latest_for(g.user["user_id"]),
                           max_reason=reassessment.MAX_REASON_LENGTH, form_reason=form_reason, error=error), 200


@screening_bp.route("/screening/ask-admin", methods=["POST"])
@role_required("general")
def ask_admin():
    """During the waiting period, ask the administrator to let this person screen again early (one screening)."""
    summary = _wait_summary()
    reason = request.form.get("reason", "")
    try:
        reassessment.ask_admin(get_reassessment_store(), g.user["user_id"], reason,
                               summary["next_screening"]["state"] == "waiting", clock.now_utc())
    except reassessment.RequestError as error:
        if summary["next_screening"]["state"] != "waiting":
            flash(str(error), "info")
            return redirect(url_for("screening.screening"))
        return _waiting_page(summary, form_reason=reason, error=str(error))
    activity.record("reassessment_requested", g.user["user_id"], g.user["user_id"])
    flash("Your request was sent to the administrator. You will get a notification when they decide.", "success")
    return redirect(url_for("screening.screening"))


@screening_bp.route("/screening", methods=["GET", "POST"])
@role_required("general")
def screening():
    model, catalog, config = _model(), _catalog(), current_app.config
    if not model.ready:
        return _unavailable()

    summary = _wait_summary()
    if summary["next_screening"]["state"] == "waiting":
        return _waiting_page(summary)

    draft_store = get_screening_draft_store()
    me = get_user_store().find_by_id(g.user["user_id"])
    fixed = fixed_answers.fixed_for(me.get("date_of_birth"), me.get("country"),
                                    fixed_answers.earliest_preliminary_inputs(get_assessment_store(), g.user["user_id"]),
                                    clock.local_today(config["APP_TIMEZONE"]))
    if request.method == "GET":
        answers = screening_drafts.resume_values(draft_store, g.user["user_id"], "preliminary")
        answers = fixed_answers.apply(answers or {}, fixed)
        step_keys = [step["key"] for step in catalog["steps"]]
        start_step = screening_drafts.resume_step_index(draft_store, g.user["user_id"], "preliminary", step_keys)
        return _form(catalog, answers, {}, start_step=start_step, fixed=fixed)

    form = fixed_answers.apply(request.form, fixed)          # the server decides the fixed answers, not the page
    values, inputs, errors = screening_contract.validate_answers(catalog, form, fixed=fixed)
    if errors:
        return _form(catalog, form, errors, fixed=fixed)

    try:
        answer = model.predict(values)
    except Exception as error:                            # the model failed for any reason: say so, save nothing
        current_app.logger.error("Screening could not be analysed: %s: %s", type(error).__name__, error)
        return _unavailable("We could not analyse your answers")

    store, now = get_assessment_store(), clock.now_utc()
    duplicate = _same_submission(store, inputs, answer, now)
    if duplicate:
        return redirect(url_for("screening.result", assessment_id=duplicate))
    assessment_id = assessments.record_assessment(store, g.user["user_id"], {
        "assessment_type": answer["assessment_type"], "probability": answer["probability"],
        "classification": answer["classification"], "threshold_used": answer["threshold"],
        "model_version": answer["model_version"], "assessed_at": now,
    }, inputs)
    followups.mark_fulfilled_by_new_assessment(get_followup_store(), g.user["user_id"], now)
    reassessment.screening_saved(get_reassessment_store(), g.user["user_id"], now)
    screening_drafts.discard(draft_store, g.user["user_id"], "preliminary")
    current_app.logger.info("Assessment saved (user_id=%s, assessment_id=%s, %s)", g.user["user_id"], assessment_id, answer["classification"])
    flash("Your result is ready and saved to your history.", "success")
    return redirect(url_for("screening.result", assessment_id=assessment_id))


@screening_bp.route("/screening/draft", methods=["POST"])
@role_required("general")
def save_draft():
    """Called by the form's own autosave, in the background - never a full page load, so it answers with a tiny
    JSON body, not a redirect or a rendered page."""
    screening_drafts.save_draft(get_screening_draft_store(), g.user["user_id"], "preliminary",
                                request.form, request.form.get("current_step"), clock.now_utc())
    return {"status": "saved"}


@screening_bp.route("/screening/draft/discard", methods=["POST"])
@role_required("general")
def discard_draft():
    assessment_type = request.form.get("assessment_type", "preliminary")
    if assessment_type not in ("preliminary", "enhanced"):
        abort(400)
    screening_drafts.discard(get_screening_draft_store(), g.user["user_id"], assessment_type)
    flash("Your unfinished screening was discarded.", "success")
    return redirect(url_for("account.dashboard"))


def _same_submission(store, inputs, answer, now):
    """A double click or a resend sends the same answers again within seconds: that is one assessment, not two."""
    rows = store.list_assessments(g.user["user_id"])
    if not rows:
        return None
    newest = store.get_assessment(g.user["user_id"], rows[0]["assessment_id"])
    if newest and newest["inputs"] == inputs and now - newest["assessed_at"] < DUPLICATE_WINDOW \
            and newest["model_version"] == answer["model_version"]:
        return newest["assessment_id"]
    return None


def _form(catalog, answers, errors, start_step=-1, fixed=None):
    steps = [step["key"] for step in catalog["steps"]]
    failing = screening_contract.steps_with_errors(catalog, errors)
    first_error_step = next((i for i, key in enumerate(steps) if key in failing), start_step)
    return render_template("screening/form.html", page_title="Preliminary screening", catalog=catalog,
                           answers=answers, errors=errors, first_error_step=first_error_step, step_keys=steps, fixed=fixed or {})


@screening_bp.route("/results/<int:assessment_id>")
@role_required("general")
def result(assessment_id):
    config = current_app.config
    row = get_assessment_store().get_assessment(g.user["user_id"], assessment_id)
    if row is None:
        abort(404)                                     # not yours, or it does not exist: the same answer

    record = assessments.to_record(row, config["APP_TIMEZONE"])
    older = [r for r in _records() if r["assessment_id"] != assessment_id and (r["date"], r["assessment_id"]) <= (record["date"], assessment_id)]
    previous = older[0] if older else None
    change = None
    if previous:
        change = visuals.summarize_assessments([record, previous], today=clock.local_today(config["APP_TIMEZONE"]))["change"]

    if row["assessment_type"] == "enhanced":
        model, describer = current_app.extensions["model_service_stage2"], _stage2_describer()
        stage1_answers = screening_contract.describe_inputs(_catalog(), row["inputs"]) if row["inputs"] else []
        lab_answers = lab_contract.describe_lab_values(lab_contract.load_lab_catalog(), row["inputs"]) if row["inputs"] else []
        answers = stage1_answers + lab_answers
    else:
        model, describer = _model(), _catalog()
        answers = screening_contract.describe_inputs(_catalog(), row["inputs"]) if row["inputs"] else []

    # What affected THIS result most: worked out again from the answers saved with it, and shown only when the model that is running
    # now is the model that made it and its contributions add up to the saved probability. Otherwise nothing is shown.
    explanation = explanations.explain_saved_result(model, describer, row)
    reviews = [dict(r, date=clock.to_local_date(r["created_at"], config["APP_TIMEZONE"])) for r in clinical_reviews.for_assessment(get_clinical_review_store(), assessment_id)]
    tips = kidney_tips.personalized_tips(row["inputs"], record["level"])
    outside = screening_contract.outside_training(_catalog(), row["inputs"]) if row["inputs"] else []
    return render_template("screening/result.html", page_title="Screening result", record=record, previous=previous, change=change, outside=outside,
                           explanation=explanation, explanation_unavailable=explanations.UNAVAILABLE, answers=answers, level=record["level"],
                           threshold=record["threshold"], source_id=row.get("source_assessment_id"), reviews=reviews, tips=tips)
