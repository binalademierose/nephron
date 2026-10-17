"""
notifications.py - one function per real event that creates a notification, plus the read-side helpers.

Every notify_*() here is called from exactly one place (routes/authorization_routes.py, or services/reassessment.py), right where the real
event it describes is already being saved - never speculatively, never to make the bell look busier. Wording is
built here so it stays consistent and is covered by tests, not scattered as string-building across routes.
"""
from services import clock

MAX_RECENT = 5    # how many the header's dropdown preview shows


def notify_follow_up_requested(store, patient_user_id, professional_name, message, now):
    title = f"{professional_name} requested a follow-up screening"
    body = message or "Screen again when you're ready - the usual waiting period does not apply this time."
    store.create(patient_user_id, "follow_up", title, body, "/dashboard", now)


def notify_reassessment_decision(store, user_id, approved, now):
    """The administrator decided a person's request to screen again early (services/reassessment.py)."""
    if approved:
        store.create(user_id, "follow_up", "Your request to screen again early was approved",
                     "You can take one screening now. After it, the usual waiting period applies again.", "/screening", now)
    else:
        store.create(user_id, "follow_up", "Your request to screen again early was not approved",
                     "Your next screening opens when the usual waiting period ends.", "/dashboard", now)


def notify_clinical_review_added(store, patient_user_id, professional_name, assessment_id, now):
    title = f"{professional_name} added a note to one of your results"
    store.create(patient_user_id, "clinical_review", title, None, f"/results/{assessment_id}", now)


def notify_share_requested(store, professional_user_id, patient_name, now):
    title = f"{patient_name} wants to share their assessment history with you"
    store.create(professional_user_id, "share_request", title, None, "/patients", now)


def notify_share_response(store, patient_user_id, professional_name, accepted, now):
    verb = "accepted" if accepted else "declined"
    title = f"{professional_name} {verb} your share request"
    store.create(patient_user_id, "share_response", title, None, "/share", now)


def unread_count(store, user_id):
    return store.unread_count(user_id)


def recent_for_header(store, user_id, timezone_name):
    """The header dropdown's own short preview - the newest few, however many of them are unread or not."""
    return _described(store.list_for_user(user_id, limit=MAX_RECENT), timezone_name)


def all_for_user(store, user_id, timezone_name):
    """The full list, for the dedicated /notifications page."""
    return _described(store.list_for_user(user_id), timezone_name)


def _described(rows, timezone_name):
    return [{**row, "created_at_local": clock.to_local_datetime(row["created_at"], timezone_name)} for row in rows]
