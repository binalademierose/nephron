"""
main_routes.py - public pages that need no login: home, about, health check.
"""
from flask import Blueprint, abort, current_app, jsonify, render_template

import db
from services import clock

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    return render_template("main/home.html", page_title="Kidney health risk screening")


@main_bp.route("/about")
def about():
    return render_template("main/about.html", page_title="How Nephron works")


@main_bp.route("/terms")
def terms():
    """Terms & Conditions. Public, no sign-in needed - it must be readable before someone creates an account."""
    effective = clock.local_today(current_app.config["APP_TIMEZONE"]).strftime("%B %Y")
    return render_template("legal/terms.html", page_title="Terms & Conditions", effective_date=effective)


@main_bp.route("/faq")
def faq():
    """Frequently asked questions. Public, no sign-in needed."""
    return render_template("legal/faq.html", page_title="Frequently asked questions")


@main_bp.route("/health")
def health():
    """
    Used to check that the app and MySQL are working. It reveals no details:
    the technical reason for a failure is written to logs/nephron.log only.
    """
    is_connected, _ = db.check_database_connection()
    if is_connected:
        return jsonify(status="ok", database="connected"), 200
    return jsonify(status="degraded", database="unavailable"), 503


@main_bp.route("/style-guide")
def style_guide():
    """Shows every design-system component. Available only while FLASK_DEBUG=1."""
    if not current_app.debug:
        abort(404)
    return render_template("main/style_guide.html", page_title="Style guide")
