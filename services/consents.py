"""
consents.py - the rules around a patient's agreement to share their assessment history.

A share request is only ever created after the patient has actively agreed (the confirmation dialog on the
Share page, or its no-JavaScript checkbox) - routes/authorization_routes.py refuses the request otherwise, so
this is enforced on the server, not just on the page. Each agreement is recorded with the version of the wording
the person saw. CURRENT_VERSION must change whenever the consent text in
templates/authorizations/_consent_template.html changes in what it actually promises.
"""
from services import clock

CURRENT_VERSION = "share-history-v1"
SHARE_HISTORY = "share_history"


def given(form):
    """True only if the submitted form carries an explicit agreement - an empty or missing value is not one."""
    return "1" in form.getlist("consent")


def record_share_consent(store, patient_user_id, professional_user_id, now):
    return store.record(patient_user_id, professional_user_id, SHARE_HISTORY, CURRENT_VERSION, now)


def latest_dates_for_patient(store, patient_user_id, timezone_name):
    """{professional_user_id: local date of the patient's most recent agreement to share with them}."""
    latest = {}
    for row in store.list_for_patient(patient_user_id):            # newest first, so the first one seen wins
        latest.setdefault(row["professional_user_id"], clock.to_local_date(row["consented_at"], timezone_name))
    return latest
