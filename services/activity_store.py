"""
activity_store.py - the administrator's activity log: what happened, who did it, to whom, and when.
Never anyone's health information. MySQL and in-memory versions with the same methods.
"""
from flask import current_app

import db


def get_activity_store():
    return current_app.extensions["activity_store"]


class MySQLActivityStore:
    def add(self, actor_user_id, action, target_user_id, details, now):
        db.execute("INSERT INTO activity_log (actor_user_id, action, target_user_id, details, created_at) VALUES (%s, %s, %s, %s, %s)",
                   (actor_user_id, action, target_user_id, (details or None) and details[:255], now))

    def recent(self, limit=300):
        """Newest first."""
        rows = db.query_all("SELECT activity_id, actor_user_id, action, target_user_id, details, created_at FROM activity_log "
                            "ORDER BY created_at DESC, activity_id DESC LIMIT %s", (limit,))
        return [dict(row) for row in rows]


class MemoryActivityStore:
    def __init__(self):
        self._rows = []

    def add(self, actor_user_id, action, target_user_id, details, now):
        self._rows.append({"activity_id": len(self._rows) + 1, "actor_user_id": actor_user_id, "action": action,
                           "target_user_id": target_user_id, "details": (details or None) and details[:255], "created_at": now})

    def recent(self, limit=300):
        return sorted(self._rows, key=lambda r: (r["created_at"], r["activity_id"]), reverse=True)[:limit]
