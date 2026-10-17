"""
Checks for services/checklist_store.py. The SAME checks run against Memory and MySQL.
"""
import os
import sys
import unittest
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mysql_support  # noqa: E402

from services.checklist_store import MemoryChecklistStore, MySQLChecklistStore  # noqa: E402
from services.user_store import MemoryUserStore, MySQLUserStore  # noqa: E402

NOW = datetime(2026, 9, 20, 10, 0, 0)


def setUpModule():
    mysql_support.prepare()


def tearDownModule():
    mysql_support.drop()


def new_user(users):
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    return users.create_user({"email": email, "full_name": "Ana Reyes", "role": "general", "professional": None}, "h", NOW)


class ChecklistStoreContract:
    def make_stores(self):
        raise NotImplementedError

    def setUp(self):
        self.users, self.store = self.make_stores()
        self.user_id = new_user(self.users)

    def test_nothing_completed_at_first(self):
        self.assertEqual(self.store.completed_tip_ids(self.user_id), set())

    def test_marking_complete_shows_up(self):
        self.store.mark_complete(self.user_id, "diet_general", NOW)
        self.assertEqual(self.store.completed_tip_ids(self.user_id), {"diet_general"})

    def test_marking_complete_twice_is_harmless(self):
        self.store.mark_complete(self.user_id, "diet_general", NOW)
        self.store.mark_complete(self.user_id, "diet_general", NOW)
        self.assertEqual(self.store.completed_tip_ids(self.user_id), {"diet_general"})

    def test_several_tips_can_be_completed_independently(self):
        self.store.mark_complete(self.user_id, "diet_general", NOW)
        self.store.mark_complete(self.user_id, "activity_general", NOW)
        self.assertEqual(self.store.completed_tip_ids(self.user_id), {"diet_general", "activity_general"})

    def test_marking_incomplete_removes_just_that_one(self):
        self.store.mark_complete(self.user_id, "diet_general", NOW)
        self.store.mark_complete(self.user_id, "activity_general", NOW)
        self.store.mark_incomplete(self.user_id, "diet_general")
        self.assertEqual(self.store.completed_tip_ids(self.user_id), {"activity_general"})

    def test_marking_incomplete_something_never_completed_is_harmless(self):
        self.store.mark_incomplete(self.user_id, "diet_general")
        self.assertEqual(self.store.completed_tip_ids(self.user_id), set())

    def test_one_persons_checklist_is_invisible_to_another(self):
        other = new_user(self.users)
        self.store.mark_complete(self.user_id, "diet_general", NOW)
        self.assertEqual(self.store.completed_tip_ids(other), set())


class MemoryStoreTests(ChecklistStoreContract, unittest.TestCase):
    def make_stores(self):
        return MemoryUserStore(), MemoryChecklistStore()


class MySQLStoreTests(ChecklistStoreContract, unittest.TestCase):
    def make_stores(self):
        if mysql_support.problem:
            self.skipTest(mysql_support.problem)
        mysql_support.push_app_context(self)
        return MySQLUserStore(), MySQLChecklistStore()


if __name__ == "__main__":
    unittest.main()
