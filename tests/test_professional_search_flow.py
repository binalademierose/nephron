"""
Checks for /search (routes/account_routes.py professional_search). The matching logic itself is covered by
tests/test_professional_overview.py; these confirm the page renders it and links go where they should.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase  # noqa: E402
from test_screening_flow import answers  # noqa: E402


class SearchPageTests(AppTestCase):
    model = True

    def setUp(self):
        super().setUp()
        self.professional = self.signed_in(**self.professional_details())
        response = self.post("/patient-records/new", {"full_name": "Juan Dela Cruz", "date_of_birth": "1968-01-15", "country": "Other", "gender": "Male", "sex": "Male"},
                             client=self.professional, token_from="/patient-records/new")
        self.code = response.headers["Location"].split("/")[-2]
        result = self.post(f"/patient-records/{self.code}/screening", answers(), client=self.professional, token_from=f"/patient-records/{self.code}/screening")
        self.assessment_id = result.headers["Location"].rstrip("/").split("/")[-1]

    def test_no_query_shows_the_search_box_only(self):
        page = self.text(self.professional.get("/search"))
        self.assertIn("Search", page)
        self.assertNotIn("Patients (", page)

    def test_searching_by_name_finds_the_patient_and_their_assessment(self):
        page = self.text(self.professional.get("/search?q=Dela+Cruz"))
        self.assertIn("Juan Dela Cruz", page)
        self.assertIn("Patients (1)", page)
        self.assertIn("Assessments (1)", page)

    def test_searching_by_patient_code_finds_the_patient(self):
        page = self.text(self.professional.get(f"/search?q={self.code}"))
        self.assertIn("Juan Dela Cruz", page)

    def test_searching_by_assessment_id_links_straight_to_risk_analysis(self):
        page = self.text(self.professional.get(f"/search?q={self.assessment_id}"))
        self.assertIn(f"/patient-records/{self.code}/results/{self.assessment_id}", page)

    def test_a_no_match_search_says_so_plainly(self):
        page = self.text(self.professional.get("/search?q=Nobody+Here"))
        self.assertIn("No patient matches", page)
        self.assertIn("No assessment matches", page)

    def test_a_different_professional_finds_nothing_for_the_same_terms(self):
        other = self.signed_in(**self.professional_details(email="dr.other@example.com", full_name="Dr. Other"))
        page = self.text(other.get("/search?q=Dela+Cruz"))
        self.assertIn("Patients (0)", page)
        self.assertIn("Assessments (0)", page)

    def test_a_general_user_cannot_reach_it(self):
        general = self.signed_in()
        self.assertEqual(general.get("/search").status_code, 403)


class SearchLinksToSharedPatientTests(AppTestCase):
    model = True

    def setUp(self):
        super().setUp()
        self.patient = self.signed_in()
        self.professional = self.signed_in(**self.professional_details())
        self.professional_id = self.store.find_by_email("dr.cruz@example.com")["user_id"]
        self.patient_id = self.store.find_by_email("ana@example.com")["user_id"]
        self.post("/share/request", {"consent": "1", "professional_user_id": str(self.professional_id)},
                 client=self.patient, token_from="/share")
        self.post(f"/patients/respond/{self.patient_id}", {"action": "accept"}, client=self.professional, token_from="/patients")
        self.post("/screening", answers(), client=self.patient, token_from="/screening")

    def test_a_shared_patient_links_to_their_history_page_not_a_risk_analysis_url(self):
        page = self.text(self.professional.get("/search?q=Ana"))
        self.assertIn("Ana Reyes", page)
        self.assertIn(f"/patients/{self.patient_id}", page)
        self.assertNotIn("/patient-records/", page)


if __name__ == "__main__":
    unittest.main()
