"""
Checks for the Shared Assessments table on /patients (routes/authorization_routes.py patients): date tabs,
search, risk filter, review status filter. The filtering logic itself is covered by
tests/test_professional_overview.py; these confirm the page renders it.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase  # noqa: E402
from test_screening_flow import answers  # noqa: E402


class SharedAssessmentsFilterTests(AppTestCase):
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
        result = self.post("/screening", answers(), client=self.patient, token_from="/screening")
        self.assessment_id = result.headers["Location"].rstrip("/").split("/")[-1]

    def test_lists_the_shared_assessment(self):
        page = self.text(self.professional.get("/patients"))
        self.assertIn("Ana Reyes", page)
        self.assertIn(f"#{self.assessment_id}", page)
        self.assertIn("Awaiting review", page)

    def test_all_dates_tab_is_the_default(self):
        page = self.text(self.professional.get("/patients"))
        self.assertRegex(page, r'tab-link is-active"[^>]*>\s*All dates')

    def test_review_status_filter(self):
        page = self.text(self.professional.get("/patients?review_status=reviewed"))
        self.assertIn("No shared assessment matches these filters", page)
        page_awaiting = self.text(self.professional.get("/patients?review_status=awaiting_review"))
        self.assertIn(f"#{self.assessment_id}", page_awaiting)

    def test_reviewing_moves_it_out_of_awaiting_review(self):
        self.post(f"/patients/{self.patient_id}/review", {"assessment_id": str(self.assessment_id), "note": "Fine."},
                 client=self.professional, token_from=f"/patients/{self.patient_id}")
        page = self.text(self.professional.get("/patients?review_status=reviewed"))
        self.assertIn(f"#{self.assessment_id}", page)
        page_awaiting = self.text(self.professional.get("/patients?review_status=awaiting_review"))
        self.assertIn("No shared assessment matches these filters", page_awaiting)

    def test_search_by_assessment_id(self):
        page = self.text(self.professional.get(f"/patients?q={self.assessment_id}"))
        self.assertIn("Ana Reyes", page)

    def test_a_patient_record_never_appears_in_shared_assessments(self):
        response = self.post("/patient-records/new", {"full_name": "Own Patient", "date_of_birth": "1986-01-15", "country": "Other", "gender": "Female", "sex": "Female"},
                             client=self.professional, token_from="/patient-records/new")
        code = response.headers["Location"].split("/")[-2]
        self.post(f"/patient-records/{code}/screening", answers(), client=self.professional, token_from=f"/patient-records/{code}/screening")
        page = self.text(self.professional.get("/patients"))
        self.assertNotIn("Own Patient", page)

    def test_reset_clears_every_filter(self):
        page = self.text(self.professional.get("/patients?risk=high&review_status=reviewed&q=xyz"))
        self.assertIn('href="/patients"', page)

    def test_an_invalid_date_period_falls_back_to_all_instead_of_crashing(self):
        response = self.professional.get("/patients?date_period=not-real")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Ana Reyes", self.text(response))


if __name__ == "__main__":
    unittest.main()
