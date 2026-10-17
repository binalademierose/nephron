"""
auth_hooks.py - the code that runs on EVERY request, before or after the page's own code.

  1. Who is signed in?  The session cookie only holds a user number. The person's details and role are read
     from the database each time, so a change in the database takes effect immediately.
  2. CSRF protection.   Every form that changes something (POST) must carry the secret token from the session.
  3. No caching.        Private pages are marked "no-store", so pressing Back after signing out does not
     show them again.
"""
from datetime import datetime

import mysql.connector
from flask import abort, current_app, flash, g, redirect, request, session, url_for

from services import auth_service, security
from services.user_store import get_user_store

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")      # these only READ, so they need no CSRF token
PRIVATE_BLUEPRINTS = ("auth", "account")


def landing_url(user):
    """The home page for this person's role."""
    if user.get("is_admin"):
        return url_for("admin.dashboard")
    return url_for("account.professional_home" if user["role"] == "professional" else "account.dashboard")


def start_session(user_id, now):
    """
    Sign a person in. The old session is thrown away first, so nothing an earlier visitor left in it
    (including a CSRF token an attacker might know) carries over into the signed-in session.
    """
    session.clear()
    session["user_id"] = user_id
    session["issued_at"] = now.isoformat()
    session.permanent = True                   # expires after SESSION_LIFETIME_MINUTES without activity


def _session_is_current(user):
    """A session created before the password was last changed is no longer valid."""
    try:
        issued_at = datetime.fromisoformat(session.get("issued_at"))
    except (TypeError, ValueError):
        return False
    changed_at = user["password_changed_at"]
    return changed_at is None or issued_at >= changed_at


def register_auth_hooks(app):
    @app.before_request
    def load_current_user():
        g.user = None
        g.user_lookup_failed = False
        if request.endpoint == "static":
            return
        user_id = session.get("user_id")
        if user_id is None:
            return
        try:
            user = get_user_store().find_by_id(user_id)
        except mysql.connector.Error as error:
            # Public pages keep working; pages that need a signed-in person show the "unavailable" page.
            current_app.logger.error("Could not look up the signed-in user: %s", error)
            g.user_lookup_failed = True
            return
        if user is None or user["is_patient_record"] or not user.get("is_active", True) or not _session_is_current(user):
            # A patient_record shadow account (services/patient_records.py) can never be "signed in" as anybody -
            # its session is treated exactly like one that does not exist, before anything else even runs.
            session.clear()
            return
        g.user = auth_service.describe(user)

    @app.before_request
    def replace_a_temporary_password_first():
        """After an administrator's password reset, the person signs in with a temporary password and must choose
        their own before anything else: every other page sends them to their account page."""
        user = g.get("user")
        if not user or not user.get("must_change_password"):
            return None
        allowed = {"account.settings", "account.change_password", "auth.logout", "static"}
        if request.endpoint in allowed or request.endpoint is None:
            return None
        flash("Please choose a new password to finish signing in - the one you used was temporary.", "warning")
        return redirect(url_for("account.settings"))

    @app.before_request
    def reject_forms_without_the_secret_token():
        if request.method in SAFE_METHODS or request.endpoint == "static":
            return
        if request.routing_exception is not None:
            return          # no such page, or the wrong method: let Flask answer 404 / 405 instead of a misleading "expired"
        if not security.csrf_is_valid(request.form.get("csrf_token")):
            current_app.logger.warning("Rejected %s %s: missing or wrong CSRF token", request.method, request.path)
            abort(400)

    @app.after_request
    def keep_private_pages_out_of_the_cache(response):
        if g.get("user") is not None or request.blueprint in PRIVATE_BLUEPRINTS:
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.context_processor
    def inject_signed_in_person():
        return {"current_user": g.get("user"), "screening_available": current_app.extensions["model_service"].ready}
