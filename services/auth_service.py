"""
auth_service.py - the rules of registering, signing in and changing a password.

These functions take a `store` (see user_store.py) and the current time as arguments, so they contain no Flask
and no SQL, and a test can give them a fake clock.
"""
from datetime import timedelta

from services.security import DUMMY_HASH, hash_password, verify_password
from services.validation import ROLE_LABELS, first_name, initials

LOGIN_OK = "ok"
LOGIN_FAILED = "failed"
LOGIN_LOCKED = "locked"
LOGIN_INACTIVE = "inactive"        # the right password, but an administrator has switched the account off

KEEP_ATTEMPTS_FOR = timedelta(days=30)


def register(store, values, now):
    """Create the account. Raises DuplicateEmailError if the email is taken. Returns the new user_id."""
    return store.create_user(values, hash_password(values["password"]), now)


def authenticate(store, email, password, ip_address, now, max_failures, lock_minutes):
    """
    Try to sign in. Returns (status, user):
      (LOGIN_OK, user)      the email and password are right
      (LOGIN_FAILED, None)  wrong email or wrong password (the caller must not say which)
      (LOGIN_LOCKED, None)  too many recent failures for this email; the password is not even checked

    Being locked out only depends on how many failures were recorded for the email TEXT, so an email that has no
    account is locked out in exactly the same way as one that has, and nothing reveals which are registered.
    """
    store.delete_old_login_attempts(now - KEEP_ATTEMPTS_FOR)
    recent = store.count_failed_attempts(email, now - timedelta(minutes=lock_minutes))
    if recent >= max_failures:
        return LOGIN_LOCKED, None

    user = store.find_by_email(email)
    # Always check a hash, even when there is no such account (see DUMMY_HASH in security.py).
    password_is_right = verify_password(user["password_hash"] if user else DUMMY_HASH, password)

    if user is not None and password_is_right and user["is_patient_record"]:
        # Defense in depth: a patient_record's password is an unguessable secret nobody is ever told (see
        # services/patient_records.py), so this should never actually happen - but routes/auth_hooks.py is the
        # layer that actually matters (it refuses the session outright); this is a second, independent refusal.
        store.record_login_attempt(email, ip_address, False, now)
        return LOGIN_FAILED, None

    if user is not None and password_is_right and not user.get("is_active", True):
        # Said only once the password is right, so a deactivated account is never revealed to someone guessing.
        store.record_login_attempt(email, ip_address, False, now)
        return LOGIN_INACTIVE, None

    if user is not None and password_is_right:
        store.clear_failed_attempts(email)
        store.record_login_attempt(email, ip_address, True, now)
        store.mark_login(user["user_id"], now)
        return LOGIN_OK, user

    store.record_login_attempt(email, ip_address, False, now)
    return LOGIN_FAILED, None


CHANGE_OK = "ok"
CHANGE_WRONG = "wrong-current-password"
CHANGE_LOCKED = "locked"


def change_password(store, user_id, current_password, new_password, ip_address, now, max_failures, lock_minutes):
    """
    Change the password if the current one is right. Returns CHANGE_OK, CHANGE_WRONG or CHANGE_LOCKED.

    Someone who got hold of an open session could otherwise guess the current password here without limit,
    so wrong guesses count towards the same lock as wrong sign-ins for this email.
    """
    user = store.find_by_id(user_id)
    email = user["email"]
    if store.count_failed_attempts(email, now - timedelta(minutes=lock_minutes)) >= max_failures:
        return CHANGE_LOCKED
    if not verify_password(user["password_hash"], current_password):
        store.record_login_attempt(email, ip_address, False, now)
        return CHANGE_WRONG
    store.update_password(user_id, hash_password(new_password), now)
    return CHANGE_OK


def reset_password(store, email, new_password, now):
    """
    Set a new password for an account WITHOUT the old one. Only reset_password.py (run from a terminal by
    whoever runs the system) calls this; no web page can. It also removes any sign-in lock and signs the
    account out everywhere. Returns False if there is no such account.
    """
    user = store.find_by_email(email)
    if user is None:
        return False
    store.update_password(user["user_id"], hash_password(new_password), now)
    store.clear_failed_attempts(email)
    return True


def describe(user):
    """A copy of the user with the extra words the pages need (greeting name, initials, role label)."""
    person = dict(user)
    person.pop("password_hash", None)          # the hash never goes into a page
    person["first_name"] = first_name(user["full_name"])
    person["initials"] = initials(user["full_name"])
    if user.get("is_admin"):
        person["role"] = "admin"          # stored role is unchanged (migrations never MODIFY the ENUM): see migration 019
    person["role_label"] = ROLE_LABELS[person["role"]]
    return person
