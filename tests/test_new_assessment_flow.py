"""
Checks for /assessments/new (choose existing or new patient) and /assessments/new/existing (search, see basic
info, start). Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase  # noqa: E402
from test_screening_flow import answers  # noqa: E402


class NewAssessmentChoiceTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.professional = self.signed_in(**self.professional_details())

    def test_shows_both_choices(self):
        page = self.text(self.professional.get("/assessments/new"))
        self.assertIn("Existing Patient", page)
        self.assertIn("New Patient", page)
        self.assertIn('href="/assessments/new/existing"', page)
        self.assertIn('href="/patient-records/new"', page)

    def test_a_general_user_cannot_reach_it(self):
        general = self.signed_in()
        self.assertEqual(general.get("/assessments/new").status_code, 403)


class AssessExistingPatientTests(AppTestCase):
    model = True

    def setUp(self):
        super().setUp()
        self.professional = self.signed_in(**self.professional_details())
        response = self.post("/patient-records/new", {"full_name": "Juan Dela Cruz", "date_of_birth": "1968-01-15", "country": "Other", "gender": "Male", "sex": "Male"},
                             client=self.professional, token_from="/patient-records/new")
        self.code = response.headers["Location"].split("/")[-2]

    def test_no_query_shows_no_results_yet(self):
        page = self.text(self.professional.get("/assessments/new/existing"))
        self.assertNotIn("Start assessment", page)

    def test_searching_shows_the_patients_basic_info_before_starting(self):
        page = self.text(self.professional.get("/assessments/new/existing?q=Dela+Cruz"))
        self.assertIn("Juan Dela Cruz", page)
        self.assertIn(self.code, page)
        self.assertIn("58 years old", page)
        self.assertIn("Male", page)
        self.assertIn("No assessment yet", page)

    def test_start_assessment_links_straight_to_choose_assessment_for_that_patient(self):
        page = self.text(self.professional.get("/assessments/new/existing?q=Juan"))
        self.assertIn(f'href="/patient-records/{self.code}/assess"', page)

    def test_a_screened_patient_shows_their_latest_result_in_the_search_row(self):
        self.post(f"/patient-records/{self.code}/screening", answers(), client=self.professional, token_from=f"/patient-records/{self.code}/screening")
        page = self.text(self.professional.get("/assessments/new/existing?q=Juan"))
        self.assertIn("Last assessment", page)
        self.assertNotIn("No assessment yet", page)

    def test_a_no_match_search_says_so_plainly(self):
        page = self.text(self.professional.get("/assessments/new/existing?q=Nobody+Here"))
        self.assertIn("No patient matches", page)

    def test_never_finds_another_professionals_patient(self):
        other = self.signed_in(**self.professional_details(email="dr.other@example.com", full_name="Dr. Other"))
        page = self.text(other.get("/assessments/new/existing?q=Dela+Cruz"))
        self.assertIn("No patient matches", page)

    def test_a_general_user_cannot_reach_it(self):
        general = self.signed_in()
        self.assertEqual(general.get("/assessments/new/existing").status_code, 403)


if __name__ == "__main__":
    unittest.main()
