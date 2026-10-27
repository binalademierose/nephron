"""
account_routes.py - pages for people who are signed in: their home page, and their account.

Each role has its own home page. The role is read from the database (never from the URL or a form), and a
person of the other role who opens it gets "Access not allowed".
"""
from datetime import timedelta

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for

from routes.auth_hooks import start_session
from routes.decorators import login_required, role_required
from services.security import verify_password
from services import activity, assessments, auth_service, checklist, ckd_facts, clock, community_stats, followups, professional_overview, reassessment, screening_contract, screening_drafts, security, visuals
from services.assessment_store import get_assessment_store
from services.checklist_store import get_checklist_store
from services.authorization_store import get_authorization_store
from services.clinical_review_store import get_clinical_review_store
from services.followup_appointment_store import get_followup_appointment_store
from services.followup_store import get_followup_store
from services.reassessment_store import get_reassessment_store
from services.patient_records_store import get_patient_records_store
from services.screening_draft_store import get_screening_draft_store
from services.user_store import get_user_store
from services.validation import validate_password_change

account_bp = Blueprint("account", __name__)


@account_bp.route("/dashboard")
@role_required("general")
def dashboard():
    """
    The General User's overview. Everything on it is worked out from THIS person's saved assessments
    (services/assessments.py reads them, services/visuals.py turns them into numbers and charts).
    With no assessments every card shows an honest empty state.
    """
    config = current_app.config
    records = assessments.load_records(get_assessment_store(), g.user["user_id"], config["APP_TIMEZONE"])
    followup_requests = followups.open_request(get_followup_store(), g.user["user_id"])
    follow_up_count = len(get_followup_store().list_for_patient(g.user["user_id"]))
    summary = visuals.summarize_assessments(
        records, today=clock.local_today(config["APP_TIMEZONE"]), reassessment_days=reassessment.current_period(),
        follow_up_open=followup_requests is not None,
    )
    latest = summary["latest"]
    trend = visuals.trend_geometry(summary["oldest_first"], latest["threshold"]) if summary["has_trend"] else None
    # The kidney-health checklist resets every day: show how yesterday went and how today is going.
    checklist_days, checklist_groups = None, []
    if records:
        store = get_assessment_store()
        newest = store.get_assessment(g.user["user_id"], records[0]["assessment_id"])
        if newest and newest["inputs"]:
            today = clock.local_today(config["APP_TIMEZONE"])
            args = (get_checklist_store(), newest["inputs"], newest["classification"], g.user["user_id"])
            checklist_days = {"yesterday": checklist.day_summary(*args, today - timedelta(days=1)),
                              "today": checklist.day_summary(*args, today)}
            # Today's list itself, shown right under that summary card (templates/partials/_checklist.html).
            checklist_groups = checklist.for_user(*args, today)
    checklist_done, checklist_total = checklist.progress(checklist_groups)
    return render_template(
        "account/dashboard.html", checklist_days=checklist_days,
        checklist_groups=checklist_groups, checklist_done=checklist_done, checklist_total=checklist_total,
        page_title="Overview",
        is_sample=False,
        summary=summary,
        trend=trend,
        path_labels=visuals.PATH_STEPS,
        path_done=visuals.screening_path(summary["total"], follow_up_count),
        message=visuals.summary_message(summary["low_count"], summary["high_count"]),
        activity=visuals.activity_items(summary["newest_first"]),
        open_follow_up=followup_requests, admin_opening=reassessment.is_admin_opening(followup_requests),
        admin_request=get_reassessment_store().latest_for(g.user["user_id"]),
        ckd_facts=ckd_facts.all_facts(),
        community=community_stats.philippines(get_assessment_store().latest_profiles(), screening_contract.load_catalog()),
        drafts=screening_drafts.describe_for_dashboard(get_screening_draft_store(), g.user["user_id"], config["APP_TIMEZONE"],
                                                       {"preliminary": [step["key"] for step in screening_contract.load_catalog()["steps"]]}),
        profile=g.user,
        # None = not built yet (shown as "Coming soon"). Each of these becomes a real address in the phase that builds it.
        result_urls={r["assessment_id"]: url_for("screening.result", assessment_id=r["assessment_id"]) for r in records},
        links={"start": url_for("screening.screening") if current_app.extensions["model_service"].ready else None, "history": url_for("history.index"), "activity": url_for("history.index"), "upload": url_for("lab.start"), "reports": url_for("reports.patient_reports"), "share": url_for("authorization.share"),
               "profile": url_for("account.settings"), "about_ckd": None, "philhealth": url_for("resources.philhealth_directory"), "model_info": url_for("main.about"), "tips": url_for("followup.index") + "#checklist-heading", "follow_up": url_for("followup.index")},
    )


@account_bp.route("/professional")
@role_required("professional")
def professional_home():
    overview = professional_overview.dashboard(
        get_patient_records_store(), get_authorization_store(), get_user_store(), get_assessment_store(),
        get_clinical_review_store(), get_followup_appointment_store(), g.user["user_id"], current_app.config["APP_TIMEZONE"],
    )
    insights = professional_overview.patient_insights(
        get_patient_records_store(), get_authorization_store(), get_user_store(), get_assessment_store(),
        g.user["user_id"], current_app.config["APP_TIMEZONE"],
    )
    community = community_stats.philippines(get_assessment_store().latest_profiles(), screening_contract.load_catalog())
    return render_template("account/professional_home.html", page_title="Home", overview=overview, insights=insights,
                           community=community, ckd_facts=ckd_facts.all_facts())


