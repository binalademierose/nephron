"""
notification_routes.py - the dedicated /notifications page, and marking/deleting one's own notifications.

Every route here only ever touches the SIGNED-IN person's own notifications - services/notification_store.py's
own user_id check is the real guard (never trusted from the URL alone), matching every other per-person store
in this app.
"""
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for, g

from routes.decorators import login_required
from services import clock, notifications
from services.notification_store import get_notification_store

notification_bp = Blueprint("notifications", __name__)


@notification_bp.route("/notifications")
@login_required
def index():
    store = get_notification_store()
    zone = current_app.config["APP_TIMEZONE"]
    items = notifications.all_for_user(store, g.user["user_id"], zone)
    return render_template("notifications/index.html", page_title="Notifications", items=items)


@notification_bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def mark_read(notification_id):
    store = get_notification_store()
    if not store.set_read(notification_id, g.user["user_id"], True):
        abort(404)
    return redirect(request.referrer or url_for("notifications.index"))


@notification_bp.route("/notifications/<int:notification_id>/unread", methods=["POST"])
@login_required
def mark_unread(notification_id):
    store = get_notification_store()
    if not store.set_read(notification_id, g.user["user_id"], False):
        abort(404)
    return redirect(request.referrer or url_for("notifications.index"))


@notification_bp.route("/notifications/<int:notification_id>/delete", methods=["POST"])
@login_required
def delete(notification_id):
    store = get_notification_store()
    if not store.delete(notification_id, g.user["user_id"]):
        abort(404)
    flash("Notification deleted.", "success")
    return redirect(request.referrer or url_for("notifications.index"))


@notification_bp.route("/notifications/mark-all-read", methods=["POST"])
@login_required
def mark_all_read():
    store = get_notification_store()
    store.mark_all_read(g.user["user_id"])
    return redirect(request.referrer or url_for("notifications.index"))
