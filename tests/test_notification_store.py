"""
Checks for services/notification_store.py. The SAME checks run against two stores:
  * MemoryNotificationStore - always runs.
  * MySQLNotificationStore  - runs on the separate <DB_NAME>_test database. Skipped, with the reason, if MySQL is
                              not available.
"""
import os
import sys
import unittest
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mysql_support  # noqa: E402

from services.notification_store import MemoryNotificationStore, MySQLNotificationStore  # noqa: E402
from services.user_store import MemoryUserStore, MySQLUserStore  # noqa: E402

NOW = datetime(2026, 9, 20, 10, 0, 0)
LATER = datetime(2026, 9, 21, 10, 0, 0)


def setUpModule():
    mysql_support.prepare()


def tearDownModule():
    mysql_support.drop()


def new_user(users):
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    return users.create_user({"email": email, "full_name": "Ana Reyes", "role": "general", "professional": None}, "h", NOW)


class NotificationStoreContract:
    def make_stores(self):
        raise NotImplementedError

    def setUp(self):
        self.users, self.store = self.make_stores()
        self.user_id = new_user(self.users)

    def test_a_fresh_notification_is_read_back_unread(self):
        nid = self.store.create(self.user_id, "follow_up", "Title", "Body", "/somewhere", NOW)
        row = self.store.get(nid, self.user_id)
        self.assertEqual(row["title"], "Title")
        self.assertEqual(row["body"], "Body")
        self.assertEqual(row["link"], "/somewhere")
        self.assertEqual(row["category"], "follow_up")
        self.assertFalse(row["is_read"])
        self.assertEqual(row["created_at"], NOW)

    def test_body_and_link_are_optional(self):
        nid = self.store.create(self.user_id, "follow_up", "Title", None, None, NOW)
        row = self.store.get(nid, self.user_id)
        self.assertIsNone(row["body"])
        self.assertIsNone(row["link"])

    def test_list_for_user_is_newest_first(self):
        first = self.store.create(self.user_id, "follow_up", "First", None, None, NOW)
        second = self.store.create(self.user_id, "follow_up", "Second", None, None, LATER)
        ids = [row["notification_id"] for row in self.store.list_for_user(self.user_id)]
        self.assertEqual(ids, [second, first])

    def test_list_respects_a_limit(self):
        for _ in range(3):
            self.store.create(self.user_id, "follow_up", "One", None, None, NOW)
        self.assertEqual(len(self.store.list_for_user(self.user_id, limit=2)), 2)

    def test_unread_count_only_counts_unread(self):
        a = self.store.create(self.user_id, "follow_up", "A", None, None, NOW)
        self.store.create(self.user_id, "follow_up", "B", None, None, NOW)
        self.assertEqual(self.store.unread_count(self.user_id), 2)
        self.store.set_read(a, self.user_id, True)
        self.assertEqual(self.store.unread_count(self.user_id), 1)

    def test_set_read_and_unread_round_trip(self):
        nid = self.store.create(self.user_id, "follow_up", "A", None, None, NOW)
        self.assertTrue(self.store.set_read(nid, self.user_id, True))
        self.assertTrue(self.store.get(nid, self.user_id)["is_read"])
        self.assertTrue(self.store.set_read(nid, self.user_id, False))
        self.assertFalse(self.store.get(nid, self.user_id)["is_read"])

    def test_mark_all_read_only_touches_this_users_unread_ones(self):
        other = new_user(self.users)
        a = self.store.create(self.user_id, "follow_up", "A", None, None, NOW)
        b = self.store.create(self.user_id, "follow_up", "B", None, None, NOW)
        self.store.set_read(a, self.user_id, True)
        other_n = self.store.create(other, "follow_up", "Other", None, None, NOW)
        changed = self.store.mark_all_read(self.user_id)
        self.assertEqual(changed, 1)                       # only b was unread
        self.assertTrue(self.store.get(b, self.user_id)["is_read"])
        self.assertFalse(self.store.get(other_n, other)["is_read"])   # someone else's is untouched

    def test_delete_removes_it_and_reports_true(self):
        nid = self.store.create(self.user_id, "follow_up", "A", None, None, NOW)
        self.assertTrue(self.store.delete(nid, self.user_id))
        self.assertIsNone(self.store.get(nid, self.user_id))

    def test_deleting_something_that_does_not_exist_reports_false(self):
        self.assertFalse(self.store.delete(999999, self.user_id))

    def test_one_persons_notification_is_invisible_to_another(self):
        other = new_user(self.users)
        nid = self.store.create(self.user_id, "follow_up", "Private", None, None, NOW)
        self.assertIsNone(self.store.get(nid, other))
        self.assertEqual(self.store.list_for_user(other), [])
        self.assertEqual(self.store.unread_count(other), 0)

    def test_one_person_cannot_mark_or_delete_anothers(self):
        other = new_user(self.users)
        nid = self.store.create(self.user_id, "follow_up", "Private", None, None, NOW)
        self.assertFalse(self.store.set_read(nid, other, True))
        self.assertFalse(self.store.delete(nid, other))
        self.assertFalse(self.store.get(nid, self.user_id)["is_read"])   # untouched


class MemoryStoreTests(NotificationStoreContract, unittest.TestCase):
    def make_stores(self):
        return MemoryUserStore(), MemoryNotificationStore()


class MySQLStoreTests(NotificationStoreContract, unittest.TestCase):
    def make_stores(self):
        if mysql_support.problem:
            self.skipTest(mysql_support.problem)
        mysql_support.push_app_context(self)
        return MySQLUserStore(), MySQLNotificationStore()

    def test_deleting_the_user_deletes_their_notifications(self):
        from db import execute, query_one
        nid = self.store.create(self.user_id, "follow_up", "A", None, None, NOW)
        execute("DELETE FROM users WHERE user_id = %s", (self.user_id,))
        self.assertEqual(query_one("SELECT COUNT(*) AS n FROM notifications WHERE notification_id = %s", (nid,))["n"], 0)


if __name__ == "__main__":
    unittest.main()
