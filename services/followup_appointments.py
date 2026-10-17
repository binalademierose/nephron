"""
followup_appointments.py - the rules for a professional's scheduled visit with their patient.

services/followup_appointment_store.py only ever does what it is told; this decides whether it may happen: only
a professional CURRENTLY authorized for the patient may schedule, reschedule, complete, cancel, or delete an
appointment (checked fresh every time, via services/authorizations.py - a past authorization that has since been
revoked is never enough). A purpose must be real text within a sane length; a date and time must be a real,
future moment.
"""
from datetime import timedelta

from services import authorizations, clock

MAX_PURPOSE_LENGTH = 200
MAX_NOTES_LENGTH = 1000


class NotAuthorizedError(ValueError):
    """The professional is not currently authorized for this patient (or does not own this appointment)."""


def _check_authorized(auth_store, patient_user_id, professional_user_id):
    if not authorizations.is_authorized(auth_store, patient_user_id, professional_user_id):
        raise NotAuthorizedError(patient_user_id)


def _check_fields(purpose, notes):
    purpose = (purpose or "").strip()
    if not purpose:
        raise ValueError("Enter what the follow-up is for.")
    if len(purpose) > MAX_PURPOSE_LENGTH:
        raise ValueError(f"The purpose is longer than {MAX_PURPOSE_LENGTH} characters.")
    notes = (notes or "").strip() or None
    if notes and len(notes) > MAX_NOTES_LENGTH:
        raise ValueError(f"The notes are longer than {MAX_NOTES_LENGTH} characters.")
    return purpose, notes


def schedule(store, auth_store, professional, patient_user_id, scheduled_at_utc, purpose, notes, now):
    """
    professional: the signed-in professional's own user row (g.user).
    scheduled_at_utc: already converted from the local date/time the professional typed - see routes/authorization_routes.py.
    Raises NotAuthorizedError, or ValueError for a blank/too-long purpose, over-long notes, or a moment in the past.
    """
    _check_authorized(auth_store, patient_user_id, professional["user_id"])
    purpose, notes = _check_fields(purpose, notes)
    if scheduled_at_utc < now:
        raise ValueError("Choose a date and time in the future.")
    return store.create(patient_user_id, professional["user_id"], professional["full_name"],
                        professional.get("profession_title"), scheduled_at_utc, purpose, notes, now)


def reschedule(store, auth_store, professional_user_id, appointment_id, scheduled_at_utc, purpose, notes, now):
    """True if it was really changed. Raises NotAuthorizedError if this professional does not own the appointment,
    or is no longer authorized for its patient; ValueError for the same field problems as schedule()."""
    row = store.get(appointment_id)
    if row is None or row["professional_user_id"] != professional_user_id:
        raise NotAuthorizedError(appointment_id)
    _check_authorized(auth_store, row["patient_user_id"], professional_user_id)
    purpose, notes = _check_fields(purpose, notes)
    if scheduled_at_utc < now:
        raise ValueError("Choose a date and time in the future.")
    return store.update(appointment_id, professional_user_id, scheduled_at_utc, purpose, notes, now)


def _set_status(store, auth_store, professional_user_id, appointment_id, status, now):
    row = store.get(appointment_id)
    if row is None or row["professional_user_id"] != professional_user_id:
        raise NotAuthorizedError(appointment_id)
    _check_authorized(auth_store, row["patient_user_id"], professional_user_id)
    return store.set_status(appointment_id, professional_user_id, status, now)


def cancel(store, auth_store, professional_user_id, appointment_id, now):
    return _set_status(store, auth_store, professional_user_id, appointment_id, "cancelled", now)


def complete(store, auth_store, professional_user_id, appointment_id, now):
    return _set_status(store, auth_store, professional_user_id, appointment_id, "completed", now)


def delete(store, auth_store, professional_user_id, appointment_id):
    row = store.get(appointment_id)
    if row is None or row["professional_user_id"] != professional_user_id:
        raise NotAuthorizedError(appointment_id)
    _check_authorized(auth_store, row["patient_user_id"], professional_user_id)
    return store.delete(appointment_id, professional_user_id)


def _described(rows, timezone_name):
    described = []
    for row in rows:
        local = clock.to_local_datetime(row["scheduled_at"], timezone_name)
        described.append({**row, "scheduled_local": local})
    return described


def for_patient(store, patient_user_id, timezone_name):
    return _described(store.list_for_patient(patient_user_id), timezone_name)


def for_professional(store, professional_user_id, timezone_name):
    """Every appointment this professional has scheduled, across every patient."""
    return _described(store.list_for_professional(professional_user_id), timezone_name)


def for_professional_patient(store, professional_user_id, patient_user_id, timezone_name):
    return _described(store.list_for_professional_patient(professional_user_id, patient_user_id), timezone_name)
