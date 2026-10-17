"""
Checks for services/followup_store.py. The SAME checks run against two stores:
  * MemoryFollowUpStore - always runs.
  * MySQLFollowUpStore  - runs on the separate <DB_NAME>_test database (see tests/mysql_support.py).
                          Skipped, with the reason, if MySQL is not available.
"""
import os
import sys
import unittest
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mysql_support  # noqa: E402

import mysql.connector  # noqa: E402

from services.followup_store import MemoryFollowUpStore, MySQLFollowUpStore, UnknownUserError  # noqa: E402
from services.user_store import MemoryUserStore, MySQLUserStore  # noqa: E402

NOW = datetime(2026, 9, 20, 10, 0, 0)
LATER = datetime(2026, 9, 21, 10, 0, 0)


def setUpModule():
    mysql_support.prepare()


def tearDownModule():
    mysql_support.drop()


def new_user(users, role, name):
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    return users.create_user({"email": email, "full_name": name, "role": role, "professional": None}, "h", NOW)


class FollowUpStoreContract:
    def make_stores(self):
        raise NotImplementedError

    def setUp(self):
        self.users, self.store = self.make_stores()
        self.patient = new_user(self.users, "general", "Ana Reyes")
        self.professional = new_user(self.users, "professional", "Dr. Maria Cruz")

    def request(self, **changes):
        defaults = dict(patient_user_id=self.patient, professional_user_id=self.professional,
                        professional_name="Dr. Maria Cruz", profession_title="Nephrologist",
                        message="Please redo after your medication change.", requested_at=NOW)
        defaults.update(changes)
        return self.store.request(**defaults)

    def test_a_fresh_request_is_open(self):
        self.request()
        row = self.store.get_open(self.patient)
        self.assertIsNotNone(row)
        self.assertIsNone(row["fulfilled_at"])
        self.assertEqual(row["professional_name"], "Dr. Maria Cruz")
        self.assertEqual(row["message"], "Please redo after your medication change.")

    def test_no_request_means_get_open_is_none(self):
        self.assertIsNone(self.store.get_open(self.patient))

    def test_marking_fulfilled_closes_it(self):
        self.request()
        closed = self.store.mark_fulfilled(self.patient, LATER)
        self.assertEqual(closed, 1)
        self.assertIsNone(self.store.get_open(self.patient))
        row = self.store.list_for_patient(self.patient)[0]
        self.assertEqual(row["fulfilled_at"], LATER)

    def test_marking_fulfilled_with_nothing_open_closes_nothing(self):
        self.assertEqual(self.store.mark_fulfilled(self.patient, NOW), 0)

    def test_a_message_is_optional(self):
        self.request(message=None)
        self.assertIsNone(self.store.get_open(self.patient)["message"])

    def test_requesting_again_after_fulfilment_creates_a_new_open_request(self):
        self.request()
        self.store.mark_fulfilled(self.patient, LATER)
        self.request(requested_at=LATER)
        row = self.store.get_open(self.patient)
        self.assertIsNotNone(row)
        self.assertEqual(row["requested_at"], LATER)
        self.assertEqual(len(self.store.list_for_patient(self.patient)), 2)

    def test_list_for_patient_and_list_for_professional_see_the_same_row(self):
        self.request()
        self.assertEqual(len(self.store.list_for_patient(self.patient)), 1)
        self.assertEqual(len(self.store.list_for_professional(self.professional)), 1)

    def test_listed_newest_first(self):
        other_patient = new_user(self.users, "general", "Ben Cruz")
        self.request(patient_user_id=self.patient, requested_at=NOW)
        self.request(patient_user_id=other_patient, requested_at=LATER)
        ids = [row["patient_user_id"] for row in self.store.list_for_professional(self.professional)]
        self.assertEqual(ids, [other_patient, self.patient])

    def test_one_patients_requests_are_not_mixed_with_anothers(self):
        other_patient = new_user(self.users, "general", "Ben Cruz")
        self.request(patient_user_id=self.patient)
        self.assertEqual(self.store.list_for_patient(other_patient), [])

    def test_a_request_for_a_patient_that_does_not_exist_is_refused(self):
        with self.assertRaises(UnknownUserError):
            self.request(patient_user_id=987654321)

    def test_a_request_for_a_professional_that_does_not_exist_is_refused(self):
        with self.assertRaises(UnknownUserError):
            self.request(professional_user_id=987654321)


class MemoryStoreTests(FollowUpStoreContract, unittest.TestCase):
    def make_stores(self):
        users = MemoryUserStore()
        return users, MemoryFollowUpStore(users)


class MySQLStoreTests(FollowUpStoreContract, unittest.TestCase):
    def make_stores(self):
        if mysql_support.problem:
            self.skipTest(mysql_support.problem)
        mysql_support.push_app_context(self)
        return MySQLUserStore(), MySQLFollowUpStore()

    def test_deleting_the_patient_deletes_their_requests(self):
        from db import execute, query_one
        self.request()
        execute("DELETE FROM users WHERE user_id = %s", (self.patient,))
        self.assertEqual(query_one("SELECT COUNT(*) AS n FROM follow_up_requests WHERE patient_user_id = %s", (self.patient,))["n"], 0)

    def test_deleting_the_professional_keeps_the_request_but_clears_the_link(self):
        from db import execute, query_one
        self.request()
        execute("DELETE FROM users WHERE user_id = %s", (self.professional,))
        row = query_one("SELECT professional_user_id, professional_name FROM follow_up_requests WHERE patient_user_id = %s", (self.patient,))
        self.assertIsNone(row["professional_user_id"])
        self.assertEqual(row["professional_name"], "Dr. Maria Cruz")


if __name__ == "__main__":
    unittest.main()
