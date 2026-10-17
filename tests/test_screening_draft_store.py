"""
Checks for services/screening_draft_store.py. The SAME checks run against two stores:
  * MemoryScreeningDraftStore - always runs.
  * MySQLScreeningDraftStore  - runs on the separate <DB_NAME>_test database (see tests/mysql_support.py).
                                Skipped, with the reason, if MySQL is not available.
"""
import os
import sys
import unittest
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mysql_support  # noqa: E402

from services.screening_draft_store import MemoryScreeningDraftStore, MySQLScreeningDraftStore  # noqa: E402
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


class ScreeningDraftStoreContract:
    def make_stores(self):
        raise NotImplementedError

    def setUp(self):
        self.users, self.store = self.make_stores()
        self.user_id = new_user(self.users)

    def test_a_fresh_draft_is_read_back_exactly(self):
        self.store.save_draft(self.user_id, "preliminary", {"Age": "45", "Sex": "Female"}, "health_history", NOW)
        draft = self.store.get_draft(self.user_id, "preliminary")
        self.assertEqual(draft["answers"], {"Age": "45", "Sex": "Female"})
        self.assertEqual(draft["current_step"], "health_history")
        self.assertEqual(draft["updated_at"], NOW)

    def test_no_draft_is_none(self):
        self.assertIsNone(self.store.get_draft(self.user_id, "preliminary"))

    def test_saving_again_updates_the_same_draft_not_a_new_one(self):
        self.store.save_draft(self.user_id, "preliminary", {"Age": "45"}, "about_you", NOW)
        first = self.store.get_draft(self.user_id, "preliminary")
        self.store.save_draft(self.user_id, "preliminary", {"Age": "45", "Sex": "Female"}, "health_history", LATER)
        second = self.store.get_draft(self.user_id, "preliminary")
        self.assertEqual(first["draft_id"], second["draft_id"])
        self.assertEqual(second["answers"], {"Age": "45", "Sex": "Female"})
        self.assertEqual(second["current_step"], "health_history")

    def test_preliminary_and_enhanced_are_separate_drafts(self):
        self.store.save_draft(self.user_id, "preliminary", {"Age": "45"}, "about_you", NOW)
        self.store.save_draft(self.user_id, "enhanced", {"Serum_Creatinine": "1.2"}, None, NOW)
        self.assertEqual(self.store.get_draft(self.user_id, "preliminary")["answers"], {"Age": "45"})
        self.assertEqual(self.store.get_draft(self.user_id, "enhanced")["answers"], {"Serum_Creatinine": "1.2"})

    def test_list_drafts_returns_every_type_newest_first(self):
        self.store.save_draft(self.user_id, "preliminary", {}, None, NOW)
        self.store.save_draft(self.user_id, "enhanced", {}, None, LATER)
        types = [d["assessment_type"] for d in self.store.list_drafts(self.user_id)]
        self.assertEqual(types, ["enhanced", "preliminary"])

    def test_list_drafts_for_someone_with_none_is_empty(self):
        self.assertEqual(self.store.list_drafts(self.user_id), [])

    def test_discarding_an_existing_draft_removes_it_and_reports_true(self):
        self.store.save_draft(self.user_id, "preliminary", {"Age": "45"}, None, NOW)
        self.assertTrue(self.store.discard_draft(self.user_id, "preliminary"))
        self.assertIsNone(self.store.get_draft(self.user_id, "preliminary"))

    def test_discarding_nothing_reports_false(self):
        self.assertFalse(self.store.discard_draft(self.user_id, "preliminary"))

    def test_discarding_one_type_leaves_the_other_alone(self):
        self.store.save_draft(self.user_id, "preliminary", {}, None, NOW)
        self.store.save_draft(self.user_id, "enhanced", {}, None, NOW)
        self.store.discard_draft(self.user_id, "preliminary")
        self.assertIsNone(self.store.get_draft(self.user_id, "preliminary"))
        self.assertIsNotNone(self.store.get_draft(self.user_id, "enhanced"))

    def test_one_persons_draft_is_never_mixed_with_anothers(self):
        other = new_user(self.users)
        self.store.save_draft(self.user_id, "preliminary", {"Age": "45"}, None, NOW)
        self.assertIsNone(self.store.get_draft(other, "preliminary"))
        self.assertEqual(self.store.list_drafts(other), [])


class MemoryStoreTests(ScreeningDraftStoreContract, unittest.TestCase):
    def make_stores(self):
        return MemoryUserStore(), MemoryScreeningDraftStore()


class MySQLStoreTests(ScreeningDraftStoreContract, unittest.TestCase):
    def make_stores(self):
        if mysql_support.problem:
            self.skipTest(mysql_support.problem)
        mysql_support.push_app_context(self)
        return MySQLUserStore(), MySQLScreeningDraftStore()

    def test_deleting_the_user_deletes_their_drafts(self):
        from db import execute, query_one
        self.store.save_draft(self.user_id, "preliminary", {"Age": "45"}, None, NOW)
        execute("DELETE FROM users WHERE user_id = %s", (self.user_id,))
        self.assertEqual(query_one("SELECT COUNT(*) AS n FROM screening_drafts WHERE user_id = %s", (self.user_id,))["n"], 0)


if __name__ == "__main__":
    unittest.main()
