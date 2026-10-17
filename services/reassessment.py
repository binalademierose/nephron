"""
reassessment.py - the re-assessment rule: how long a General User waits between screenings, and who may let them
screen again early.

  * The administrator sets the waiting period in calendar months (1 to 12, or none). Until they save one,
    REASSESSMENT_DAYS from .env applies if it is set, and otherwise 3 months.
  * During the waiting period, ONE early screening is opened by an open follow-up request
    (services/followups.py), which comes from either:
      - any healthcare professional the person has authorized (Request follow-up on the patient's page), or
      - the administrator, approving the person's own request (ask_admin() / approve() below).
  * The next saved screening uses the opening up (followups.mark_fulfilled_by_new_assessment), so the normal waiting
    period applies again from that screening's date - until someone opens another one.

services/eligibility.py does the date arithmetic; this module only decides the period and handles the requests.
"""
from flask import current_app

from services import activity, eligibility, notifications

MONTH_CHOICES = tuple(range(1, 13))
DEFAULT_MONTHS = 3
MAX_REASON_LENGTH = 300
ADMIN_TITLE = "Administrator"
ADMIN_NAME = "The Nephron administrator"


class RequestError(ValueError):
    """The request cannot be made or decided (the message says why, in plain words)."""


def period_from(months, fallback_days, default_months=None):
    """months: the administrator's setting (None = never saved, 0 = no waiting period). fallback_days: .env's
    REASSESSMENT_DAYS. default_months: the rule when neither exists (3 on the real database)."""
    if months is not None:
        return eligibility.Period(months=months) if months > 0 else None
    if fallback_days:
        return eligibility.as_period(fallback_days)
    return eligibility.Period(months=default_months) if default_months else None


def current_period():
    """The waiting period in force right now (an eligibility.Period, or None for no waiting period)."""
    store = current_app.extensions.get("reassessment_store")
    months = store.get_months() if store is not None else None
    return period_from(months, current_app.config.get("REASSESSMENT_DAYS"), getattr(store, "default_months", None))


def saved_or_default_months(store):
    """What the administrator's page shows as chosen: the saved value, else the default (None if there is neither)."""
    months = store.get_months()
    return months if months is not None else getattr(store, "default_months", None)


def set_months(store, months, admin_user_id, now):
    """months: a whole number from MONTH_CHOICES, or 0 for no waiting period."""
    try:
        months = int(months)
    except (TypeError, ValueError):
        raise RequestError("Choose a waiting period from the list.")
    if months != 0 and months not in MONTH_CHOICES:
        raise RequestError("Choose a waiting period from the list.")
    store.set_months(months, admin_user_id, now)
    return months


def ask_admin(store, user_id, reason, waiting, now):
    """A General User asks the administrator to screen again early. waiting: True only while they are inside the
    waiting period (the caller works it out with eligibility). One pending request at a time."""
    if not waiting:
        raise RequestError("You can already screen again, so there is nothing to ask.")
    reason = (reason or "").strip() or None
    if reason and len(reason) > MAX_REASON_LENGTH:
        raise RequestError(f"Please keep the reason to {MAX_REASON_LENGTH} characters.")
    latest = store.latest_for(user_id)
    if latest and latest["status"] == "pending":
        raise RequestError("Your request is already with the administrator.")
    return store.add_request(user_id, reason, now)


def approve(store, followup_store, notification_store, admin, request_id, now):
    """Opens ONE early screening for the person who asked. Returns the request."""
    request_row = _pending(store, request_id)
    if not store.decide(request_id, "approved", admin["user_id"], now):
        raise RequestError("This request was already decided.")
    message = "Your request to screen again early was approved. You can take one screening now; after it, the usual waiting period applies again."
    followup_store.request(request_row["user_id"], admin["user_id"], ADMIN_NAME, ADMIN_TITLE, message, now)
    notifications.notify_reassessment_decision(notification_store, request_row["user_id"], True, now)
    activity.record("reassessment_approved", admin["user_id"], request_row["user_id"])
    return request_row


def decline(store, notification_store, admin, request_id, now):
    request_row = _pending(store, request_id)
    if not store.decide(request_id, "declined", admin["user_id"], now):
        raise RequestError("This request was already decided.")
    notifications.notify_reassessment_decision(notification_store, request_row["user_id"], False, now)
    activity.record("reassessment_declined", admin["user_id"], request_row["user_id"])
    return request_row


def screening_saved(store, user_id, now):
    """Call after a new screening is saved: a request still waiting for the administrator is no longer needed."""
    if store is not None:
        store.close_pending(user_id, now)


def _pending(store, request_id):
    row = store.get(request_id)
    if row is None:
        raise RequestError("That request no longer exists.")
    if row["status"] != "pending":
        raise RequestError("This request was already decided.")
    return row


def is_admin_opening(follow_up):
    """True when an open follow-up came from the administrator approving the person's own request."""
    return bool(follow_up) and follow_up.get("profession_title") == ADMIN_TITLE
