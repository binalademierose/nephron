"""
admin_routes.py - the administrator side: an overview, account management, and professional licence checks.

An administrator manages ACCOUNTS (who can sign in, which professionals are verified), the re-assessment rule, and
the models. It never sees a named person's screening answers, probabilities or results (services/admin_overview.py):
health information reaches it only as totals, and as the de-identified, predictor-only Research Data export.
For a re-assessment request it sees who asked, when, the reason they typed, and the date of their last screening.
Every change is a POST with a CSRF token, confirmed in the page first, and written to the log with who did it.
"""
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from routes.decorators import role_required
import secrets

from services import activity, admin_overview, clock, community_stats, location_heatmap, model_design, model_insights, reassessment, screening_contract, security
from services.assessment_store import get_assessment_store
from services.activity_store import get_activity_store
from services.followup_store import get_followup_store
from services.notification_store import get_notification_store
from services.reassessment_store import get_reassessment_store
from services.user_store import get_user_store

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _account_or_404(user_id):
    account = get_user_store().find_by_id(user_id)
    if account is None or account.get("is_patient_record"):
        abort(404)
    return account


@admin_bp.route("")
@role_required("admin")
def dashboard():
    accounts = get_user_store().list_accounts()
    model, stage2 = current_app.extensions.get("model_service"), current_app.extensions.get("model_service_stage2")
    now = clock.now_utc()
    return render_template("admin/dashboard.html", page_title="Administrator",
                           kpis=admin_overview.user_kpis(accounts, now, timezone_name=current_app.config["APP_TIMEZONE"]),
                           risk=admin_overview.risk_by_age(get_assessment_store().latest_per_person()),
                           philippines=community_stats.philippines(get_assessment_store().latest_profiles(),
                                                                   screening_contract.load_catalog(), min_people=1),
                           counts=admin_overview.account_counts(accounts),
                           usage=admin_overview.assessment_counts(get_assessment_store(), clock.now_utc()),
                           recent_accounts=accounts[:6],
                           models=[("Preliminary Screening", model), ("Enhanced Screening", stage2)])


@admin_bp.route("/users")
@role_required("admin")
def users():
    term, role, status = request.args.get("q", "").strip(), request.args.get("role") or None, request.args.get("status") or None
    accounts = get_user_store().list_accounts()
    rows = admin_overview.filter_accounts(accounts, term, role, status)
    return render_template("admin/users.html", page_title="Accounts", accounts=rows, total=len(accounts),
                           query=term, role=role, status=status, role_of=admin_overview.role_of)


def _set_active(user_id, active):
    account = _account_or_404(user_id)
    if account["user_id"] == g.user["user_id"]:
        flash("You cannot switch off your own account.", "error")
        return redirect(url_for("admin.users"))
    get_user_store().set_active(account["user_id"], active)
    activity.record("account_reactivated" if active else "account_deactivated", g.user["user_id"], account["user_id"])
    current_app.logger.info("Account %s by administrator (user_id=%s, admin_user_id=%s)",
                            "reactivated" if active else "deactivated", account["user_id"], g.user["user_id"])
    flash(f"{account['full_name']}'s account is {'active again' if active else 'switched off'}.", "success")
    return redirect(security.safe_next_url(request.form.get("next"), url_for("admin.users")))   # never an off-site redirect


@admin_bp.route("/users/<int:user_id>/deactivate", methods=["POST"])
@role_required("admin")
def deactivate(user_id):
    return _set_active(user_id, False)


@admin_bp.route("/users/<int:user_id>/reactivate", methods=["POST"])
@role_required("admin")
def reactivate(user_id):
    return _set_active(user_id, True)


@admin_bp.route("/professionals")
@role_required("admin")
def professionals():
    status = request.args.get("status") or "pending"
    if status not in admin_overview.VERIFICATION + ("all",):
        status = "pending"
    accounts = get_user_store().list_accounts()
    everyone = admin_overview.professionals(accounts)
    counts = {key: len(admin_overview.professionals(accounts, key)) for key in admin_overview.VERIFICATION}
    counts["all"] = len(everyone)
    rows = everyone if status == "all" else admin_overview.professionals(accounts, status)
    return render_template("admin/professionals.html", page_title="Professional verification",
                           professionals=rows, status=status, counts=counts)


