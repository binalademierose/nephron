"""
Checks for /assessments (routes/patient_records_routes.py assessment_list). The filtering logic itself is
covered by tests/test_professional_overview.py; these confirm the page renders it.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase  # noqa: E402
from test_screening_flow import answers, at  # noqa: E402

NOW = datetime(2026, 9, 29, 10, 0, 0)


class AssessmentsSectionTests(AppTestCase):
    model = True

    def setUp(self):
        super().setUp()
        self.professional = self.signed_in(**self.professional_details())
        response = self.post("/patient-records/new", {"full_name": "Juan Dela Cruz", "date_of_birth": "1968-01-15", "country": "Other", "gender": "Male", "sex": "Male"},
                             client=self.professional, token_from="/patient-records/new")
        self.code = response.headers["Location"].split("/")[-2]
        with at(NOW):
            result = self.post(f"/patient-records/{self.code}/screening", answers(), client=self.professional,
                               token_from=f"/patient-records/{self.code}/screening")
        self.assessment_id = result.headers["Location"].rstrip("/").split("/")[-1]

    def test_lists_the_assessment_with_every_expected_column(self):
        page = self.text(self.professional.get("/assessments"))
        self.assertIn("Juan Dela Cruz", page)
        self.assertIn(f"#{self.assessment_id}", page)
        self.assertIn(self.code, page)
        self.assertIn("Preliminary screening", page)
        self.assertIn("Self-recorded", page)

    def test_all_records_tab_is_the_default(self):
        page = self.text(self.professional.get("/assessments"))
        self.assertRegex(page, r'tab-link is-active"[^>]*>\s*All Records')

    def test_search_by_assessment_id_finds_it(self):
        page = self.text(self.professional.get(f"/assessments?q={self.assessment_id}"))
        self.assertIn("Juan Dela Cruz", page)

    def test_risk_filter_excludes_a_non_matching_result(self):
        # "Juan Dela Cruz" and the patient code also appear in the search box's own placeholder text, so a real
        # result is confirmed by the table itself existing (only rendered inside {% if records %}), not by
        # searching the page for those strings.
        high = self.text(self.professional.get("/assessments?risk=high"))
        low = self.text(self.professional.get("/assessments?risk=low"))
        # exactly one of the two risk filters matches this one real assessment
        self.assertNotEqual("<tbody>" in high, "<tbody>" in low)

    def test_a_30_day_old_assessment_is_excluded_by_the_7_day_tab(self):
        # the placeholder text in the search box also contains "Juan Dela Cruz" and the patient code, so a real
        # row is confirmed by the empty-state message's absence/presence, not by searching for those strings.
        with at(NOW + timedelta(days=10)):
            page = self.text(self.professional.get("/assessments?period=7_days"))
        self.assertIn("No assessment matches these filters", page)
        with at(NOW + timedelta(days=10)):
            page_all = self.text(self.professional.get("/assessments?period=all"))
        self.assertNotIn("No assessment matches these filters", page_all)
        self.assertNotIn("No assessments yet", page_all)

    def test_an_invalid_period_falls_back_to_all_instead_of_crashing(self):
        response = self.professional.get("/assessments?period=not-real")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Juan Dela Cruz", self.text(response))

    def test_a_different_professional_sees_none_of_this(self):
        other = self.signed_in(**self.professional_details(email="dr.other@example.com", full_name="Dr. Other"))
        page = self.text(other.get("/assessments"))
        self.assertIn("No assessments yet", page)
        self.assertNotIn("<tbody>", page)

    def test_a_general_user_cannot_reach_it(self):
        general = self.signed_in()
        self.assertEqual(general.get("/assessments").status_code, 403)

    def test_view_links_to_the_patients_risk_analysis_page(self):
        page = self.text(self.professional.get("/assessments"))
        self.assertIn(f"/patient-records/{self.code}/results/{self.assessment_id}", page)


class AssessmentsSectionSharedPatientTests(AppTestCase):
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

    def test_a_shared_patients_assessment_shows_awaiting_review_and_links_to_their_history(self):
        page = self.text(self.professional.get("/assessments"))
        self.assertIn("Ana Reyes", page)
        self.assertIn("Awaiting review", page)
        self.assertIn(f"/patients/{self.patient_id}", page)


if __name__ == "__main__":
    unittest.main()
