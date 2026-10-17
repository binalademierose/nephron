"""
auth_routes.py - creating an account, signing in and signing out.
"""
from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for

from routes.auth_hooks import landing_url, start_session
from services import activity, auth_service, clock, security
from services.user_store import DuplicateEmailError, DuplicateUsernameError, get_user_store
from services.validation import PROFESSIONS, clean_email, validate_registration

auth_bp = Blueprint("auth", __name__)

REGISTER_FIELDS = ("role", "full_name", "email", "username", "date_of_birth", "address", "avatar",
                  "profession_title", "institution", "license_number")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(landing_url(g.user))

    if request.method == "GET":
        return _show_register({}, {"role": "general"})

    values, errors = validate_registration(request.form)
    if not errors:
        store, now = get_user_store(), clock.now_utc()
        try:
            user_id = auth_service.register(store, values, now)
        except DuplicateEmailError:
            errors["email"] = "An account with this email already exists. Try signing in instead."
        except DuplicateUsernameError:
            errors["username"] = "That username is already taken. Try another one."
        else:
            store.mark_login(user_id, now)
            start_session(user_id, now)
            current_app.logger.info("New %s account created (user_id=%s)", values["role"], user_id)
            activity.record("registered", user_id, user_id, "Healthcare Professional" if values["role"] == "professional" else "General User")
            flash("Your account is ready. Welcome to Nephron.", "success")
            return redirect(landing_url(values))
    # Show the form again with what they typed (never the password) and a message beside each problem.
    return _show_register(errors, {field: request.form.get(field, "") for field in REGISTER_FIELDS})


def _show_register(errors, form):
    return render_template("auth/register.html", page_title="Create your account",
                           errors=errors, form=form, professions=PROFESSIONS)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(landing_url(g.user))
    next_url = request.values.get("next", "")

    if request.method == "GET":
        return _show_login("", {}, next_url)

    email = clean_email(request.form.get("email"))
    password = request.form.get("password") or ""
    errors = {}
    if not email:
        errors["email"] = "Enter your email address."
    if not password:
        errors["password"] = "Enter your password."
    if errors:
        return _show_login(email, errors, next_url)

    config = current_app.config
    status, user = auth_service.authenticate(
        get_user_store(), email, password, security.client_ip(), clock.now_utc(),
        config["LOGIN_MAX_FAILURES"], config["LOGIN_LOCK_MINUTES"],
    )
    if status == auth_service.LOGIN_OK:
        start_session(user["user_id"], clock.now_utc())
        flash(f"Welcome back, {auth_service.describe(user)['first_name']}. You are signed in.", "success")
        current_app.logger.info("Signed in (user_id=%s)", user["user_id"])
        activity.record("signed_in", user["user_id"], user["user_id"])
        return redirect(security.safe_next_url(next_url, landing_url(user)))

    if status == auth_service.LOGIN_INACTIVE:
        current_app.logger.warning("Sign-in refused: account deactivated (ip=%s)", security.client_ip())
        return _show_login(email, {}, next_url, notice="inactive"), 403

    if status == auth_service.LOGIN_LOCKED:
        current_app.logger.warning("Sign-in refused: too many failed attempts (ip=%s)", security.client_ip())
        return _show_login(email, {}, next_url, notice="locked"), 429

    current_app.logger.warning("Failed sign-in attempt (ip=%s)", security.client_ip())
    known = get_user_store().find_by_email(email) if email else None
    activity.record("sign_in_failed", None, known["user_id"] if known and not known.get("is_patient_record") else None,
                    None if known else "No account uses this email address")
    return _show_login(email, {}, next_url, notice="failed")


def _show_login(email, errors, next_url, notice=None):
    return render_template("auth/login.html", page_title="Sign in", email=email, errors=errors,
                           next_url=next_url, notice=notice, lock_minutes=current_app.config["LOGIN_LOCK_MINUTES"])


@auth_bp.route("/logout", methods=["POST"])
def logout():
    if g.get("user"):
        activity.record("signed_out", g.user["user_id"], g.user["user_id"])
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))
