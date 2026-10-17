"""
followups.py - the rules for a professional asking their patient to screen again.

services/followup_store.py only ever does what it is told; this decides whether it may happen: only a professional
CURRENTLY authorized for that patient may request one (checked fresh every time, via services/authorizations.py),
and a message, if given, must be within a sane length. Marking a request fulfilled is meant to be called once,
right after routes/screening_routes.py or routes/lab_routes.py saves a NEW assessment for that patient - see
mark_fulfilled_by_new_assessment() below, which both call.
"""
from services import authorizations
from services.followup_store import MAX_MESSAGE_LENGTH


class NotAuthorizedError(ValueError):
    """The professional is not currently authorized for this patient."""


def request_followup(followup_store, auth_store, professional, patient_user_id, message, now):
    """
    professional: the signed-in professional's own user row (g.user), so its real, current name/title are the
    ones snapshotted.
    Raises NotAuthorizedError if professional is not currently authorized for patient_user_id, or ValueError for a
    message over followup_store.MAX_MESSAGE_LENGTH characters (a blank message is fine - the request itself is
    the point, a reason is optional).
    """
    if not authorizations.is_authorized(auth_store, patient_user_id, professional["user_id"]):
        raise NotAuthorizedError(patient_user_id)
    message = (message or "").strip() or None
    if message and len(message) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"The message is longer than {MAX_MESSAGE_LENGTH} characters.")
    return followup_store.request(patient_user_id, professional["user_id"], professional["full_name"],
                                  professional.get("profession_title"), message, now)


def mark_fulfilled_by_new_assessment(followup_store, patient_user_id, assessed_at):
    """Call this the moment a new assessment (either stage) is saved for patient_user_id: closes their open
    follow-up request, if there is one. Safe to call even when there is none (does nothing)."""
    followup_store.mark_fulfilled(patient_user_id, assessed_at)


def open_request(followup_store, patient_user_id):
    """This patient's open follow-up request, or None."""
    return followup_store.get_open(patient_user_id)
