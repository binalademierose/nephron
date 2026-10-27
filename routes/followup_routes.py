"""
followup_routes.py - the patient's own Follow-up screen: a calendar of appointments a professional has scheduled
for them, and their personalized kidney-health checklist. Nothing here is editable by the patient except the
checklist's own checked/unchecked state - scheduling itself is the professional's own action
(routes/authorization_routes.py).
"""
from datetime import date

from flask import Blueprint, current_app, g, jsonify, redirect, render_template, request, url_for

from routes.decorators import role_required
from services import checklist, clock, followup_appointments, followup_calendar, security
from services.assessment_store import get_assessment_store
from services.checklist_store import get_checklist_store
from services.followup_appointment_store import get_followup_appointment_store

followup_bp = Blueprint("followup", __name__)


def _latest_inputs_and_classification(user_id):
    """The person's most recent assessment's own saved inputs and classification - the same two things a
    checklist and the result page's own tips panel are both built from. (None, None) if they have none yet."""
    store = get_assessment_store()
    rows = store.list_assessments(user_id)              # a summary only - no "inputs" column, by design
    if not rows:
        return None, None
    latest = store.get_assessment(user_id, rows[0]["assessment_id"])   # the one call that also joins the saved answers
    return latest["inputs"], latest["classification"]


@followup_bp.route("/follow-up")
@role_required("general")
def index():
    zone = current_app.config["APP_TIMEZONE"]
    appointments = followup_appointments.for_patient(get_followup_appointment_store(), g.user["user_id"], zone)
    today = clock.local_today(zone)
    year, month = followup_calendar.viewed_month(request.args, today)
    weeks = followup_calendar.month_grid(year, month, appointments, today)
    previous_month, next_month = followup_calendar.neighbours(year, month)

    inputs, level = _latest_inputs_and_classification(g.user["user_id"])
    grouped = checklist.for_user(get_checklist_store(), inputs, level, g.user["user_id"], today) if inputs is not None else []
    done, total = checklist.progress(grouped)
    return render_template("followup/index.html", page_title="Follow-up", appointments=appointments,
                           weeks=weeks, month_label=date(year, month, 1).strftime("%B %Y"),
                           previous_month=previous_month, next_month=next_month, viewed_year=year, viewed_month=month,
                           checklist_groups=grouped, checklist_done=done, checklist_total=total,
                           has_assessment=inputs is not None)


@followup_bp.route("/follow-up/checklist/<tip_id>", methods=["POST"])
@role_required("general")
def toggle_checklist_item(tip_id):
    """Tick or untick one task on today's list. The checklist appears on both the dashboard and the Follow-up page:
    a plain form post goes back to the page it came from ("next", checked to stay on this site); the page's own
    script (static/js/checklist.js) asks for JSON instead and gets today's real totals back to show."""
    is_complete = request.form.get("is_complete") == "1"
    today = clock.local_today(current_app.config["APP_TIMEZONE"])
    checklist.toggle(get_checklist_store(), g.user["user_id"], tip_id, is_complete, clock.now_utc(), today)   # today's own list
    if request.headers.get("X-Requested-With") == "fetch":
        inputs, level = _latest_inputs_and_classification(g.user["user_id"])
        grouped = checklist.for_user(get_checklist_store(), inputs, level, g.user["user_id"], today) if inputs is not None else []
        done, total = checklist.progress(grouped)
        return jsonify(ok=True, tip_id=tip_id, is_complete=is_complete, done=done, total=total)
    back = security.safe_next_url(request.form.get("next", ""), url_for("followup.index"))
    return redirect(back.split("#", 1)[0] + "#checklist")
