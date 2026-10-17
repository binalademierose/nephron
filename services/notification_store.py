"""
notification_store.py - one row per notification, for the person it is for.

Same MySQL + Memory pattern as the other stores. Every read and write here takes user_id and checks it - a
notification belongs to exactly one person, and this store never lets one person read, mark, or delete another's.
Business rules (which real event creates which notification, its wording) live in services/notifications.py.
"""
import mysql.connector
from flask import current_app

import db


def get_notification_store():
    return current_app.extensions["notification_store"]


class MySQLNotificationStore:
    def create(self, user_id, category, title, body, link, now):
        return db.execute(
            "INSERT INTO notifications (user_id, category, title, body, link, is_read, created_at) "
            "VALUES (%s, %s, %s, %s, %s, 0, %s)",
            (user_id, category, title, body, link, now),
        )

    def list_for_user(self, user_id, limit=None):
        sql = "SELECT notification_id, user_id, category, title, body, link, is_read, created_at FROM notifications WHERE user_id = %s ORDER BY created_at DESC, notification_id DESC"
        params = (user_id,)
        if limit is not None:
            sql += " LIMIT %s"
            params = (user_id, limit)
        return db.query_all(sql, params)

    def unread_count(self, user_id):
        row = db.query_one("SELECT COUNT(*) AS n FROM notifications WHERE user_id = %s AND is_read = 0", (user_id,))
        return row["n"]

    def get(self, notification_id, user_id):
        return db.query_one(
            "SELECT notification_id, user_id, category, title, body, link, is_read, created_at FROM notifications WHERE notification_id = %s AND user_id = %s",
            (notification_id, user_id),
        )

    def set_read(self, notification_id, user_id, is_read):
        with db.transaction() as cursor:
            cursor.execute("UPDATE notifications SET is_read = %s WHERE notification_id = %s AND user_id = %s",
                           (1 if is_read else 0, notification_id, user_id))
            return cursor.rowcount > 0

    def mark_all_read(self, user_id):
        with db.transaction() as cursor:
            cursor.execute("UPDATE notifications SET is_read = 1 WHERE user_id = %s AND is_read = 0", (user_id,))
            return cursor.rowcount

    def delete(self, notification_id, user_id):
        with db.transaction() as cursor:
            cursor.execute("DELETE FROM notifications WHERE notification_id = %s AND user_id = %s", (notification_id, user_id))
            return cursor.rowcount > 0


class MemoryNotificationStore:
    def __init__(self):
        self._rows = {}
        self._next_id = 1

    def create(self, user_id, category, title, body, link, now):
        notification_id = self._next_id
        self._next_id += 1
        self._rows[notification_id] = {
            "notification_id": notification_id, "user_id": user_id, "category": category,
            "title": title, "body": body, "link": link, "is_read": False, "created_at": now,
        }
        return notification_id

    def list_for_user(self, user_id, limit=None):
        mine = [dict(row) for row in self._rows.values() if row["user_id"] == user_id]
        mine.sort(key=lambda row: (row["created_at"], row["notification_id"]), reverse=True)
        return mine[:limit] if limit is not None else mine

    def unread_count(self, user_id):
        return sum(1 for row in self._rows.values() if row["user_id"] == user_id and not row["is_read"])

    def get(self, notification_id, user_id):
        row = self._rows.get(notification_id)
        return dict(row) if row and row["user_id"] == user_id else None

    def set_read(self, notification_id, user_id, is_read):
        row = self._rows.get(notification_id)
        if row is None or row["user_id"] != user_id:
            return False
        row["is_read"] = bool(is_read)
        return True

    def mark_all_read(self, user_id):
        changed = 0
        for row in self._rows.values():
            if row["user_id"] == user_id and not row["is_read"]:
                row["is_read"] = True
                changed += 1
        return changed

    def delete(self, notification_id, user_id):
        row = self._rows.get(notification_id)
        if row is None or row["user_id"] != user_id:
            return False
        del self._rows[notification_id]
        return True
