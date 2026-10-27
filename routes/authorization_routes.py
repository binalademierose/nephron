"""
authorization_routes.py - a patient sharing their assessment history with a professional, and the professional's
side of accepting, declining, viewing, and ending it.

  Patient (role 'general'):
    GET  /share                         search for a professional, see your own requests, revoke an accepted one
    POST /share/request                 send (or resend) a request to a professional found by search
    POST /share/revoke/<professional_id>  end an accepted authorization

  Professional (role 'professional'):
    GET  /patients                      pending requests to answer, and your authorized patients
    POST /patients/respond/<patient_id> accept or decline a pending request
    GET  /patients/<patient_id>         that patient's full assessment history (only if 'accepted' right now)
    GET  /patients/<patient_id>/assessments/<assessment_id>  one shared result with its answers and factors
    POST /patients/revoke/<patient_id>  end an accepted authorization from this side

Every route re-checks authorizations.is_authorized() itself before showing anything - never trusts a page having
been reachable once before, and never trusts g.user's role alone without also checking the actual relationship.
"""
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from routes.decorators import role_required
from datetime import date, datetime

from services import assessments, authorizations, clinical_reviews, clock, consents, explanations, followup_appointments, followups, followup_calendar, notifications, professional_overview, result_details
from services.assessment_store import get_assessment_store
from services.authorization_store import get_authorization_store
from services.clinical_review_store import get_clinical_review_store
from services.consent_store import get_consent_store
from services.followup_appointment_store import get_followup_appointment_store
from services.followup_store import get_followup_store
from services.notification_store import get_notification_store
from services.patient_records_store import get_patient_records_store
from services.user_store import get_user_store

authorization_bp = Blueprint("authorization", __name__)


# ------------------------------------------------------------------ patient side
@authorization_bp.route("/share")
@role_required("general")
def share():
    auth_store, user_store = get_authorization_store(), get_user_store()
    term = request.args.get("q", "").strip()
    results = _search_professionals(user_store, term)
    mine = authorizations.describe_for_patient(auth_store, user_store, g.user["user_id"])
    consent_dates = consents.latest_dates_for_patient(get_consent_store(), g.user["user_id"], current_app.config["APP_TIMEZONE"])
    return render_template("authorizations/share.html", page_title="Share with a professional",
                           query=term, results=results, authorizations=mine, consent_dates=consent_dates)


def _search_professionals(user_store, term):
    """Never lets a patient find their own account this way - searching for oneself to "share with" makes no sense."""
    results = user_store.search_professionals(term) if term else []
    # A switched-off account cannot be shared with (it cannot sign in to see anything).
    return [r for r in results if r["user_id"] != g.user["user_id"] and r.get("is_active", True)]


@authorization_bp.route("/share/search")
@role_required("general")
def share_search():
    """The live-search endpoint: the same search as /share itself, as JSON, for the page's own script to call
    while the person types."""
    user_store = get_user_store()
    try:
        term = request.args.get("q", "").strip()
        results = _search_professionals(user_store, term)
    except Exception as error:                              # a search box must never surface a raw error
        current_app.logger.error("Practitioner search failed: %s: %s", type(error).__name__, error)
        return {"error": "Search is temporarily unavailable."}, 503
    return {"results": [{"user_id": r["user_id"], "full_name": r["full_name"], "profession_title": r.get("profession_title"),
                        "institution": r.get("institution"), "verification_status": r.get("verification_status") or "pending"}
                       for r in results]}


@authorization_bp.route("/share/request", methods=["POST"])
@role_required("general")
def request_share():
    auth_store, user_store = get_authorization_store(), get_user_store()
    try:
        professional_id = int(request.form.get("professional_user_id", ""))
    except ValueError:
        abort(400)
    if not consents.given(request.form):
        # Sharing health information needs an active yes, checked here on the server and not only on the page.
        flash("Please confirm what you are sharing before sending a request. Nothing was sent.", "error")
        return redirect(url_for("authorization.share"))
    try:
        authorizations.request_authorization(auth_store, user_store, g.user["user_id"], professional_id, clock.now_utc())
    except authorizations.NotAProfessionalError:
        flash("That account could not be found.", "error")
        return redirect(url_for("authorization.share"))
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("authorization.share"))
    professional = user_store.find_by_id(professional_id)
    consents.record_share_consent(get_consent_store(), g.user["user_id"], professional_id, clock.now_utc())
    flash(f"Request sent to {professional['full_name']}. They can only see your history if they accept.", "success")
    notifications.notify_share_requested(get_notification_store(), professional_id, g.user["full_name"], clock.now_utc())
    current_app.logger.info("Authorization requested (patient_user_id=%s, professional_user_id=%s)", g.user["user_id"], professional_id)
    return redirect(url_for("authorization.share"))


