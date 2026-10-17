"""
Checks for services/followup_appointment_store.py. The SAME checks run against Memory and MySQL.
"""
import os
import sys
import unittest
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mysql_support  # noqa: E402

from services.followup_appointment_store import MemoryFollowUpAppointmentStore, MySQLFollowUpAppointmentStore  # noqa: E402
from services.user_store import MemoryUserStore, MySQLUserStore  # noqa: E402

NOW = datetime(2026, 9, 20, 10, 0, 0)
LATER = datetime(2026, 9, 21, 10, 0, 0)
SCHEDULED = datetime(2026, 10, 15, 6, 30, 0)


def setUpModule():
    mysql_support.prepare()


def tearDownModule():
    mysql_support.drop()


def new_user(users):
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    return users.create_user({"email": email, "full_name": "Ana Reyes", "role": "general", "professional": None}, "h", NOW)


class FollowUpAppointmentStoreContract:
    def make_stores(self):
        raise NotImplementedError

    def setUp(self):
        self.users, self.store = self.make_stores()
        self.patient_id = new_user(self.users)
        self.professional_id = new_user(self.users)

    def test_a_fresh_appointment_is_scheduled_and_read_back(self):
        aid = self.store.create(self.patient_id, self.professional_id, "Dr. Cruz", "Nephrologist", SCHEDULED, "Recheck labs", "Bring your last results", NOW)
        row = self.store.get(aid)
        self.assertEqual(row["scheduled_at"], SCHEDULED)
        self.assertEqual(row["purpose"], "Recheck labs")
        self.assertEqual(row["notes"], "Bring your last results")
        self.assertEqual(row["status"], "scheduled")
        self.assertEqual(row["professional_name"], "Dr. Cruz")

    def test_notes_are_optional(self):
        aid = self.store.create(self.patient_id, self.professional_id, "Dr. Cruz", "Nephrologist", SCHEDULED, "Recheck labs", None, NOW)
        self.assertIsNone(self.store.get(aid)["notes"])

    def test_list_for_patient_is_soonest_first(self):
        later = self.store.create(self.patient_id, self.professional_id, "Dr. Cruz", None, LATER.replace(month=11), "Later visit", None, NOW)
        sooner = self.store.create(self.patient_id, self.professional_id, "Dr. Cruz", None, SCHEDULED, "Sooner visit", None, NOW)
        ids = [row["appointment_id"] for row in self.store.list_for_patient(self.patient_id)]
        self.assertEqual(ids, [sooner, later])

    def test_list_for_professional_patient_only_shows_that_pair(self):
        other_patient = new_user(self.users)
        mine = self.store.create(self.patient_id, self.professional_id, "Dr. Cruz", None, SCHEDULED, "Mine", None, NOW)
        self.store.create(other_patient, self.professional_id, "Dr. Cruz", None, SCHEDULED, "Not mine", None, NOW)
        rows = self.store.list_for_professional_patient(self.professional_id, self.patient_id)
        self.assertEqual([row["appointment_id"] for row in rows], [mine])

    def test_list_for_professional_spans_every_one_of_their_patients(self):
        other_patient = new_user(self.users)
        other_professional = new_user(self.users)
        first = self.store.create(self.patient_id, self.professional_id, "Dr. Cruz", None, SCHEDULED, "First", None, NOW)
        second = self.store.create(other_patient, self.professional_id, "Dr. Cruz", None, SCHEDULED.replace(month=11), "Second", None, NOW)
        self.store.create(self.patient_id, other_professional, "Dr. Other", None, SCHEDULED, "Not mine", None, NOW)
        rows = self.store.list_for_professional(self.professional_id)
        self.assertEqual({row["appointment_id"] for row in rows}, {first, second})

    def test_update_changes_the_schedule_purpose_and_notes(self):
        aid = self.store.create(self.patient_id, self.professional_id, "Dr. Cruz", None, SCHEDULED, "Original", None, NOW)
        self.assertTrue(self.store.update(aid, self.professional_id, LATER, "Changed purpose", "Added a note", LATER))
        row = self.store.get(aid)
        self.assertEqual(row["scheduled_at"], LATER)
        self.assertEqual(row["purpose"], "Changed purpose")
        self.assertEqual(row["notes"], "Added a note")
        self.assertEqual(row["updated_at"], LATER)

    def test_a_different_professional_cannot_update_it(self):
        aid = self.store.create(self.patient_id, self.professional_id, "Dr. Cruz", None, SCHEDULED, "Original", None, NOW)
        other_professional = new_user(self.users)
        self.assertFalse(self.store.update(aid, other_professional, LATER, "Hijacked", None, LATER))
        self.assertEqual(self.store.get(aid)["purpose"], "Original")

    def test_set_status_to_completed_and_cancelled(self):
        aid = self.store.create(self.patient_id, self.professional_id, "Dr. Cruz", None, SCHEDULED, "Original", None, NOW)
        self.assertTrue(self.store.set_status(aid, self.professional_id, "completed", LATER))
        self.assertEqual(self.store.get(aid)["status"], "completed")
        self.assertTrue(self.store.set_status(aid, self.professional_id, "cancelled", LATER))
        self.assertEqual(self.store.get(aid)["status"], "cancelled")

    def test_a_different_professional_cannot_change_status(self):
        aid = self.store.create(self.patient_id, self.professional_id, "Dr. Cruz", None, SCHEDULED, "Original", None, NOW)
        other_professional = new_user(self.users)
        self.assertFalse(self.store.set_status(aid, other_professional, "cancelled", LATER))

    def test_delete_removes_it_and_reports_true(self):
        aid = self.store.create(self.patient_id, self.professional_id, "Dr. Cruz", None, SCHEDULED, "Original", None, NOW)
        self.assertTrue(self.store.delete(aid, self.professional_id))
        self.assertIsNone(self.store.get(aid))

    def test_a_different_professional_cannot_delete_it(self):
        aid = self.store.create(self.patient_id, self.professional_id, "Dr. Cruz", None, SCHEDULED, "Original", None, NOW)
        other_professional = new_user(self.users)
        self.assertFalse(self.store.delete(aid, other_professional))
        self.assertIsNotNone(self.store.get(aid))

    def test_deleting_something_that_does_not_exist_reports_false(self):
        self.assertFalse(self.store.delete(999999, self.professional_id))


class MemoryStoreTests(FollowUpAppointmentStoreContract, unittest.TestCase):
    def make_stores(self):
        return MemoryUserStore(), MemoryFollowUpAppointmentStore()


class MySQLStoreTests(FollowUpAppointmentStoreContract, unittest.TestCase):
    def make_stores(self):
        if mysql_support.problem:
            self.skipTest(mysql_support.problem)
        mysql_support.push_app_context(self)
        return MySQLUserStore(), MySQLFollowUpAppointmentStore()


if __name__ == "__main__":
    unittest.main()