def _set_verification(user_id, decision):
    account = _account_or_404(user_id)
    if admin_overview.role_of(account) != "professional":
        abort(404)
    get_user_store().set_verification(account["user_id"], decision, clock.now_utc())
    activity.record("professional_verified" if decision == "verified" else "professional_rejected", g.user["user_id"], account["user_id"],
                    f"Licence {account.get('license_number') or '(none given)'}")
    current_app.logger.info("Professional %s by administrator (user_id=%s, admin_user_id=%s)", decision, account["user_id"], g.user["user_id"])
    flash(f"{account['full_name']} is now {'verified' if decision == 'verified' else 'marked as not verified'}.", "success")
    return redirect(url_for("admin.professionals", status=request.form.get("back") or "pending"))


@admin_bp.route("/professionals/<int:user_id>/verify", methods=["POST"])
@role_required("admin")
def verify(user_id):
    return _set_verification(user_id, "verified")


@admin_bp.route("/professionals/<int:user_id>/reject", methods=["POST"])
@role_required("admin")
def reject(user_id):
    return _set_verification(user_id, "rejected")



@admin_bp.route("/reassessment")
@role_required("admin")
def reassessment_page():
    """The re-assessment rule: the waiting period between screenings, and people's requests to screen again early."""
    store, zone = get_reassessment_store(), current_app.config["APP_TIMEZONE"]
    accounts = {a["user_id"]: a for a in get_user_store().list_accounts()}
    assessment_store = get_assessment_store()
    period = reassessment.current_period()

    def described(row):
        person = accounts.get(row["user_id"]) or {}
        last = assessment_store.list_assessments(row["user_id"])
        last_date = clock.to_local_date(last[0]["assessed_at"], zone) if last else None
        return {**row, "name": person.get("full_name") or "Removed account", "email": person.get("email") or "",
                "requested_date": clock.to_local_date(row["requested_at"], zone),
                "decided_date": clock.to_local_date(row["decided_at"], zone) if row.get("decided_at") else None,
                "last_screening": last_date, "opens_on": period.opens_on(last_date) if (period and last_date) else None}

    pending = [described(r) for r in store.list("pending")]
    decided = [described(r) for r in store.list() if r["status"] != "pending"][:20]
    return render_template("admin/reassessment.html", page_title="Re-assessment rule", months=store.get_months(),
                           period=period, env_days=current_app.config.get("REASSESSMENT_DAYS"),
                           choices=reassessment.MONTH_CHOICES, pending=pending, decided=decided)


@admin_bp.route("/reassessment/rule", methods=["POST"])
@role_required("admin")
def reassessment_rule():
    try:
        months = reassessment.set_months(get_reassessment_store(), request.form.get("months"), g.user["user_id"], clock.now_utc())
    except reassessment.RequestError as error:
        flash(str(error), "error")
        return redirect(url_for("admin.reassessment_page"))
    label = f"{months} month{'' if months == 1 else 's'}" if months else "no waiting period"
    activity.record("reassessment_rule_changed", g.user["user_id"], None, f"Set to {label}")
    flash(f"The waiting period between screenings is now {label}.", "success")
    return redirect(url_for("admin.reassessment_page"))


@admin_bp.route("/reassessment/<int:request_id>/<decision>", methods=["POST"])
@role_required("admin")
def reassessment_decide(request_id, decision):
    if decision not in ("approve", "decline"):
        abort(404)
    store, now = get_reassessment_store(), clock.now_utc()
    try:
        if decision == "approve":
            row = reassessment.approve(store, get_followup_store(), get_notification_store(), g.user, request_id, now)
        else:
            row = reassessment.decline(store, get_notification_store(), g.user, request_id, now)
    except reassessment.RequestError as error:
        flash(str(error), "error")
        return redirect(url_for("admin.reassessment_page"))
    person = get_user_store().find_by_id(row["user_id"]) or {}
    name = person.get("full_name") or "This person"
    flash(f"{name} can now take one screening early." if decision == "approve" else f"{name}'s request was declined.", "success")
    return redirect(url_for("admin.reassessment_page"))


