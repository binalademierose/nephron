"""
authorizations.py - the rules for a patient sharing their assessment history with a professional.

services/authorization_store.py only ever does what it is told; this decides whether it may happen: a patient may
only request a real, professional account, and never their own; only the professional side may accept or decline a
'pending' request; either side may end an 'accepted' one. Searching for a professional to request is
services/user_store.py's own search_professionals() - nothing here changes how that works.
"""


class NotAProfessionalError(ValueError):
    """The account a patient tried to request is not a professional account (or does not exist at all)."""


def request_authorization(auth_store, user_store, patient_user_id, professional_user_id, now):
    """
    A patient asks a professional for access to their assessment history. Reuses the same row and moves it back to
    'pending' if this pair has a declined or revoked history (see authorization_store's own docstring); does
    nothing new if a request between them is already 'pending' or already 'accepted' (the store's own UPSERT
    still runs, but the practical effect is a no-op: pending stays pending, accepted is not something this call
    is ever offered for by the routes that call it).
    Raises NotAProfessionalError if professional_user_id is not a real professional account, or ValueError for a
    patient requesting their own account.
    """
    if professional_user_id == patient_user_id:
        raise ValueError("You cannot request access to your own account.")
    professional = user_store.find_by_id(professional_user_id)
    if professional is None or professional["role"] != "professional":
        raise NotAProfessionalError(professional_user_id)
    return auth_store.request(patient_user_id, professional_user_id, now)


def respond_to_request(auth_store, patient_user_id, professional_user_id, accept, now):
    """The professional answers a 'pending' request. True if it actually changed something (it was really pending);
    False if it had already been answered, withdrawn, or never asked - the caller decides what that means."""
    if accept:
        return auth_store.accept(patient_user_id, professional_user_id, now)
    return auth_store.decline(patient_user_id, professional_user_id, now)


def revoke(auth_store, patient_user_id, professional_user_id, now):
    """Either side ends an 'accepted' authorization. True only if one was really 'accepted' to begin with."""
    return auth_store.revoke(patient_user_id, professional_user_id, now)


def is_authorized(auth_store, patient_user_id, professional_user_id):
    """True only when the CURRENT status between them is 'accepted' - a past acceptance that was later revoked, or
    a request that is still only 'pending', is never treated as authorization."""
    row = auth_store.get(patient_user_id, professional_user_id)
    return row is not None and row["status"] == "accepted"


def describe_for_patient(auth_store, user_store, patient_user_id):
    """This patient's own authorizations, newest request first, each with the professional's own name/profession/
    institution attached for display. A row whose professional account no longer exists is left out."""
    described = []
    for row in auth_store.list_for_patient(patient_user_id):
        professional = user_store.find_by_id(row["professional_user_id"])
        if professional is None:
            continue
        described.append({**row, "professional_name": professional["full_name"],
                          "profession_title": professional.get("profession_title"), "institution": professional.get("institution")})
    return described


def describe_for_professional(auth_store, user_store, professional_user_id, statuses=None):
    """This professional's own authorizations, newest request first, each with the patient's own name/email
    attached for display. A row whose patient account no longer exists is left out."""
    described = []
    for row in auth_store.list_for_professional(professional_user_id, statuses=statuses):
        patient = user_store.find_by_id(row["patient_user_id"])
        if patient is None:
            continue
        described.append({**row, "patient_name": patient["full_name"], "patient_email": patient["email"]})
    return described