@account_bp.route("/search")
@role_required("professional")
def professional_search():
    term = request.args.get("q", "").strip()
    results = professional_overview.search(
        get_patient_records_store(), get_authorization_store(), get_user_store(), get_assessment_store(),
        g.user["user_id"], term, current_app.config["APP_TIMEZONE"],
    )
    return render_template("account/search.html", page_title="Search", query=term, results=results)


@account_bp.route("/account")
@login_required
def settings():
    return render_template("account/settings.html", page_title="Your account", errors={})


@account_bp.route("/account/location", methods=["POST"])
@role_required("general")
def save_location():
    """A General User living in the Philippines says where: the province, and for Pangasinan the town and barangay."""
    from services import ph_locations
    me = get_user_store().find_by_id(g.user["user_id"])
    values, errors = ph_locations.validate(me.get("country"), request.form)
    if errors:
        return render_template("account/settings.html", page_title="Your account", errors={},
                               location_values=request.form, location_errors=errors), 200
    get_user_store().set_location(g.user["user_id"], values)
    activity.record("location_updated", g.user["user_id"], g.user["user_id"])
    flash("Saved where you live. Thank you - it helps local health officials, without your name.", "success")
    return redirect(url_for("account.settings") + "#location")


@account_bp.route("/account/password", methods=["POST"])
@login_required
def change_password():
    current_password = request.form.get("current_password") or ""
    new_password = request.form.get("new_password") or ""
    errors = validate_password_change(current_password, new_password, g.user["email"], g.user["full_name"])

    if not errors:
        config, store, now = current_app.config, get_user_store(), clock.now_utc()
        status = auth_service.change_password(
            store, g.user["user_id"], current_password, new_password, security.client_ip(), now,
            config["LOGIN_MAX_FAILURES"], config["LOGIN_LOCK_MINUTES"],
        )
        if status == auth_service.CHANGE_OK:
            # Every session made before now stops working; this one is renewed so the person stays signed in.
            start_session(g.user["user_id"], now)
            current_app.logger.info("Password changed (user_id=%s)", g.user["user_id"])
            store.set_must_change(g.user["user_id"], False)          # a temporary password from an administrator is now replaced
            activity.record("password_changed", g.user["user_id"], g.user["user_id"])
            flash("Your password was changed. Any other device that was signed in has been signed out.", "success")
            return redirect(url_for("account.settings"))
        if status == auth_service.CHANGE_LOCKED:
            errors["current_password"] = "Too many wrong attempts. Please wait a while and try again."
        else:
            errors["current_password"] = "That is not your current password."
    return render_template("account/settings.html", page_title="Your account", errors=errors)


@account_bp.route("/account/deactivate", methods=["POST"])
@role_required("general", "professional")
def deactivate_account():
    """Switch off your own account. Your data is kept; you cannot sign in again until an administrator reactivates
    it. The password is re-checked so a borrowed, signed-in device cannot deactivate the account."""
    password = request.form.get("password") or ""
    me = get_user_store().find_by_id(g.user["user_id"])
    if not me or not verify_password(me["password_hash"], password):
        return render_template("account/settings.html", page_title="Your account", errors={},
                               danger_error="deactivate", danger_message="That is not your current password."), 200
    get_user_store().set_active(g.user["user_id"], False)
    activity.record("account_self_deactivated", g.user["user_id"], g.user["user_id"])
    current_app.logger.info("Account self-deactivated (user_id=%s)", g.user["user_id"])
    session.clear()
    flash("Your account has been deactivated. Contact the administrator if you want it switched back on.", "success")
    return redirect(url_for("auth.login"))


@account_bp.route("/account/delete", methods=["POST"])
@role_required("general", "professional")
def delete_account():
    """Permanently delete your own account and your own data. Requires the password and an explicit confirmation.
    This cannot be undone."""
    password = request.form.get("password") or ""
    confirmed = (request.form.get("confirm_delete") or "").strip().lower() in ("on", "yes", "true", "1", "delete")
    me = get_user_store().find_by_id(g.user["user_id"])
    if not me or not verify_password(me["password_hash"], password):
        return render_template("account/settings.html", page_title="Your account", errors={},
                               danger_error="delete", danger_message="That is not your current password."), 200
    if not confirmed:
        return render_template("account/settings.html", page_title="Your account", errors={},
                               danger_error="delete", danger_message="Tick the box to confirm you want to permanently delete your account."), 200
    user_id = g.user["user_id"]
    # Record the audit entry before the row is gone (the log keeps it, with the person's id set to NULL afterwards).
    activity.record("account_self_deleted", user_id, user_id)
    current_app.logger.info("Account self-deleted (user_id=%s)", user_id)
    get_user_store().delete_user(user_id)
    session.clear()
    flash("Your account and your data have been permanently deleted.", "success")
    return redirect(url_for("main.home"))