@admin_bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@role_required("admin")
def reset_password(user_id):
    """A temporary password, shown ONCE on the page this returns (never stored readable, never emailed, never in a
    flash message or a URL). Every open session of that account ends, and at the next sign-in the person must
    choose their own password before doing anything else (routes/auth_hooks.py)."""
    account = _account_or_404(user_id)
    if account["user_id"] == g.user["user_id"]:
        flash("Change your own password on your account page.", "error")
        return redirect(url_for("admin.users"))
    temporary = "-".join(secrets.token_urlsafe(6) for _ in range(2))         # e.g. "q7Kd9_Lm-Xp2aZ0w": ~96 bits
    store = get_user_store()
    store.update_password(account["user_id"], security.hash_password(temporary), clock.now_utc())   # ends every session
    store.set_must_change(account["user_id"], True)
    activity.record("password_reset", g.user["user_id"], account["user_id"])
    current_app.logger.info("Password reset by administrator (user_id=%s, admin_user_id=%s)", account["user_id"], g.user["user_id"])
    response = current_app.make_response(render_template("admin/reset_done.html", page_title="Temporary password",
                                                         account=account, temporary=temporary))
    response.headers["Cache-Control"] = "no-store"                            # the password is never kept by the browser
    return response


@admin_bp.route("/activity")
@role_required("admin")
def activity_log():
    group, term = request.args.get("group") or None, request.args.get("q", "").strip()
    rows = activity.describe(get_activity_store().recent(), get_user_store())
    shown = activity.filter_rows(rows, group, term)
    return render_template("admin/activity.html", page_title="Activity log", rows=shown, total=len(rows),
                           group=group, query=term, groups=activity.GROUPS)



@admin_bp.route("/guide")
@role_required("admin")
def guide():
    return render_template("admin/guide.html", page_title="Administrator guide")



def _input_labels():
    """Short, readable names for every model input: the screening questions, the lab values, and eGFR."""
    from services import lab_contract, screening_contract
    labels = {q["name"]: q["short"] for q in screening_contract.load_catalog()["questions"]}
    labels.update({f["name"]: f["label"] for f in lab_contract.load_lab_catalog()["fields"]})
    labels.setdefault("eGFR", "eGFR (kidney filtration)")
    return labels


def _models(labels):
    """Both installed models with what the admin pages show about them: readiness, measured metrics, importance
    and the model card. Shared by Model performance, How the models work, and Model comparison."""
    config = current_app.config
    models = []
    for key, title, service, folder, stage in (
            ("preliminary", "Preliminary Screening", current_app.extensions.get("model_service"), config["MODEL_DIR"], "1"),
            ("enhanced", "Enhanced Screening", current_app.extensions.get("model_service_stage2"), config["MODEL_STAGE2_DIR"], "2")):
        folder = getattr(service, "model_dir", None) or folder          # the folder of the model actually loaded
        metrics = model_insights.load_metrics(folder)
        meta = getattr(service, "metadata", None) or {}
        models.append({
            "key": key, "title": title, "stage": stage, "ready": bool(service and service.ready), "service": service,
            "reason": getattr(service, "reason", None), "checks": getattr(service, "checks", []) or [],
            "metrics": metrics, "roc": model_insights.roc_polyline(metrics),
            "all_importance": model_insights.importance(service, labels),
            "facts": model_insights.facts(service), "warning": meta.get("near_circular_warning"), "meta": meta,
            "features": meta.get("features", []) if service and service.ready else [],
            "test_csv": "ml\\validation_holdout.csv" if stage == "1" else "ml\\stage2_sealed_test.csv",
        })
        models[-1]["importance"] = models[-1]["all_importance"][:15]
    return models


@admin_bp.route("/model")
@role_required("admin")
def model():
    """Each model's performance (from model_report.py on labelled data), what drives it overall, and its model card."""
    models = _models(_input_labels())
    return render_template("admin/model.html", page_title="Model performance", models=models)


