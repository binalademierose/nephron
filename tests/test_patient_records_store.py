"""Checks for services/patient_records_store.py. The SAME checks run against Memory and MySQL."""
import os
import sys
import unittest
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mysql_support  # noqa: E402

from services.patient_records_store import MemoryPatientRecordsStore, MySQLPatientRecordsStore  # noqa: E402
from services.user_store import MemoryUserStore, MySQLUserStore  # noqa: E402

NOW = datetime(2026, 9, 20, 10, 0, 0)


def setUpModule():
    mysql_support.prepare()


def tearDownModule():
    mysql_support.drop()


def new_professional(users):
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    return users.create_user({"email": email, "full_name": "Dr. Luis Cruz", "role": "professional",
                              "professional": {"profession_title": "Nephrologist", "institution": None, "license_number": None}}, "h", NOW)


class PatientRecordsStoreContract:
    def make_stores(self):
        raise NotImplementedError

    def setUp(self):
        self.users, self.store = self.make_stores()
        self.professional_id = new_professional(self.users)

    def test_creating_one_makes_a_real_shadow_account_and_a_sequential_code(self):
        user_id, code = self.store.create(self.professional_id, "Juan Dela Cruz", 52, "Male",
                                          "shadow-a@patient-records.nephron.invalid", "h", NOW)
        self.assertRegex(code, r"^NPH-\d{4}$")
        shadow = self.users.find_by_id(user_id)
        self.assertEqual(shadow["role"], "general")
        self.assertTrue(shadow["is_patient_record"])
        self.assertEqual(shadow["full_name"], "Juan Dela Cruz")

    def test_two_patients_get_two_different_sequential_codes(self):
        _, code1 = self.store.create(self.professional_id, "A One", 40, "Female", "a@patient-records.nephron.invalid", "h", NOW)
        _, code2 = self.store.create(self.professional_id, "A Two", 41, "Male", "b@patient-records.nephron.invalid", "h", NOW)
        self.assertNotEqual(code1, code2)

    def test_get_by_user_id_returns_the_full_record(self):
        user_id, code = self.store.create(self.professional_id, "Juan Dela Cruz", 52, "Male",
                                          "shadow-b@patient-records.nephron.invalid", "h", NOW)
        record = self.store.get_by_user_id(user_id)
        self.assertEqual((record["full_name"], record["age"], record["sex"], record["patient_code"], record["professional_user_id"]),
                         ("Juan Dela Cruz", 52, "Male", code, self.professional_id))

    def test_get_by_user_id_for_someone_with_no_record_is_none(self):
        other = new_professional(self.users)
        self.assertIsNone(self.store.get_by_user_id(other))

    def test_get_by_code_finds_the_same_record(self):
        user_id, code = self.store.create(self.professional_id, "Juan Dela Cruz", 52, "Male",
                                          "shadow-c@patient-records.nephron.invalid", "h", NOW)
        self.assertEqual(self.store.get_by_code(code)["user_id"], user_id)

    def test_get_by_code_for_an_unknown_code_is_none(self):
        self.assertIsNone(self.store.get_by_code("NPH-9999"))

    def test_list_for_professional_is_newest_first_and_scoped(self):
        other = new_professional(self.users)
        self.store.create(other, "Not Mine", 30, "Female", "x@patient-records.nephron.invalid", "h", NOW)
        first, _ = self.store.create(self.professional_id, "First", 30, "Female", "y@patient-records.nephron.invalid", "h", NOW)
        second, _ = self.store.create(self.professional_id, "Second", 31, "Male", "z@patient-records.nephron.invalid", "h", NOW)
        ids = [r["user_id"] for r in self.store.list_for_professional(self.professional_id)]
        self.assertEqual(ids, [second, first])

    def test_owned_by_is_true_only_for_the_creating_professional(self):
        other = new_professional(self.users)
        user_id, _ = self.store.create(self.professional_id, "Juan Dela Cruz", 52, "Male",
                                       "shadow-d@patient-records.nephron.invalid", "h", NOW)
        self.assertTrue(self.store.owned_by(user_id, self.professional_id))
        self.assertFalse(self.store.owned_by(user_id, other))
        self.assertFalse(self.store.owned_by(999999, self.professional_id))


class MemoryStoreTests(PatientRecordsStoreContract, unittest.TestCase):
    def make_stores(self):
        users = MemoryUserStore()
        return users, MemoryPatientRecordsStore(users)


class MySQLStoreTests(PatientRecordsStoreContract, unittest.TestCase):
    def make_stores(self):
        if mysql_support.problem:
            self.skipTest(mysql_support.problem)
        mysql_support.push_app_context(self)
        return MySQLUserStore(), MySQLPatientRecordsStore()

    def test_deleting_the_professional_deletes_their_patient_records_but_leaves_the_orphaned_shadow_account(self):
        # An orphaned patient_record shadow account is harmless (it can never sign in, and nothing lists it once
        # its patient_records row is gone) - there is no "delete a professional's account" feature to attach
        # further cleanup to, so this only checks the one thing patient_records.py itself promises.
        user_id, _ = self.store.create(self.professional_id, "Juan Dela Cruz", 52, "Male",
                                       "shadow-e@patient-records.nephron.invalid", "h", NOW)
        from db import execute, query_one
        execute("DELETE FROM users WHERE user_id = %s", (self.professional_id,))
        self.assertIsNone(query_one("SELECT 1 AS one FROM patient_records WHERE user_id = %s", (user_id,)))


if __name__ == "__main__":
    unittest.main()
