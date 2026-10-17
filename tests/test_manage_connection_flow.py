"""
Checks for /patients/<id>/connection (routes/authorization_routes.py manage_connection): a focused page for the
relationship between a professional and one shared patient. Run everything with:
python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase  # noqa: E402


class ManageConnectionTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.patient = self.signed_in()
        self.professional = self.signed_in(**self.professional_details())
        self.professional_id = self.store.find_by_email("dr.cruz@example.com")["user_id"]
        self.patient_id = self.store.find_by_email("ana@example.com")["user_id"]
        self.post("/share/request", {"consent": "1", "professional_user_id": str(self.professional_id)},
                 client=self.patient, token_from="/share")
        self.post(f"/patients/respond/{self.patient_id}", {"action": "accept"}, client=self.professional, token_from="/patients")

    def test_shows_the_connection_details(self):
        page = self.text(self.professional.get(f"/patients/{self.patient_id}/connection"))
        self.assertIn("Ana Reyes", page)
        self.assertIn("Active", page)
        self.assertIn("Requested", page)
        self.assertIn("Accepted", page)

    def test_ending_access_from_here_works_and_redirects_correctly(self):
        response = self.post(f"/patients/revoke/{self.patient_id}", {}, client=self.professional,
                             token_from=f"/patients/{self.patient_id}/connection")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.professional.get(f"/patients/{self.patient_id}/connection").status_code, 404)

    def test_a_pending_not_yet_accepted_request_has_no_connection_page(self):
        other_patient = self.signed_in(**{"email": "maria@example.com", "full_name": "Maria Santos"})
        self.post("/share/request", {"consent": "1", "professional_user_id": str(self.professional_id)},
                 client=other_patient, token_from="/share")
        other_id = self.store.find_by_email("maria@example.com")["user_id"]
        self.assertEqual(self.professional.get(f"/patients/{other_id}/connection").status_code, 404)

    def test_a_different_professional_cannot_see_it(self):
        other = self.signed_in(**self.professional_details(email="dr.other@example.com", full_name="Dr. Other"))
        self.assertEqual(other.get(f"/patients/{self.patient_id}/connection").status_code, 404)

    def test_a_general_user_cannot_reach_it(self):
        general = self.signed_in(**{"email": "someone@example.com", "full_name": "Someone Else"})
        self.assertEqual(general.get(f"/patients/{self.patient_id}/connection").status_code, 403)

    def test_the_history_page_links_to_manage_connection(self):
        page = self.text(self.professional.get(f"/patients/{self.patient_id}"))
        self.assertIn(f'href="/patients/{self.patient_id}/connection"', page)


if __name__ == "__main__":
    unittest.main()
