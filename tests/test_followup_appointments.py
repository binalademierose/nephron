"""
Checks for services/followup_appointments.py: only a currently-authorized professional may schedule, reschedule,
complete, cancel, or delete - re-checked fresh on every write, never trusted from an earlier visit.
"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import followup_appointments as fa  # noqa: E402
from services.authorization_store import MemoryAuthorizationStore  # noqa: E402
from services.followup_appointment_store import MemoryFollowUpAppointmentStore  # noqa: E402
from services.user_store import MemoryUserStore  # noqa: E402

NOW = datetime(2026, 9, 20, 10, 0, 0)
FUTURE = datetime(2026, 10, 15, 6, 30, 0)
PAST = datetime(2026, 1, 1, 6, 30, 0)


def _new_stores():
    users = MemoryUserStore()
    patient_id = users.create_user({"email": "ana@example.com", "full_name": "Ana Reyes", "role": "general", "professional": None}, "h", NOW)
    professional_id = users.create_user({"email": "dr.cruz@example.com", "full_name": "Dr. Luis Cruz", "role": "professional",
                                        "professional": {"profession_title": "Nephrologist", "institution": None, "license_number": None}}, "h", NOW)
    return users, MemoryAuthorizationStore(users), patient_id, professional_id


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.users, self.auth_store, self.patient_id, self.professional_id = _new_stores()
        self.store = MemoryFollowUpAppointmentStore()
        self.auth_store.request(self.patient_id, self.professional_id, NOW)
        self.auth_store.accept(self.patient_id, self.professional_id, NOW)
        self.professional = self.users.find_by_id(self.professional_id)

    def test_an_authorized_professional_can_schedule_one(self):
        aid = fa.schedule(self.store, self.auth_store, self.professional, self.patient_id, FUTURE, "Recheck labs", "Bring results", NOW)
        row = self.store.get(aid)
        self.assertEqual(row["purpose"], "Recheck labs")

    def test_an_unauthorized_professional_cannot_schedule_one(self):
        other_patient = self.users.create_user({"email": "other@example.com", "full_name": "Other", "role": "general", "professional": None}, "h", NOW)
        with self.assertRaises(fa.NotAuthorizedError):
            fa.schedule(self.store, self.auth_store, self.professional, other_patient, FUTURE, "Recheck labs", None, NOW)

    def test_a_blank_purpose_is_refused(self):
        with self.assertRaises(ValueError):
            fa.schedule(self.store, self.auth_store, self.professional, self.patient_id, FUTURE, "   ", None, NOW)

    def test_a_past_moment_is_refused(self):
        with self.assertRaises(ValueError):
            fa.schedule(self.store, self.auth_store, self.professional, self.patient_id, PAST, "Recheck labs", None, NOW)

    def test_an_over_long_purpose_is_refused(self):
        with self.assertRaises(ValueError):
            fa.schedule(self.store, self.auth_store, self.professional, self.patient_id, FUTURE, "x" * 201, None, NOW)

    def test_revoking_authorization_blocks_scheduling_even_if_it_was_once_accepted(self):
        self.auth_store.revoke(self.patient_id, self.professional_id, NOW)
        with self.assertRaises(fa.NotAuthorizedError):
            fa.schedule(self.store, self.auth_store, self.professional, self.patient_id, FUTURE, "Recheck labs", None, NOW)


class ReschedulingAndStatusTests(unittest.TestCase):
    def setUp(self):
        self.users, self.auth_store, self.patient_id, self.professional_id = _new_stores()
        self.store = MemoryFollowUpAppointmentStore()
        self.auth_store.request(self.patient_id, self.professional_id, NOW)
        self.auth_store.accept(self.patient_id, self.professional_id, NOW)
        professional = self.users.find_by_id(self.professional_id)
        self.aid = fa.schedule(self.store, self.auth_store, professional, self.patient_id, FUTURE, "Original purpose", None, NOW)

    def test_rescheduling_changes_the_time_and_purpose(self):
        new_time = FUTURE.replace(day=20)
        fa.reschedule(self.store, self.auth_store, self.professional_id, self.aid, new_time, "Changed purpose", "A note", NOW)
        row = self.store.get(self.aid)
        self.assertEqual(row["scheduled_at"], new_time)
        self.assertEqual(row["purpose"], "Changed purpose")

    def test_a_different_professional_cannot_reschedule_it(self):
        other = self.users.create_user({"email": "other-doc@example.com", "full_name": "Other Doc", "role": "professional",
                                        "professional": {"profession_title": "Nurse", "institution": None, "license_number": None}}, "h", NOW)
        with self.assertRaises(fa.NotAuthorizedError):
            fa.reschedule(self.store, self.auth_store, other, self.aid, FUTURE, "Hijacked", None, NOW)

    def test_revoked_authorization_blocks_rescheduling_the_existing_appointment_too(self):
        self.auth_store.revoke(self.patient_id, self.professional_id, NOW)
        with self.assertRaises(fa.NotAuthorizedError):
            fa.reschedule(self.store, self.auth_store, self.professional_id, self.aid, FUTURE, "Changed", None, NOW)

    def test_cancel_sets_the_status(self):
        fa.cancel(self.store, self.auth_store, self.professional_id, self.aid, NOW)
        self.assertEqual(self.store.get(self.aid)["status"], "cancelled")

    def test_complete_sets_the_status(self):
        fa.complete(self.store, self.auth_store, self.professional_id, self.aid, NOW)
        self.assertEqual(self.store.get(self.aid)["status"], "completed")

    def test_delete_removes_it(self):
        fa.delete(self.store, self.auth_store, self.professional_id, self.aid)
        self.assertIsNone(self.store.get(self.aid))

    def test_a_different_professional_cannot_delete_it(self):
        other = self.users.create_user({"email": "other-doc2@example.com", "full_name": "Other Doc", "role": "professional",
                                        "professional": {"profession_title": "Nurse", "institution": None, "license_number": None}}, "h", NOW)
        with self.assertRaises(fa.NotAuthorizedError):
            fa.delete(self.store, self.auth_store, other, self.aid)


class DescribingTests(unittest.TestCase):
    def setUp(self):
        self.users, self.auth_store, self.patient_id, self.professional_id = _new_stores()
        self.store = MemoryFollowUpAppointmentStore()
        self.auth_store.request(self.patient_id, self.professional_id, NOW)
        self.auth_store.accept(self.patient_id, self.professional_id, NOW)
        professional = self.users.find_by_id(self.professional_id)
        fa.schedule(self.store, self.auth_store, professional, self.patient_id, FUTURE, "Recheck labs", None, NOW)

    def test_for_patient_includes_the_local_time(self):
        described = fa.for_patient(self.store, self.patient_id, "Asia/Manila")
        self.assertEqual(len(described), 1)
        self.assertIn("scheduled_local", described[0])

    def test_for_professional_patient_is_scoped(self):
        described = fa.for_professional_patient(self.store, self.professional_id, self.patient_id, "Asia/Manila")
        self.assertEqual(len(described), 1)
        described_other = fa.for_professional_patient(self.store, self.professional_id, 999999, "Asia/Manila")
        self.assertEqual(described_other, [])


if __name__ == "__main__":
    unittest.main()
