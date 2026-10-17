"""
Checks for the sharing pages: a patient searching for and requesting a professional, the professional accepting
or declining, viewing an authorized patient's history, and either side ending it. Uses in-memory stores; no
database and no ML model needed (these pages never touch the screening model).
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import AppTestCase  # noqa: E402


class SharingFlowTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.patient = self.signed_in()                                         # ana@example.com, general
        self.professional = self.signed_in(**self.professional_details())       # dr.cruz@example.com, professional
        self.professional_id = self.store.find_by_email("dr.cruz@example.com")["user_id"]
        self.patient_id = self.store.find_by_email("ana@example.com")["user_id"]

    def request_from_patient(self):
        return self.post("/share/request", {"consent": "1", "professional_user_id": str(self.professional_id)},
                         client=self.patient, token_from="/share")

    def test_a_patient_can_find_a_professional_by_partial_name(self):
        page = self.text(self.patient.get("/share?q=cruz"))
        self.assertIn("Dr. Luis Cruz", page)
        self.assertIn("Nephrologist", page)

    def test_the_live_search_endpoint_returns_the_same_match_as_json(self):
        response = self.patient.get("/share/search?q=cruz")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["full_name"], "Dr. Luis Cruz")
        self.assertEqual(data["results"][0]["profession_title"], "Nephrologist")

    def test_the_live_search_endpoint_never_returns_the_patients_own_account(self):
        response = self.patient.get("/share/search?q=ana")
        data = response.get_json()
        self.assertEqual(data["results"], [])

    def test_the_live_search_endpoint_with_no_match_returns_an_empty_list(self):
        response = self.patient.get("/share/search?q=nobody-at-all-xyz")
        self.assertEqual(response.get_json()["results"], [])

    def test_a_professional_cannot_reach_the_live_search_endpoint(self):
        response = self.professional.get("/share/search?q=cruz")
        self.assertEqual(response.status_code, 403)

    def test_a_patient_can_find_a_professional_by_exact_email(self):
        page = self.text(self.patient.get("/share?q=dr.cruz@example.com"))
        self.assertIn("Dr. Luis Cruz", page)

    def test_searching_a_name_with_no_match_says_so_plainly(self):
        page = self.text(self.patient.get("/share?q=nobody at all"))
        self.assertIn("No professional account matches", page)

    def test_a_general_account_never_turns_up_in_the_professional_search(self):
        self.signed_in(email="ben@example.com", full_name="Ben Cruz")
        page = self.text(self.patient.get("/share?q=cruz"))
        self.assertIn("Dr. Luis Cruz", page)
        self.assertNotIn("Ben Cruz", page)

    def test_requesting_shows_up_as_pending_for_both_sides(self):
        self.request_from_patient()
        patient_page = self.text(self.patient.get("/share"))
        self.assertIn("Dr. Luis Cruz", patient_page)
        self.assertIn("Pending", patient_page)
        professional_page = self.text(self.professional.get("/patients"))
        self.assertIn("Ana Reyes", professional_page)

    def test_the_professional_accepting_makes_it_authorized_both_sides_agree(self):
        self.request_from_patient()
        self.post(f"/patients/respond/{self.patient_id}", {"action": "accept"}, client=self.professional, token_from="/patients")
        self.assertIn("Accepted", self.text(self.professional.get("/patients")))
        self.assertIn("Accepted", self.text(self.patient.get("/share")))
        from services.authorizations import is_authorized
        self.assertTrue(is_authorized(self.app.extensions["authorization_store"], self.patient_id, self.professional_id))

    def test_the_professional_declining_leaves_it_not_authorized(self):
        self.request_from_patient()
        self.post(f"/patients/respond/{self.patient_id}", {"action": "decline"}, client=self.professional, token_from="/patients")
        from services.authorizations import is_authorized
        self.assertFalse(is_authorized(self.app.extensions["authorization_store"], self.patient_id, self.professional_id))
        self.assertIn("Declined", self.text(self.patient.get("/share")))

    def test_after_a_decline_the_patient_can_request_again(self):
        self.request_from_patient()
        self.post(f"/patients/respond/{self.patient_id}", {"action": "decline"}, client=self.professional, token_from="/patients")
        self.request_from_patient()
        page = self.text(self.patient.get("/share"))
        self.assertIn("Pending", page)

    def test_an_accepted_professional_can_see_the_patients_history(self):
        self.request_from_patient()
        self.post(f"/patients/respond/{self.patient_id}", {"action": "accept"}, client=self.professional, token_from="/patients")
        self.add_assessment(probability=0.42, classification="high")
        page = self.text(self.professional.get(f"/patients/{self.patient_id}"))
        self.assertIn("Ana Reyes", page)
        self.assertIn("42", page)

    def test_a_professional_cannot_see_a_patients_history_who_never_authorized_them(self):
        response = self.professional.get(f"/patients/{self.patient_id}")
        self.assertEqual(response.status_code, 404)

    def test_a_professional_cannot_see_history_of_a_patient_who_only_has_a_pending_request(self):
        self.request_from_patient()
        response = self.professional.get(f"/patients/{self.patient_id}")
        self.assertEqual(response.status_code, 404)

    def test_the_patient_can_revoke_an_accepted_authorization(self):
        self.request_from_patient()
        self.post(f"/patients/respond/{self.patient_id}", {"action": "accept"}, client=self.professional, token_from="/patients")
        self.post(f"/share/revoke/{self.professional_id}", {}, client=self.patient, token_from="/share")
        from services.authorizations import is_authorized
        self.assertFalse(is_authorized(self.app.extensions["authorization_store"], self.patient_id, self.professional_id))
        response = self.professional.get(f"/patients/{self.patient_id}")
        self.assertEqual(response.status_code, 404)

    def test_the_professional_can_also_end_an_accepted_authorization(self):
        self.request_from_patient()
        self.post(f"/patients/respond/{self.patient_id}", {"action": "accept"}, client=self.professional, token_from="/patients")
        self.post(f"/patients/revoke/{self.patient_id}", {}, client=self.professional, token_from="/patients")
        from services.authorizations import is_authorized
        self.assertFalse(is_authorized(self.app.extensions["authorization_store"], self.patient_id, self.professional_id))

    def test_a_patient_cannot_request_their_own_account_even_by_crafting_the_form(self):
        self.post("/share/request", {"consent": "1", "professional_user_id": str(self.patient_id)}, client=self.patient, token_from="/share")
        self.assertIn("cannot request access to your own account", self.text(self.patient.get("/share")))

    def test_a_patient_cannot_request_a_general_account_by_crafting_the_form(self):
        self.signed_in(email="ben@example.com", full_name="Ben Cruz")
        ben_id = self.store.find_by_email("ben@example.com")["user_id"]
        self.post("/share/request", {"consent": "1", "professional_user_id": str(ben_id)}, client=self.patient, token_from="/share")
        self.assertIn("could not be found", self.text(self.patient.get("/share")))

    def test_one_patients_requests_are_never_shown_to_another_patient(self):
        self.request_from_patient()
        other_patient = self.signed_in(email="ben@example.com", full_name="Ben Cruz")
        page = self.text(other_patient.get("/share"))
        self.assertNotIn("Dr. Luis Cruz", page)

    def test_a_general_user_cannot_reach_the_professionals_pages(self):
        response = self.patient.get("/patients")
        self.assertEqual(response.status_code, 403)

    def test_a_professional_cannot_reach_the_patients_share_page(self):
        response = self.professional.get("/share")
        self.assertEqual(response.status_code, 403)

    def test_the_share_button_on_a_result_page_leads_here(self):
        self.add_assessment()
        row = self.app.extensions["assessment_store"].list_assessments(self.patient_id)[0]
        page = self.text(self.patient.get(f"/results/{row['assessment_id']}"))
        self.assertIn(f'href="/share"', page)


if __name__ == "__main__":
    unittest.main()
