"""
Checks for services/authorization_store.py. The SAME checks run against two stores:
  * MemoryAuthorizationStore - always runs.
  * MySQLAuthorizationStore  - runs on the separate <DB_NAME>_test database (see tests/mysql_support.py).
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

from services.authorization_store import MemoryAuthorizationStore, MySQLAuthorizationStore, UnknownUserError  # noqa: E402
from services.user_store import MemoryUserStore, MySQLUserStore  # noqa: E402

NOW = datetime(2026, 9, 20, 10, 0, 0)
LATER = datetime(2026, 9, 21, 10, 0, 0)
EVEN_LATER = datetime(2026, 9, 22, 10, 0, 0)


def setUpModule():
    mysql_support.prepare()


def tearDownModule():
    mysql_support.drop()


def new_user(users, role, name):
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    return users.create_user({"email": email, "full_name": name, "role": role, "professional": None}, "h", NOW)


class AuthorizationStoreContract:
    def make_stores(self):
        raise NotImplementedError

    def setUp(self):
        self.users, self.store = self.make_stores()
        self.patient = new_user(self.users, "general", "Ana Reyes")
        self.professional = new_user(self.users, "professional", "Dr. Cruz")

    def test_a_fresh_request_is_pending_with_no_response_yet(self):
        row = self.store.request(self.patient, self.professional, NOW)
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["requested_at"], NOW)
        self.assertIsNone(row["responded_at"])
        self.assertEqual((row["patient_user_id"], row["professional_user_id"]), (self.patient, self.professional))

    def test_accepting_a_pending_request_succeeds_and_is_reflected_in_get(self):
        self.store.request(self.patient, self.professional, NOW)
        self.assertTrue(self.store.accept(self.patient, self.professional, LATER))
        row = self.store.get(self.patient, self.professional)
        self.assertEqual(row["status"], "accepted")
        self.assertEqual(row["responded_at"], LATER)

    def test_declining_a_pending_request_succeeds(self):
        self.store.request(self.patient, self.professional, NOW)
        self.assertTrue(self.store.decline(self.patient, self.professional, LATER))
        self.assertEqual(self.store.get(self.patient, self.professional)["status"], "declined")

    def test_accepting_something_not_pending_fails_quietly_and_changes_nothing(self):
        self.store.request(self.patient, self.professional, NOW)
        self.store.decline(self.patient, self.professional, LATER)
        self.assertFalse(self.store.accept(self.patient, self.professional, EVEN_LATER))
        row = self.store.get(self.patient, self.professional)
        self.assertEqual(row["status"], "declined")                # unchanged
        self.assertEqual(row["responded_at"], LATER)                # unchanged

    def test_revoking_an_accepted_authorization_succeeds(self):
        self.store.request(self.patient, self.professional, NOW)
        self.store.accept(self.patient, self.professional, LATER)
        self.assertTrue(self.store.revoke(self.patient, self.professional, EVEN_LATER))
        self.assertEqual(self.store.get(self.patient, self.professional)["status"], "revoked")

    def test_revoking_something_not_accepted_fails_quietly(self):
        self.store.request(self.patient, self.professional, NOW)
        self.assertFalse(self.store.revoke(self.patient, self.professional, LATER))

    def test_requesting_again_after_a_decline_reuses_the_same_row_reset_to_pending(self):
        first = self.store.request(self.patient, self.professional, NOW)
        self.store.decline(self.patient, self.professional, LATER)
        second = self.store.request(self.patient, self.professional, EVEN_LATER)
        self.assertEqual(first["authorization_id"], second["authorization_id"])
        self.assertEqual(second["status"], "pending")
        self.assertIsNone(second["responded_at"])
        self.assertEqual(second["requested_at"], EVEN_LATER)

    def test_requesting_again_after_a_revoke_also_reuses_the_same_row(self):
        first = self.store.request(self.patient, self.professional, NOW)
        self.store.accept(self.patient, self.professional, LATER)
        self.store.revoke(self.patient, self.professional, EVEN_LATER)
        second = self.store.request(self.patient, self.professional, EVEN_LATER)
        self.assertEqual(first["authorization_id"], second["authorization_id"])
        self.assertEqual(second["status"], "pending")

    def test_get_for_a_pair_with_no_history_is_none(self):
        self.assertIsNone(self.store.get(self.patient, self.professional))

    def test_list_for_patient_and_list_for_professional_see_the_same_row(self):
        self.store.request(self.patient, self.professional, NOW)
        self.assertEqual(len(self.store.list_for_patient(self.patient)), 1)
        self.assertEqual(len(self.store.list_for_professional(self.professional)), 1)
        other_patient = new_user(self.users, "general", "Ben Cruz")
        self.assertEqual(self.store.list_for_patient(other_patient), [])

    def test_list_can_be_narrowed_by_status(self):
        other_professional = new_user(self.users, "professional", "Dr. Santos")
        self.store.request(self.patient, self.professional, NOW)
        self.store.request(self.patient, other_professional, NOW)
        self.store.accept(self.patient, other_professional, LATER)
        pending_only = self.store.list_for_patient(self.patient, statuses={"pending"})
        self.assertEqual([row["professional_user_id"] for row in pending_only], [self.professional])
        accepted_only = self.store.list_for_patient(self.patient, statuses={"accepted"})
        self.assertEqual([row["professional_user_id"] for row in accepted_only], [other_professional])

    def test_listed_newest_request_first(self):
        p2 = new_user(self.users, "professional", "Dr. Santos")
        self.store.request(self.patient, self.professional, NOW)
        self.store.request(self.patient, p2, LATER)
        ids = [row["professional_user_id"] for row in self.store.list_for_patient(self.patient)]
        self.assertEqual(ids, [p2, self.professional])

    def test_a_request_for_a_patient_that_does_not_exist_is_refused(self):
        with self.assertRaises(UnknownUserError):
            self.store.request(987654321, self.professional, NOW)

    def test_a_request_for_a_professional_that_does_not_exist_is_refused(self):
        with self.assertRaises(UnknownUserError):
            self.store.request(self.patient, 987654321, NOW)

    def test_two_different_patients_can_each_have_their_own_row_with_the_same_professional(self):
        other_patient = new_user(self.users, "general", "Ben Cruz")
        self.store.request(self.patient, self.professional, NOW)
        self.store.request(other_patient, self.professional, NOW)
        self.assertEqual(len(self.store.list_for_professional(self.professional)), 2)


class MemoryStoreTests(AuthorizationStoreContract, unittest.TestCase):
    def make_stores(self):
        users = MemoryUserStore()
        return users, MemoryAuthorizationStore(users)


class MySQLStoreTests(AuthorizationStoreContract, unittest.TestCase):
    def make_stores(self):
        if mysql_support.problem:
            self.skipTest(mysql_support.problem)
        mysql_support.push_app_context(self)
        return MySQLUserStore(), MySQLAuthorizationStore()

    def test_deleting_the_patient_deletes_the_row(self):
        from db import execute, query_one
        self.store.request(self.patient, self.professional, NOW)
        execute("DELETE FROM users WHERE user_id = %s", (self.patient,))
        self.assertEqual(query_one("SELECT COUNT(*) AS n FROM authorizations WHERE patient_user_id = %s", (self.patient,))["n"], 0)

    def test_deleting_the_professional_deletes_the_row(self):
        from db import execute, query_one
        self.store.request(self.patient, self.professional, NOW)
        execute("DELETE FROM users WHERE user_id = %s", (self.professional,))
        self.assertEqual(query_one("SELECT COUNT(*) AS n FROM authorizations WHERE professional_user_id = %s", (self.professional,))["n"], 0)


if __name__ == "__main__":
    unittest.main()