@authorization_bp.route("/share/revoke/<int:professional_id>", methods=["POST"])
@role_required("general")
def revoke_share(professional_id):
    auth_store = get_authorization_store()
    if authorizations.revoke(auth_store, g.user["user_id"], professional_id, clock.now_utc()):
        flash("Access removed.", "success")
        current_app.logger.info("Authorization revoked by patient (patient_user_id=%s, professional_user_id=%s)", g.user["user_id"], professional_id)
    return redirect(url_for("authorization.share"))


# ------------------------------------------------------------------ professional side
@authorization_bp.route("/patients")
@role_required("professional")
def patients():
    auth_store, user_store = get_authorization_store(), get_user_store()
    pending = authorizations.describe_for_professional(auth_store, user_store, g.user["user_id"], statuses={"pending"})
    accepted = authorizations.describe_for_professional(auth_store, user_store, g.user["user_id"], statuses={"accepted"})

    term = request.args.get("q", "").strip()
    risk = request.args.get("risk") or None
    review_status = request.args.get("review_status") or None
    date_period = request.args.get("date_period") or professional_overview.DATE_ALL
    valid_periods = (professional_overview.DATE_TODAY, professional_overview.DATE_THIS_WEEK,
                     professional_overview.DATE_THIS_MONTH, professional_overview.DATE_ALL)
    if date_period not in valid_periods:
        date_period = professional_overview.DATE_ALL
    shared_assessments = professional_overview.shared_assessment_list(
        auth_store, user_store, get_assessment_store(), get_clinical_review_store(), g.user["user_id"],
        current_app.config["APP_TIMEZONE"], term=term, risk=risk, review_status=review_status, date_period=date_period,
    )
    return render_template("authorizations/patients.html", page_title="Shared assessments", pending=pending, accepted=accepted,
                           shared_assessments=shared_assessments, query=term, risk=risk, review_status=review_status, date_period=date_period)


@authorization_bp.route("/patients/respond/<int:patient_id>", methods=["POST"])
@role_required("professional")
def respond(patient_id):
    auth_store, user_store = get_authorization_store(), get_user_store()
    accept = request.form.get("action") == "accept"
    if authorizations.respond_to_request(auth_store, patient_id, g.user["user_id"], accept, clock.now_utc()):
        patient = user_store.find_by_id(patient_id)
        flash(f"{'Accepted' if accept else 'Declined'} the request from {patient['full_name']}.", "success")
        notifications.notify_share_response(get_notification_store(), patient_id, g.user["full_name"], accept, clock.now_utc())
        current_app.logger.info("Authorization %s (patient_user_id=%s, professional_user_id=%s)",
                                "accepted" if accept else "declined", patient_id, g.user["user_id"])
    return redirect(url_for("authorization.patients"))


@authorization_bp.route("/patients/revoke/<int:patient_id>", methods=["POST"])
@role_required("professional")
def revoke_patient(patient_id):
    auth_store = get_authorization_store()
    if authorizations.revoke(auth_store, patient_id, g.user["user_id"], clock.now_utc()):
        flash("Access ended.", "success")
        current_app.logger.info("Authorization revoked by professional (patient_user_id=%s, professional_user_id=%s)", patient_id, g.user["user_id"])
    return redirect(url_for("authorization.patients"))


@authorization_bp.route("/patients/<int:patient_id>")
@role_required("professional")
def patient_history(patient_id):
    return _history_page(patient_id)


