"""
history_routes.py - the history of a person's assessments, and the comparison of two of them.

Every assessment is a permanent row that only its owner can see. The history asks the store for THIS user's rows, and the comparison
opens each of the two ids through get_assessment(user_id, id): an id that belongs to someone else is answered exactly like an id
that does not exist (404). Nothing on these pages can change, add or delete an assessment.
"""
import re

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from routes.decorators import role_required
from services import assessments, clinical_reviews, clock, eligibility, followups, history, reassessment, visuals
from services.followup_store import get_followup_store
from services.assessment_store import get_assessment_store
from services.clinical_review_store import get_clinical_review_store

history_bp = Blueprint("history", __name__)

ID_PATTERN = re.compile(r"^\d{1,9}$", re.ASCII)


@history_bp.route("/history")
@role_required("general")
def index():
    config = current_app.config
    zone = config["APP_TIMEZONE"]
    records = assessments.load_records(get_assessment_store(), g.user["user_id"], zone)        # newest first
    today = clock.local_today(zone)
    period = reassessment.current_period()
    follow_up_open = followups.open_request(get_followup_store(), g.user["user_id"]) is not None
    summary = visuals.summarize_assessments(records, today=today, reassessment_days=period, follow_up_open=follow_up_open)
    status = eligibility.screening_status(records[0]["date"] if records else None, today, period,
                                          current_app.extensions["model_service"].ready, follow_up_open)
    latest = summary["latest"]
    # The History card shows the chart about twice as wide as the dashboard does: draw it at that size so its
    # text matches the page instead of being scaled up to double size.
    trend = visuals.trend_geometry(summary["oldest_first"], latest["threshold"], width=620, height=250) if summary["has_trend"] else None
    # For every row, the assessment just before it (used by "Compare with previous").
    previous_of = {records[i]["assessment_id"]: records[i + 1]["assessment_id"] for i in range(len(records) - 1)}
    return render_template(
        "history/index.html", page_title="Assessment history", summary=summary, status=status, trend=trend,
        page=history.paginate(records, request.args.get("page", 1, type=int)), previous_of=previous_of,
        first_id=records[-1]["assessment_id"] if len(records) > 1 else None, latest_id=records[0]["assessment_id"] if len(records) > 1 else None,
    )


def _two_ids(values):
    """Exactly two different whole numbers, or None."""
    if len(values) != 2 or not all(ID_PATTERN.match(value) for value in values):
        return None
    ids = [int(value) for value in values]
    return ids if ids[0] != ids[1] else None


@history_bp.route("/history/compare")
@role_required("general")
def compare():
    ids = _two_ids(request.args.getlist("id"))
    if ids is None:
        flash("Choose exactly two different assessments to compare.", "error")
        return redirect(url_for("history.index"))
    store = get_assessment_store()
    rows = [store.get_assessment(g.user["user_id"], assessment_id) for assessment_id in ids]
    if any(row is None for row in rows):
        abort(404)                                    # not yours, or it does not exist: the same answer
    comparison = history.compare(current_app.extensions["catalog"], rows[0], rows[1], current_app.config["APP_TIMEZONE"])
    return render_template("history/compare.html", page_title="Compare assessments", comparison=comparison)


@history_bp.route("/reviews")
@role_required("general")
def reviews():
    """Professional review: every clinical note a healthcare professional has written on this person's own
    assessments - newest result first. Results with no note yet are listed after, so nothing looks missing."""
    records = assessments.load_records(get_assessment_store(), g.user["user_id"], current_app.config["APP_TIMEZONE"])
    notes = clinical_reviews.for_assessments(get_clinical_review_store(), [r["assessment_id"] for r in records])
    reviewed = [{"record": r, "notes": notes.get(r["assessment_id"], [])} for r in records if notes.get(r["assessment_id"])]
    waiting = [r for r in records if not notes.get(r["assessment_id"])]
    return render_template("history/reviews.html", page_title="Professional review", reviewed=reviewed, waiting=waiting,
                           note_count=sum(len(item["notes"]) for item in reviewed))
