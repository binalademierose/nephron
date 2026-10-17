"""
Checks for the report-download routes: a patient downloading their own PDF, and an authorized professional
downloading one for a patient - both the single-result and whole-history kinds, and the include_reviews choice.
Content checks need pypdf (see tests/test_pdf_report.py) and are skipped without it.
Run everything with:   python -m unittest discover -s tests -v
"""
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import AppTestCase  # noqa: E402

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

NEEDS_PYPDF = unittest.skipUnless(PYPDF_AVAILABLE, "needs pypdf to read the generated PDF back (pip install pypdf)")


def _text_of(pdf_bytes):
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


class PatientReportTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.patient = self.signed_in()
        self.assessment_id = self.add_assessment(probability=0.708, classification="high")

    def test_the_reports_page_lists_assessments_to_choose_from(self):
        page = self.text(self.patient.get("/reports"))
        self.assertIn("Preliminary screening", page)

    def test_the_reports_page_with_no_assessments_says_so(self):
        other = self.signed_in(email="ben@example.com", full_name="Ben Cruz")
        page = self.text(other.get("/reports"))
        self.assertIn("no assessments yet", page)

    def test_downloading_a_single_result_returns_a_real_pdf(self):
        response = self.patient.post("/reports/download", data={"report_type": "single", "assessment_id": str(self.assessment_id),
                                                                 "csrf_token": self.csrf(self.patient, "/reports")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertTrue(response.data.startswith(b"%PDF"))

    def test_downloading_the_whole_history_returns_a_real_pdf(self):
        response = self.patient.post("/reports/download", data={"report_type": "history",
                                                                 "csrf_token": self.csrf(self.patient, "/reports")})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b"%PDF"))

    def test_a_patient_cannot_download_someone_elses_assessment(self):
        other = self.signed_in(email="ben@example.com", full_name="Ben Cruz")
        other_assessment = self.add_assessment(email="ben@example.com")
        response = self.patient.post("/reports/download", data={"report_type": "single", "assessment_id": str(other_assessment),
                                                                 "csrf_token": self.csrf(self.patient, "/reports")})
        self.assertEqual(response.status_code, 404)

    @NEEDS_PYPDF
    def test_the_pdf_contains_the_real_result(self):
        response = self.patient.post("/reports/download", data={"report_type": "single", "assessment_id": str(self.assessment_id),
                                                                 "csrf_token": self.csrf(self.patient, "/reports")})
        text = _text_of(response.data)
        self.assertIn("Ana Reyes", text)
        self.assertIn("70.8%", text)

    @NEEDS_PYPDF
    def test_unchecking_include_reviews_leaves_notes_out(self):
        from services import clinical_reviews
        from datetime import datetime
        clinical_reviews.for_assessment  # noqa (imported for clarity of what is being exercised)
        self.app.extensions["clinical_review_store"].add_review(
            self.assessment_id, None, "Dr. Maria Cruz", "Nephrologist", "Please recheck soon.", datetime(2026, 9, 20))
        with_reviews = self.patient.post("/reports/download", data={"report_type": "single", "assessment_id": str(self.assessment_id),
                                                                     "include_reviews": "on", "csrf_token": self.csrf(self.patient, "/reports")})
        without_reviews = self.patient.post("/reports/download", data={"report_type": "single", "assessment_id": str(self.assessment_id),
                                                                       "csrf_token": self.csrf(self.patient, "/reports")})
        self.assertIn("Please recheck soon.", _text_of(with_reviews.data))
        self.assertNotIn("Please recheck soon.", _text_of(without_reviews.data))


class ProfessionalReportTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.patient = self.signed_in()
        self.professional = self.signed_in(**self.professional_details())
        self.professional_id = self.store.find_by_email("dr.cruz@example.com")["user_id"]
        self.patient_id = self.store.find_by_email("ana@example.com")["user_id"]
        self.assessment_id = self.add_assessment(probability=0.708, classification="high")
        self.post("/share/request", {"consent": "1", "professional_user_id": str(self.professional_id)}, client=self.patient, token_from="/share")
        self.post(f"/patients/respond/{self.patient_id}", {"action": "accept"}, client=self.professional, token_from="/patients")

    def test_an_authorized_professional_can_download_a_report_for_their_patient(self):
        response = self.post(f"/patients/{self.patient_id}/reports/download",
                             {"report_type": "single", "assessment_id": str(self.assessment_id)},
                             client=self.professional, token_from=f"/patients/{self.patient_id}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b"%PDF"))

    def test_an_authorized_professional_can_download_the_whole_history(self):
        response = self.post(f"/patients/{self.patient_id}/reports/download", {"report_type": "history"},
                             client=self.professional, token_from=f"/patients/{self.patient_id}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b"%PDF"))

    def test_a_professional_who_is_not_authorized_cannot_download_a_report(self):
        other = self.signed_in(**self.professional_details(email="dr.other@example.com", full_name="Dr. Ana Other"))
        response = self.post(f"/patients/{self.patient_id}/reports/download", {"report_type": "history"},
                             client=other, token_from="/patients")
        self.assertEqual(response.status_code, 404)

    def test_a_patient_cannot_reach_the_professional_only_download_route(self):
        response = self.post(f"/patients/{self.patient_id}/reports/download", {"report_type": "history"},
                             client=self.patient, token_from="/share")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()


class PatientRecordReportDownloadTests(AppTestCase):
    model = True

    def setUp(self):
        super().setUp()
        self.professional = self.signed_in(**self.professional_details())
        response = self.post("/patient-records/new", {"full_name": "Juan Dela Cruz", "date_of_birth": "1968-01-15", "country": "Other", "gender": "Male", "sex": "Male"},
                             client=self.professional, token_from="/patient-records/new")
        self.code = response.headers["Location"].split("/")[-2]
        from test_screening_flow import answers
        result = self.post(f"/patient-records/{self.code}/screening", answers(), client=self.professional,
                           token_from=f"/patient-records/{self.code}/screening")
        self.assessment_id = result.headers["Location"].rstrip("/").split("/")[-1]

    def test_the_owning_professional_can_download_a_single_report(self):
        response = self.post(f"/patient-records/{self.code}/reports/download",
                             {"report_type": "single", "assessment_id": str(self.assessment_id)},
                             client=self.professional, token_from=f"/patient-records/{self.code}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b"%PDF"))

    def test_the_owning_professional_can_download_the_whole_history(self):
        response = self.post(f"/patient-records/{self.code}/reports/download", {"report_type": "history"},
                             client=self.professional, token_from=f"/patient-records/{self.code}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b"%PDF"))

    def test_a_different_professional_cannot_download_it(self):
        other = self.signed_in(**self.professional_details(email="dr.other@example.com", full_name="Dr. Other"))
        response = self.post(f"/patient-records/{self.code}/reports/download", {"report_type": "history"},
                             client=other, token_from="/patient-records")
        self.assertEqual(response.status_code, 404)

    def test_a_general_user_cannot_reach_it(self):
        general = self.signed_in()
        response = self.post(f"/patient-records/{self.code}/reports/download", {"report_type": "history"},
                             client=general, token_from="/dashboard")
        self.assertEqual(response.status_code, 403)

    def test_an_unknown_patient_code_is_404(self):
        response = self.post("/patient-records/NPH-9999/reports/download", {"report_type": "history"},
                             client=self.professional, token_from="/patient-records")
        self.assertEqual(response.status_code, 404)