def _history_page(patient_id, review_form=None, review_errors=None):
    """The shared patient's history. review_form/review_errors: a clinical-review submission that needs fixing, shown
    back with everything that was typed (a long clinical note is never lost to a mistyped appointment date)."""
    auth_store, user_store = get_authorization_store(), get_user_store()
    if not authorizations.is_authorized(auth_store, patient_id, g.user["user_id"]):
        abort(404)                                     # not authorized, or no such patient: the same answer
    patient = user_store.find_by_id(patient_id)
    if patient is None:
        abort(404)
    zone = current_app.config["APP_TIMEZONE"]
    store = get_assessment_store()
    records = assessments.load_records(store, patient_id, zone)
    reviews_by_assessment = clinical_reviews.for_assessments(get_clinical_review_store(), [r["assessment_id"] for r in records])
    for reviews in reviews_by_assessment.values():
        for review in reviews:
            review["date"] = clock.to_local_date(review["created_at"], zone)
    open_follow_up = followups.open_request(get_followup_store(), patient_id)
    if open_follow_up:
        open_follow_up["date"] = clock.to_local_date(open_follow_up["requested_at"], zone)
    appointments = followup_appointments.for_professional_patient(get_followup_appointment_store(), g.user["user_id"], patient_id, zone)
    # Which result the review form starts on: the one being fixed, else the one asked for (?assessment=), else the
    # newest result still awaiting a note, else the newest result.
    review_form = review_form or {}
    try:
        asked = int(review_form.get("assessment_id") or request.args.get("assessment", ""))
    except ValueError:
        asked = None
    ids = [r["assessment_id"] for r in records]
    selected_assessment_id = asked if asked in ids else next((r["assessment_id"] for r in records if not reviews_by_assessment.get(r["assessment_id"])), ids[0] if ids else None)
    # "Clinical note only" or "Clinical note + follow-up": what was chosen, else what the link asked for (?with=follow-up,
    # from a shared result's "Add note + follow-up" button), else a note only.
    review_mode = review_form.get("mode") or (REVIEW_WITH_FOLLOW_UP if request.args.get("with") == "follow-up" else REVIEW_NOTE_ONLY)
    return render_template("authorizations/patient_history.html", selected_assessment_id=selected_assessment_id, page_title=f"{patient['full_name']}'s history",
                           patient=patient, records=records, reviews_by_assessment=reviews_by_assessment, open_follow_up=open_follow_up,
                           appointments=appointments, review_form=review_form, review_errors=review_errors or {}, review_mode=review_mode,
                           min_date=clock.local_today(zone).isoformat())


@authorization_bp.route("/patients/<int:patient_id>/assessments/<int:assessment_id>")
@role_required("professional")
def shared_result(patient_id, assessment_id):
    """One shared result in full: the answers behind it and what raised or lowered the estimate - what the person
    agreed to share ("the answers and lab values behind it", templates/authorizations/_consent_template.html).
    The same detail a professional sees for a patient they recorded themselves (services/result_details.py)."""
    if not authorizations.is_authorized(get_authorization_store(), patient_id, g.user["user_id"]):
        abort(404)                                     # not authorized, or no such patient: the same answer
    patient = get_user_store().find_by_id(patient_id)
    if patient is None:
        abort(404)
    zone = current_app.config["APP_TIMEZONE"]
    store = get_assessment_store()
    row = store.get_assessment(patient_id, assessment_id)   # looked up within THIS patient only: another person's id is a 404
    if row is None:
        abort(404)
    result = assessments.to_record(row, zone)
    all_rows = assessments.load_records(store, patient_id, zone)
    older = [r for r in all_rows if r["assessment_id"] != assessment_id and (r["date"], r["assessment_id"]) <= (result["date"], assessment_id)]
    reviews = clinical_reviews.for_assessments(get_clinical_review_store(), [assessment_id]).get(assessment_id, [])
    for review in reviews:
        review["date"] = clock.to_local_date(review["created_at"], zone)
    details = result_details.describe(row, current_app.extensions["catalog"], current_app.extensions["model_service"],
                                      current_app.extensions["model_service_stage2"])
    return render_template("authorizations/shared_result.html", page_title=f"{patient['full_name']}'s result",
                           patient=patient, result=result, level=result["level"], threshold=result["threshold"],
                           previous=older[0] if older else None, reviews=reviews,
                           answers=details["answers"], explanation=details["explanation"], outside=details["outside"],
                           explanation_unavailable=explanations.UNAVAILABLE, explain_for_professional=True)


