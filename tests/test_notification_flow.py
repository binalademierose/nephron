"""
Checks for the notification website path: the four real events that create one, the header bell/badge, and the
dedicated /notifications page's mark read/unread/delete actions.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase  # noqa: E402


class NotificationEventTests(AppTestCase):
    """The four real events that create a notification - services/authorizations.py and
    services/followups.py/clinical_reviews.py are exercised through the actual routes, not called directly, so
    this also proves the routes are wired up correctly."""

    def setUp(self):
        super().setUp()
        self.patient = self.signed_in()
        self.professional = self.signed_in(**self.professional_details())
        self.professional_id = self.store.find_by_email("dr.cruz@example.com")["user_id"]
        self.patient_id = self.store.find_by_email("ana@example.com")["user_id"]

    def _unread(self, client):
        return self.text(client.get("/notifications")).count("notification-row is-unread")

    def test_a_share_request_notifies_the_professional(self):
        self.assertEqual(self._unread(self.professional), 0)
        self.post("/share/request", {"consent": "1", "professional_user_id": str(self.professional_id)}, client=self.patient, token_from="/share")
        self.assertEqual(self._unread(self.professional), 1)
        self.assertIn("Ana Reyes wants to share", self.text(self.professional.get("/notifications")))

    def test_accepting_a_share_notifies_the_patient(self):
        self.post("/share/request", {"consent": "1", "professional_user_id": str(self.professional_id)}, client=self.patient, token_from="/share")
        self.post(f"/patients/respond/{self.patient_id}", {"action": "accept"}, client=self.professional, token_from="/patients")
        page = self.text(self.patient.get("/notifications"))
        self.assertIn("Dr. Luis Cruz accepted your share request", page)

    def test_declining_a_share_notifies_the_patient_too(self):
        self.post("/share/request", {"consent": "1", "professional_user_id": str(self.professional_id)}, client=self.patient, token_from="/share")
        self.post(f"/patients/respond/{self.patient_id}", {"action": "decline"}, client=self.professional, token_from="/patients")
        self.assertIn("Dr. Luis Cruz declined your share request", self.text(self.patient.get("/notifications")))

    def test_a_follow_up_request_notifies_the_patient(self):
        self.post("/share/request", {"consent": "1", "professional_user_id": str(self.professional_id)}, client=self.patient, token_from="/share")
        self.post(f"/patients/respond/{self.patient_id}", {"action": "accept"}, client=self.professional, token_from="/patients")
        self.post(f"/patients/{self.patient_id}/follow-up", {"message": "Please screen again soon."},
                 client=self.professional, token_from=f"/patients/{self.patient_id}")
        page = self.text(self.patient.get("/notifications"))
        self.assertIn("Dr. Luis Cruz requested a follow-up screening", page)
        self.assertIn("Please screen again soon.", page)

    def test_a_clinical_review_notifies_the_patient(self):
        self.post("/share/request", {"consent": "1", "professional_user_id": str(self.professional_id)}, client=self.patient, token_from="/share")
        self.post(f"/patients/respond/{self.patient_id}", {"action": "accept"}, client=self.professional, token_from="/patients")
        assessment_id = self.add_assessment()
        self.post(f"/patients/{self.patient_id}/review", {"assessment_id": str(assessment_id), "note": "Looks stable."},
                 client=self.professional, token_from=f"/patients/{self.patient_id}")
        page = self.text(self.patient.get("/notifications"))
        self.assertIn("Dr. Luis Cruz added a note to one of your results", page)


class NotificationManagementTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.patient = self.signed_in()
        self.user_id = self.store.find_by_email("ana@example.com")["user_id"]
        from services.notification_store import get_notification_store
        from services import clock
        with self.app.app_context():
            self.store_notif = get_notification_store()
        self.notification_id = self.store_notif.create(self.user_id, "follow_up", "Test title", "Test body", "/dashboard", clock.now_utc())

    def test_a_fresh_notification_shows_as_unread_everywhere(self):
        page = self.text(self.patient.get("/notifications"))
        self.assertIn("notification-row is-unread", page)
        self.assertIn("Test title", page)
        self.assertIn("Test body", page)

    def test_marking_read_updates_the_page_and_the_bell_badge(self):
        self.post(f"/notifications/{self.notification_id}/read", {}, client=self.patient, token_from="/notifications")
        page = self.text(self.patient.get("/notifications"))
        self.assertNotIn("notification-row is-unread", page)
        self.assertNotIn("notif-badge", page)

    def test_marking_unread_again_restores_the_badge(self):
        self.post(f"/notifications/{self.notification_id}/read", {}, client=self.patient, token_from="/notifications")
        self.post(f"/notifications/{self.notification_id}/unread", {}, client=self.patient, token_from="/notifications")
        page = self.text(self.patient.get("/notifications"))
        self.assertIn("notification-row is-unread", page)
        self.assertIn("notif-badge", page)

    def test_deleting_removes_it_and_shows_the_empty_state(self):
        self.post(f"/notifications/{self.notification_id}/delete", {}, client=self.patient, token_from="/notifications")
        page = self.text(self.patient.get("/notifications"))
        self.assertNotIn("Test title", page)
        self.assertIn("No notifications yet", page)

    def test_mark_all_read_clears_every_unread_one(self):
        from services import clock
        self.store_notif.create(self.user_id, "follow_up", "Second", None, None, clock.now_utc())
        self.post("/notifications/mark-all-read", {}, client=self.patient, token_from="/notifications")
        page = self.text(self.patient.get("/notifications"))
        self.assertNotIn("notification-row is-unread", page)

    def test_someone_else_cannot_mark_or_delete_this_notification(self):
        other = self.signed_in(email="ben@example.com", full_name="Ben Cruz")
        response = self.post(f"/notifications/{self.notification_id}/read", {}, client=other, token_from="/notifications")
        self.assertEqual(response.status_code, 404)
        response = self.post(f"/notifications/{self.notification_id}/delete", {}, client=other, token_from="/notifications")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Test title", self.text(self.patient.get("/notifications")))   # untouched

    def test_an_anonymous_visitor_is_sent_to_sign_in(self):
        response = self.client.get("/notifications")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])


if __name__ == "__main__":
    unittest.main()
