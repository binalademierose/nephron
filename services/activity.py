"""
activity.py - records the events an administrator may need to review, and describes them for the activity page.
Recording never breaks the request it describes: if the log cannot be written, the event is still in the
application log file, and the person's own action has already succeeded.
"""
from flask import current_app

from services import clock

LABELS = {
    "signed_in": "Signed in", "sign_in_failed": "Failed sign-in", "signed_out": "Signed out",
    "registered": "Created an account", "password_changed": "Changed their password",
    "account_deactivated": "Switched an account off", "account_reactivated": "Switched an account on",
    "professional_verified": "Verified a professional", "professional_rejected": "Marked a professional not verified",
    "password_reset": "Reset a password",
    "location_updated": "Updated where they live", "research_export": "Downloaded de-identified screening data",
    "reassessment_requested": "Asked to screen again early", "reassessment_approved": "Approved an early screening",
    "reassessment_declined": "Declined an early screening", "reassessment_rule_changed": "Changed the waiting period",
}
GROUPS = {"sign_in": ("signed_in", "sign_in_failed", "signed_out"), "accounts": ("registered", "password_changed", "location_updated", "reassessment_requested"),
          "admin": ("account_deactivated", "account_reactivated", "professional_verified", "professional_rejected", "password_reset", "research_export",
                    "reassessment_approved", "reassessment_declined", "reassessment_rule_changed")}


def record(action, actor_user_id=None, target_user_id=None, details=None):
    try:
        current_app.extensions["activity_store"].add(actor_user_id, action, target_user_id, details, clock.now_utc())
    except Exception as error:                      # the log must never break the action it records
        current_app.logger.error("Activity log could not be written (%s): %s: %s", action, type(error).__name__, error)


def describe(rows, user_store):
    """Rows with the people's names and the action's label, for the activity page."""
    people = {}

    def person(user_id):
        if user_id is None:
            return None
        if user_id not in people:
            found = user_store.find_by_id(user_id)
            people[user_id] = {"name": found["full_name"], "email": found["email"]} if found else {"name": "Removed account", "email": ""}
        return people[user_id]

    return [{**row, "label": LABELS.get(row["action"], row["action"]), "actor": person(row["actor_user_id"]),
             "target": person(row["target_user_id"])} for row in rows]


def filter_rows(rows, group=None, term=None):
    if group in GROUPS:
        rows = [r for r in rows if r["action"] in GROUPS[group]]
    term = (term or "").strip().lower()
    if term:
        def hay(r):
            parts = [r["details"] or "", r["label"]]
            for who in (r["actor"], r["target"]):
                if who:
                    parts += [who["name"], who["email"]]
            return " ".join(parts).lower()
        rows = [r for r in rows if term in hay(r)]
    return rows