def _parse_local_datetime(form, zone):
    """A follow-up appointment's date and time come from two separate form fields (an HTML date input and a time
    input) - combined here into the one UTC moment the store keeps. Raises ValueError for a blank or malformed one."""
    date_text, time_text = (form.get("date") or "").strip(), (form.get("time") or "").strip()
    if not date_text or not time_text:
        raise ValueError("Enter both a date and a time.")
    try:
        naive_local = datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M")
    except ValueError:
        raise ValueError("Enter a valid date and time.")
    return clock.from_local_datetime(naive_local, zone)


@authorization_bp.route("/patients/<int:patient_id>/appointments", methods=["POST"])
@role_required("professional")
def schedule_appointment(patient_id):
    zone = current_app.config["APP_TIMEZONE"]
    store, auth_store = get_followup_appointment_store(), get_authorization_store()
    try:
        scheduled_at = _parse_local_datetime(request.form, zone)
        followup_appointments.schedule(store, auth_store, g.user, patient_id, scheduled_at,
                                       request.form.get("purpose", ""), request.form.get("notes", ""), clock.now_utc())
    except followup_appointments.NotAuthorizedError:
        abort(404)
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("authorization.patient_history", patient_id=patient_id))
    flash("Follow-up appointment scheduled.", "success")
    notifications.notify_follow_up_requested(get_notification_store(), patient_id, g.user["full_name"],
                                             f"Appointment scheduled: {request.form.get('purpose', '')}", clock.now_utc())
    current_app.logger.info("Follow-up appointment scheduled (patient_user_id=%s, professional_user_id=%s)", patient_id, g.user["user_id"])
    return redirect(url_for("authorization.patient_history", patient_id=patient_id))


@authorization_bp.route("/patients/<int:patient_id>/appointments/<int:appointment_id>/edit", methods=["POST"])
@role_required("professional")
def edit_appointment(patient_id, appointment_id):
    zone = current_app.config["APP_TIMEZONE"]
    store, auth_store = get_followup_appointment_store(), get_authorization_store()
    try:
        scheduled_at = _parse_local_datetime(request.form, zone)
        followup_appointments.reschedule(store, auth_store, g.user["user_id"], appointment_id, scheduled_at,
                                         request.form.get("purpose", ""), request.form.get("notes", ""), clock.now_utc())
    except followup_appointments.NotAuthorizedError:
        abort(404)
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("authorization.patient_history", patient_id=patient_id))
    flash("Appointment updated.", "success")
    return redirect(url_for("authorization.patient_history", patient_id=patient_id))


@authorization_bp.route("/patients/<int:patient_id>/appointments/<int:appointment_id>/cancel", methods=["POST"])
@role_required("professional")
def cancel_appointment(patient_id, appointment_id):
    store, auth_store = get_followup_appointment_store(), get_authorization_store()
    try:
        followup_appointments.cancel(store, auth_store, g.user["user_id"], appointment_id, clock.now_utc())
    except followup_appointments.NotAuthorizedError:
        abort(404)
    flash("Appointment cancelled.", "success")
    return redirect(url_for("authorization.patient_history", patient_id=patient_id))


@authorization_bp.route("/patients/<int:patient_id>/appointments/<int:appointment_id>/complete", methods=["POST"])
@role_required("professional")
def complete_appointment(patient_id, appointment_id):
    store, auth_store = get_followup_appointment_store(), get_authorization_store()
    try:
        followup_appointments.complete(store, auth_store, g.user["user_id"], appointment_id, clock.now_utc())
    except followup_appointments.NotAuthorizedError:
        abort(404)
    flash("Appointment marked complete.", "success")
    return redirect(url_for("authorization.patient_history", patient_id=patient_id))


@authorization_bp.route("/patients/<int:patient_id>/appointments/<int:appointment_id>/delete", methods=["POST"])
@role_required("professional")
def delete_appointment(patient_id, appointment_id):
    store, auth_store = get_followup_appointment_store(), get_authorization_store()
    try:
        followup_appointments.delete(store, auth_store, g.user["user_id"], appointment_id)
    except followup_appointments.NotAuthorizedError:
        abort(404)
    flash("Appointment deleted.", "success")
    return redirect(url_for("authorization.patient_history", patient_id=patient_id))


REVIEW_NOTE_ONLY = "note"
REVIEW_WITH_FOLLOW_UP = "note_follow_up"


