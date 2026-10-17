"""
Checks for /patient-reports (routes/patient_records_routes.py reports). The underlying data comes from the same
assessment_list() aggregation covered by tests/test_professional_overview.py; these confirm the page renders it,
with its own stats and download links.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase  # noqa: E402
from test_screening_flow import answers  # noqa: E402


class ReportsSectionTests(AppTestCase):
    model = True

    def setUp(self):
        super().setUp()
        self.professional = self.signed_in(**self.professional_details())
        response = self.post("/patient-records/new", {"full_name": "Juan Dela Cruz", "date_of_birth": "1968-01-15", "country": "Other", "gender": "Male", "sex": "Male"},
                             client=self.professional, token_from="/patient-records/new")
        self.code = response.headers["Location"].split("/")[-2]
        result = self.post(f"/patient-records/{self.code}/screening", answers(), client=self.professional,
                           token_from=f"/patient-records/{self.code}/screening")
        self.assessment_id = result.headers["Location"].rstrip("/").split("/")[-1]

    def test_the_stats_reflect_the_one_report(self):
        page = self.text(self.professional.get("/patient-reports"))
        self.assertRegex(page, r'Total Reports</p>\s*<p class="stat-value">1</p>')
        self.assertRegex(page, r'Reviewed Reports</p>\s*<p class="stat-value[^"]*">1</p>')      # self-recorded counts as reviewed

    def test_lists_the_report_with_a_download_form(self):
        page = self.text(self.professional.get("/patient-reports"))
        self.assertIn("Juan Dela Cruz", page)
        self.assertIn(f"#{self.assessment_id}", page)
        self.assertIn(f'action="/patient-records/{self.code}/reports/download"', page)

    def test_the_download_form_actually_produces_a_pdf(self):
        response = self.post(f"/patient-records/{self.code}/reports/download",
                             {"report_type": "single", "assessment_id": str(self.assessment_id)},
                             client=self.professional, token_from="/patient-reports")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b"%PDF"))

    def test_risk_filter(self):
        page_low = self.text(self.professional.get("/patient-reports?risk=low"))
        page_high = self.text(self.professional.get("/patient-reports?risk=high"))
        self.assertNotEqual("<tbody>" in page_low, "<tbody>" in page_high)

    def test_status_filter_self_recorded_counts_as_reviewed(self):
        page = self.text(self.professional.get("/patient-reports?review_status=reviewed"))
        self.assertIn(f"#{self.assessment_id}", page)
        page_awaiting = self.text(self.professional.get("/patient-reports?review_status=awaiting_review"))
        self.assertIn("No report matches these filters", page_awaiting)

    def test_search_by_patient_name(self):
        page = self.text(self.professional.get("/patient-reports?q=Dela+Cruz"))
        self.assertIn(f"#{self.assessment_id}", page)

    def test_a_different_professional_sees_an_empty_reports_page(self):
        other = self.signed_in(**self.professional_details(email="dr.other@example.com", full_name="Dr. Other"))
        page = self.text(other.get("/patient-reports"))
        self.assertIn("No reports yet", page)
        self.assertRegex(page, r'Total Reports</p>\s*<p class="stat-value">0</p>')

    def test_a_general_user_cannot_reach_it(self):
        general = self.signed_in()
        self.assertEqual(general.get("/patient-reports").status_code, 403)

    def test_the_sidebar_now_links_here(self):
        page = self.text(self.professional.get("/professional"))
        self.assertIn('href="/patient-reports"', page)


class ReportsSectionSharedPatientTests(AppTestCase):
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

    def test_a_shared_patients_report_downloads_through_the_existing_shared_route(self):
        page = self.text(self.professional.get("/patient-reports"))
        self.assertIn(f'action="/patients/{self.patient_id}/reports/download"', page)
        self.assertIn("Awaiting review", page)


if __name__ == "__main__":
    unittest.main()