def _input_groups(model, catalog, lab_catalog):
    """Where a model's inputs come from, in the order a person meets them."""
    from services.model_service_stage2 import STAGE1_LIKE_FIELDS
    if model["stage"] == "1":
        groups = [(step["title"], [q["name"] for q in catalog["questions"] if q["step"] == step["key"]]) for step in catalog["steps"]]
    else:
        lab_groups = {g["key"]: g.get("title", g["key"]) for g in lab_catalog.get("groups", [])} if isinstance(lab_catalog.get("groups"), list) else {}
        groups = [("From the Preliminary Screening", list(STAGE1_LIKE_FIELDS)), ("Calculated: eGFR", ["eGFR"])]
        for key, title in lab_groups.items():
            groups.append((f"Lab: {title}", [f["name"] for f in lab_catalog["fields"] if f.get("group") == key]))
        groups.append(("Lab values", [f["name"] for f in lab_catalog["fields"]]))
    return model_design.input_groups(model["features"], model["all_importance"], groups)


@admin_bp.route("/model/how-it-works")
@role_required("admin")
def model_design_page():
    """How each model turns answers into a result: its pipeline step by step, where its inputs and weight come
    from, how its scores are spread for people with and without CKD, and what moving the threshold would do."""
    from services import lab_contract
    labels, catalog, lab_catalog = _input_labels(), screening_contract.load_catalog(), lab_contract.load_lab_catalog()
    models = _models(labels)
    for m in models:
        if m["stage"] == "1":
            title, detail = f"{len(m['features']) or len(catalog['questions'])} answers from the screening", \
                "About you, health history, medicines and lifestyle - no laboratory values."
        else:
            title, detail = f"{len(m['features']) or '-'} answers and lab values", \
                "The preliminary answers plus laboratory results; eGFR is calculated from creatinine, age and sex, never typed."
        m["steps"] = model_design.pipeline_steps(m["service"], title, detail)
        m["groups"] = _input_groups(m, catalog, lab_catalog) if m["features"] else []
        m["histogram"] = model_design.histogram(m["metrics"])
        m["tradeoff"] = model_design.tradeoff_lines(m["metrics"])
    return render_template("admin/model_design.html", page_title="How the models work", models=models)


@admin_bp.route("/map")
@role_required("admin")
def location_map():
    """Pangasinan, by municipality/city or by barangay: people screened, people at higher risk, or the share - totals
    per place only (services/location_heatmap.py). For the LGU: where screening has reached, and where risk is higher."""
    from services.patient_records_store import get_patient_records_store
    entries = location_heatmap.people(get_user_store(), get_patient_records_store(), get_assessment_store())
    data = location_heatmap.view(entries, request.args.get("metric", "share"), request.args.get("level", "municipality"),
                                 request.args.get("town") or None)
    return render_template("admin/map.html", page_title="Pangasinan map", map=data,
                           others=location_heatmap.other_provinces(entries))


@admin_bp.route("/research-data")
@role_required("admin")
def research_data():
    """De-identified screening answers (predictors only) for improving the model with real-world data later."""
    from services import research_export
    store, stage2 = get_assessment_store(), current_app.extensions.get("model_service_stage2")
    kinds = []
    for key, title in research_export.TYPES.items():
        cols = research_export.columns(key, stage2)
        kinds.append({"key": key, "title": title, "columns": cols,
                      "people": len(store.saved_answers(key, latest_only=True)), "screenings": len(store.saved_answers(key, latest_only=False))})
    return render_template("admin/research_data.html", page_title="Research data", kinds=kinds, age_cap=research_export.AGE_CAP)


@admin_bp.route("/research-data/<assessment_type>.csv")
@role_required("admin")
def research_data_csv(assessment_type):
    from services import research_export
    if assessment_type not in research_export.TYPES:
        abort(404)
    latest_only = request.args.get("all") != "1"
    cols = research_export.columns(assessment_type, current_app.extensions.get("model_service_stage2"))
    data = research_export.rows(get_assessment_store(), assessment_type, cols, latest_only)
    activity.record("research_export", g.user["user_id"], None,
                    f"{research_export.TYPES[assessment_type]}: {len(data)} rows ({'latest per person' if latest_only else 'every screening'})")
    name = f"nephron_{assessment_type}_deidentified_{clock.now_utc():%Y%m%d}.csv"
    response = current_app.response_class(research_export.to_csv(cols, data), mimetype="text/csv")
    response.headers["Content-Disposition"] = f'attachment; filename="{name}"'
    response.headers["Cache-Control"] = "no-store"
    return response