@authorization_bp.route("/patients/<int:patient_id>/review", methods=["POST"])
@role_required("professional")
def add_review(patient_id):
    """
    The one place a professional reviews a shared result: a clinical note on its own, or a clinical note together with
    a follow-up appointment (and, if they tick it, permission for the patient to screen again right away).
    Everything is checked first and nothing is saved unless all of it is valid, so a note is never saved without the
    follow-up that was meant to go with it. A problem shows the form again with everything that was typed.
    """
    if not authorizations.is_authorized(get_authorization_store(), patient_id, g.user["user_id"]):
        abort(404)
    form = request.form
    try:
        assessment_id = int(form.get("assessment_id", ""))
    except ValueError:
        abort(400)
    # The result must be THIS patient's: a note is never attached to anyone else's result by changing the number.
    if get_assessment_store().get_assessment(patient_id, assessment_id) is None:
        abort(404)
    mode = form.get("mode") or REVIEW_NOTE_ONLY
    if mode not in (REVIEW_NOTE_ONLY, REVIEW_WITH_FOLLOW_UP):
        abort(400)

    zone, now = current_app.config["APP_TIMEZONE"], clock.now_utc()
    errors = {}
    note = (form.get("note") or "").strip()
    if not note:
        errors["note"] = "Write your clinical note."
    elif len(note) > clinical_reviews.MAX_NOTE_LENGTH:
        errors["note"] = f"The note is longer than {clinical_reviews.MAX_NOTE_LENGTH} characters."
    scheduled_at, purpose, notes = None, (form.get("purpose") or "").strip(), (form.get("notes") or "").strip()
    if mode == REVIEW_WITH_FOLLOW_UP:
        try:
            scheduled_at = _parse_local_datetime(form, zone)
            if scheduled_at < now:
                errors["date"] = "Choose a date and time in the future."
        except ValueError as error:
            errors["date"] = str(error)
        if not purpose:
            errors["purpose"] = "Enter what the follow-up is for."
        elif len(purpose) > followup_appointments.MAX_PURPOSE_LENGTH:
            errors["purpose"] = f"The purpose is longer than {followup_appointments.MAX_PURPOSE_LENGTH} characters."
        if len(notes) > followup_appointments.MAX_NOTES_LENGTH:
            errors["notes"] = f"The notes are longer than {followup_appointments.MAX_NOTES_LENGTH} characters."
    if errors:
        return _history_page(patient_id, review_form=form, review_errors=errors)

    try:
        clinical_reviews.add_review(get_clinical_review_store(), get_authorization_store(), g.user, assessment_id, patient_id, note, now)
        notifications.notify_clinical_review_added(get_notification_store(), patient_id, g.user["full_name"], assessment_id, now)
        message = "Your note was added."
        if mode == REVIEW_WITH_FOLLOW_UP:
            followup_appointments.schedule(get_followup_appointment_store(), get_authorization_store(), g.user, patient_id,
                                           scheduled_at, purpose, notes, now)
            notifications.notify_follow_up_requested(get_notification_store(), patient_id, g.user["full_name"],
                                                     f"Appointment scheduled: {purpose}", now)
            message = "Your note was added and the follow-up appointment was scheduled."
            if form.get("rescreen") == "1" and not followups.open_request(get_followup_store(), patient_id):
                followups.request_followup(get_followup_store(), get_authorization_store(), g.user, patient_id, purpose, now)
                message = "Your note was added, the follow-up appointment was scheduled, and they can screen again now."
    except (clinical_reviews.NotAuthorizedError, followup_appointments.NotAuthorizedError, followups.NotAuthorizedError):
        abort(404)                                     # the patient ended the sharing a moment ago
    flash(message, "success")
    current_app.logger.info("Clinical review added (patient_user_id=%s, professional_user_id=%s, assessment_id=%s, with_follow_up=%s)",
                            patient_id, g.user["user_id"], assessment_id, mode == REVIEW_WITH_FOLLOW_UP)
    return redirect(url_for("authorization.patient_history", patient_id=patient_id) + f"#assessment-{assessment_id}")


