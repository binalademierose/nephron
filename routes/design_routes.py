"""
design_routes.py - DESIGN PREVIEWS. Available only while FLASK_DEBUG=1.

These pages show how screens that are built in later phases will look and behave
(sign-in, register, dashboard, guided assessment, result, empty/loading/error states).
They never touch the database and are never registered when FLASK_DEBUG is off.

ABOUT THE DATA
  Nephron's rule is: never show a number that did not come from a real assessment.
  * The dashboard preview opens in its REAL state: a new person with no assessments,
    so charts are replaced by empty states.
  * To judge the populated design, add  ?data=sample  to the address. That fills the page
    with made-up records, every chart carries a visible "Sample data" tag, and every number
    still goes through services/visuals.py, the same code real data will use.
  * The result page has nothing to show without a result, so it always uses sample values
    and says so on the page.
"""
from datetime import date, timedelta

from flask import Blueprint, current_app, render_template, request, url_for

from services import visuals
from services import explanations
from services import ckd_facts

design_bp = Blueprint("design", __name__, url_prefix="/design")

# ----- Design-review sample data (never shown outside these previews) -----
SAMPLE_THRESHOLD = 21          # sample. The real threshold comes from the model artifact.
SAMPLE_REASSESSMENT_DAYS = 30  # sample. Nephron has not fixed a real waiting time yet.
SAMPLE_EFFECTS = [                # sample. In the real result these come from the loaded model, for one person's own answers.
    {"name": "Diabetes", "effect": 1.9},
    {"name": "Age", "effect": 1.1},
    {"name": "Hypertension", "effect": 0.6},
    {"name": "Physical_Activity_Level", "effect": -0.4},
    {"name": "Smoking_Status", "effect": -0.2},
]
SAMPLE_ANSWERS = {"Diabetes": 1, "Age": 63, "Hypertension": 1, "Physical_Activity_Level": "Active", "Smoking_Status": "Never"}


def sample_assessments(today):
    """Three made-up assessments, dated relative to today so the preview never goes stale."""
    return [
        {"date": today - timedelta(days=5), "assessment_type": "preliminary", "type": "Preliminary screening", "probability": 31.0, "level": "high", "threshold": SAMPLE_THRESHOLD},
        {"date": today - timedelta(days=45), "assessment_type": "enhanced", "type": "Enhanced screening", "probability": 18.0, "level": "low", "threshold": SAMPLE_THRESHOLD},
        {"date": today - timedelta(days=99), "assessment_type": "preliminary", "type": "Preliminary screening", "probability": 15.0, "level": "low", "threshold": SAMPLE_THRESHOLD},
    ]


@design_bp.route("/")
def index():
    return render_template("design/index.html", page_title="Design previews")


@design_bp.route("/login")
def login():
    state = "error" if request.args.get("state") == "error" else "default"
    return render_template("design/login.html", page_title="Sign in (preview)", state=state)


@design_bp.route("/register")
def register():
    return render_template("design/register.html", page_title="Create an account (preview)")


@design_bp.route("/dashboard")
def dashboard():
    today = date.today()
    use_sample = request.args.get("data") == "sample"
    assessments = sample_assessments(today) if use_sample else []
    # ?locked=1 shows the state where the waiting period between screenings has not passed yet
    locked = use_sample and request.args.get("locked") == "1"
    summary = visuals.summarize_assessments(
        assessments, today=today,
        reassessment_days=SAMPLE_REASSESSMENT_DAYS if locked else None,
    )
    trend = visuals.trend_geometry(summary["oldest_first"], SAMPLE_THRESHOLD) if summary["has_trend"] else None
    follow_up_count = 0    # follow-up records arrive in a later phase
    return render_template(
        "design/dashboard.html",
        page_title="Overview (preview)",
        data_toggle=True,
        is_sample=use_sample,
        summary=summary,
        trend=trend,
        path_labels=visuals.PATH_STEPS,
        path_done=visuals.screening_path(summary["total"], follow_up_count),
        message=visuals.summary_message(summary["low_count"], summary["high_count"]),
        activity=visuals.activity_items(summary["newest_first"]),
        result_urls={},
        ckd_facts=ckd_facts.all_facts(),
        profile={"initials": "SU", "full_name": "Sample User", "role_label": "General User"},
        # In the preview every link works or says it is a preview. In the real dashboard, links to things that are
        # not built yet are None (shown as "Coming soon").
        links={"start": url_for("design.assessment"), "history": "preview", "activity": "preview", "upload": "preview",
               "reports": "preview", "share": "preview", "profile": "preview", "about_ckd": "preview", "philhealth": "preview",
               "model_info": url_for("main.about"), "tips": "preview"},
    )


@design_bp.route("/assessment")
def assessment():
    return render_template("design/assessment.html", page_title="Guided screening (preview)")


@design_bp.route("/result")
def result():
    level = "low" if request.args.get("level") == "low" else "high"
    today = date.today()
    current = {"high": 31.0, "low": 12.0}[level]
    records = [
        {"date": today - timedelta(days=45), "type": "Preliminary screening", "probability": 18.0, "level": "low"},
        {"date": today - timedelta(days=5), "type": "Preliminary screening", "probability": current, "level": level},
    ]
    summary = visuals.summarize_assessments(records, today=today, reassessment_days=SAMPLE_REASSESSMENT_DAYS)
    return render_template(
        "design/result.html",
        page_title="Result (preview)",
        level=level,
        summary=summary,
        threshold=SAMPLE_THRESHOLD,
        explanation=explanations.build(current_app.extensions["catalog"], SAMPLE_EFFECTS, SAMPLE_ANSWERS),
        today=today,
    )


@design_bp.route("/states")
def states():
    # The responsive-table demo needs some rows. They are the same made-up sample records as the dashboard.
    return render_template(
        "design/states.html",
        page_title="Empty, loading and error states (preview)",
        history=visuals.summarize_assessments(sample_assessments(date.today()))["newest_first"],
    )
