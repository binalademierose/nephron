"""
clinical_reviews.py - the rules for a professional's note on one assessment.

services/clinical_review_store.py only ever does what it is told; this decides whether it may happen: only a
professional CURRENTLY authorized for the assessment's own owner may write one (checked fresh every time, via
services/authorizations.py - never trusted from an earlier visit), and a note must be real text within a sane length.
"""
from services import authorizations
from services.clinical_review_store import MAX_NOTE_LENGTH


class NotAuthorizedError(ValueError):
    """The professional is not currently authorized for this assessment's owner."""


def add_review(review_store, auth_store, professional, assessment_id, patient_user_id, note, now):
    """
    professional: the signed-in professional's own user row (g.user), so its real, current name/title are the
    ones snapshotted - never something the caller supplies separately and could get out of sync.
    Raises NotAuthorizedError if professional is not currently authorized for patient_user_id, or ValueError for a
    blank note or one over clinical_review_store.MAX_NOTE_LENGTH characters.
    """
    if not authorizations.is_authorized(auth_store, patient_user_id, professional["user_id"]):
        raise NotAuthorizedError(patient_user_id)
    note = (note or "").strip()
    if not note:
        raise ValueError("The note cannot be empty.")
    if len(note) > MAX_NOTE_LENGTH:
        raise ValueError(f"The note is longer than {MAX_NOTE_LENGTH} characters.")
    return review_store.add_review(assessment_id, professional["user_id"], professional["full_name"],
                                   professional.get("profession_title"), note, now)


def for_assessment(review_store, assessment_id):
    """Every review of one assessment, oldest first - the patient's own result page uses this directly; no
    authorization check here, since a patient always may see notes about their OWN assessment."""
    return review_store.list_for_assessment(assessment_id)


def for_assessments(review_store, assessment_ids):
    """The same, batched for a whole history page."""
    return review_store.list_for_assessments(assessment_ids)