@authorization_bp.route("/patients/<int:patient_id>/follow-up", methods=["POST"])
@role_required("professional")
def request_followup(patient_id):
    auth_store = get_authorization_store()
    try:
        followups.request_followup(get_followup_store(), auth_store, g.user, patient_id, request.form.get("message", ""), clock.now_utc())
    except followups.NotAuthorizedError:
        abort(404)
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("authorization.patient_history", patient_id=patient_id))
    flash("Follow-up requested.", "success")
    notifications.notify_follow_up_requested(get_notification_store(), patient_id, g.user["full_name"], request.form.get("message", ""), clock.now_utc())
    current_app.logger.info("Follow-up requested (patient_user_id=%s, professional_user_id=%s)", patient_id, g.user["user_id"])
    return redirect(url_for("authorization.patient_history", patient_id=patient_id))


@authorization_bp.route("/follow-up-cases")
@role_required("professional")
def follow_up_cases():
    """Section 40-43: every follow-up appointment this professional has scheduled, across every patient -
    searchable and filterable by status and date. Kept apart from /follow-up, which is a PATIENT's own page."""
    term = request.args.get("q", "").strip()
    status = request.args.get("status") or None
    date_period = request.args.get("date_period") or professional_overview.DATE_ALL
    valid_periods = (professional_overview.DATE_TODAY, professional_overview.DATE_THIS_WEEK,
                     professional_overview.DATE_THIS_MONTH, professional_overview.DATE_ALL)
    if date_period not in valid_periods:
        date_period = professional_overview.DATE_ALL
    zone = current_app.config["APP_TIMEZONE"]
    stores = (get_patient_records_store(), get_authorization_store(), get_user_store(), get_followup_appointment_store(),
              g.user["user_id"], zone, clock.now_utc())
    rows = professional_overview.follow_up_list(*stores, term=term, status=status, date_period=date_period)

    # The calendar shows every one of this professional's appointments for the viewed month (not narrowed by the
    # table's filters - it is the whole schedule), each labelled with its own patient.
    today = clock.local_today(zone)
    year, month = followup_calendar.viewed_month(request.args, today)
    previous_month, next_month = followup_calendar.neighbours(year, month)
    weeks = followup_calendar.month_grid(year, month, professional_overview.follow_up_list(*stores), today)
    return render_template("authorizations/follow_up_cases.html", page_title="Follow-up", records=rows,
                           query=term, status=status, date_period=date_period, weeks=weeks,
                           month_label=date(year, month, 1).strftime("%B %Y"), previous_month=previous_month, next_month=next_month)


@authorization_bp.route("/patients/<int:patient_id>/connection")
@role_required("professional")
def manage_connection(patient_id):
    """Section 7: a focused page for the relationship itself - when it was requested and accepted, and the one
    control that manages it (ending access) - separate from the history page's own inline button."""
    auth_store, user_store = get_authorization_store(), get_user_store()
    if not authorizations.is_authorized(auth_store, patient_id, g.user["user_id"]):
        abort(404)                                     # not authorized, or no such patient: the same answer
    patient = user_store.find_by_id(patient_id)
    if patient is None:
        abort(404)
    zone = current_app.config["APP_TIMEZONE"]
    (row,) = [r for r in authorizations.describe_for_professional(auth_store, user_store, g.user["user_id"], statuses={"accepted"})
             if r["patient_user_id"] == patient_id]
    requested_date = clock.to_local_date(row["requested_at"], zone)
    accepted_date = clock.to_local_date(row["responded_at"], zone) if row["responded_at"] else None
    return render_template("authorizations/manage_connection.html", page_title=f"Manage connection with {patient['full_name']}",
                           patient=patient, requested_date=requested_date, accepted_date=accepted_date)



@authorization_bp.route("/review-queue")
@role_required("professional")
def review_queue():
    """Professional review: shared assessments waiting for this professional's clinical note, and the ones already
    reviewed. "Write review" jumps straight to that result's own note form on the patient's history page."""
    status = request.args.get("status") or "awaiting_review"
    if status not in ("awaiting_review", "reviewed"):
        status = "awaiting_review"
    args = (get_authorization_store(), get_user_store(), get_assessment_store(), get_clinical_review_store(),
            g.user["user_id"], current_app.config["APP_TIMEZONE"])
    awaiting = professional_overview.shared_assessment_list(*args, review_status="awaiting_review")
    reviewed = professional_overview.shared_assessment_list(*args, review_status="reviewed")
    return render_template("authorizations/review_queue.html", page_title="Professional review", status=status,
                           records=awaiting if status == "awaiting_review" else reviewed,
                           counts={"awaiting_review": len(awaiting), "reviewed": len(reviewed)})
