"""
Checks for the Enhanced / Laboratory assessment a professional performs for their own patient record
(/patient-records/<code>/enhanced) - the same lab validation, Stage 2 model, and eGFR as a General User's own
Enhanced Screening, built on the patient's latest Preliminary Screening.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase  # noqa: E402
from test_screening_flow import answers  # noqa: E402


class PatientRecordEnhancedTests(AppTestCase):
    model = "explainable"
    stage2_model = "explainable"

    def setUp(self):
        super().setUp()
        self.professional = self.signed_in(**self.professional_details())
        response = self.post("/patient-records/new", {"full_name": "Juan Dela Cruz", "date_of_birth": "1968-01-15", "country": "Other", "gender": "Male", "sex": "Male"},
                             client=self.professional, token_from="/patient-records/new")
        self.code = response.headers["Location"].split("/")[-2]
        self.user_id = self.app.extensions["patient_records_store"].get_by_code(self.code)["user_id"]

    def _screen(self):
        self.post(f"/patient-records/{self.code}/screening", answers(Age="58", Sex="Male"), client=self.professional,
                  token_from=f"/patient-records/{self.code}/screening")

    def test_without_a_preliminary_the_choice_is_explained_not_offered(self):
        page = self.text(self.professional.get(f"/patient-records/{self.code}/assess"))
        self.assertIn("Available once this patient has a Preliminary Screening", page)
        self.assertNotIn(f'href="/patient-records/{self.code}/enhanced"', page)
        response = self.professional.get(f"/patient-records/{self.code}/enhanced")
        self.assertEqual(response.status_code, 302)                       # sent back to choose, with a message

    def test_with_a_preliminary_the_choice_is_a_real_link(self):
        self._screen()
        page = self.text(self.professional.get(f"/patient-records/{self.code}/assess"))
        self.assertIn(f'href="/patient-records/{self.code}/enhanced"', page)
        self.assertNotIn("coming soon", page.lower())

    def test_the_form_is_the_lab_form_posting_to_the_patient_records_own_route(self):
        self._screen()
        page = self.text(self.professional.get(f"/patient-records/{self.code}/enhanced"))
        self.assertIn("Enhanced / Laboratory assessment", page)
        self.assertIn(f'action="/patient-records/{self.code}/enhanced"', page)
        self.assertIn("Serum creatinine", page)

    def test_submitting_saves_an_enhanced_assessment_under_the_patient_and_opens_risk_analysis(self):
        self._screen()
        response = self.post(f"/patient-records/{self.code}/enhanced", {"Serum_Creatinine": "1.1"}, client=self.professional,
                             token_from=f"/patient-records/{self.code}/enhanced")
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"/patient-records/{self.code}/results/", response.headers["Location"])
        rows = self.app.extensions["assessment_store"].list_assessments(self.user_id)
        self.assertEqual([r["assessment_type"] for r in rows], ["enhanced", "preliminary"])
        saved = self.app.extensions["assessment_store"].get_assessment(self.user_id, rows[0]["assessment_id"])
        self.assertIn("eGFR", saved["inputs"])
        self.assertEqual(saved["source_assessment_id"], rows[1]["assessment_id"])
        page = self.text(self.professional.get(response.headers["Location"]))
        self.assertIn("Enhanced", page)
        self.assertIn("Serum creatinine", page)                          # the lab answers are listed too

    def test_a_missing_creatinine_is_refused_and_nothing_is_saved(self):
        self._screen()
        response = self.post(f"/patient-records/{self.code}/enhanced", {"Sodium": "140"}, client=self.professional,
                             token_from=f"/patient-records/{self.code}/enhanced")
        self.assertEqual(response.status_code, 200)
        types = [r["assessment_type"] for r in self.app.extensions["assessment_store"].list_assessments(self.user_id)]
        self.assertEqual(types, ["preliminary"])

    def test_a_different_professional_gets_404(self):
        self._screen()
        other = self.signed_in(**self.professional_details(email="dr.other@example.com", full_name="Dr. Other"))
        self.assertEqual(other.get(f"/patient-records/{self.code}/enhanced").status_code, 404)

    def test_a_general_user_cannot_reach_it(self):
        general = self.signed_in()
        self.assertEqual(general.get(f"/patient-records/{self.code}/enhanced").status_code, 403)


class PatientRecordEnhancedUnavailableTests(PatientRecordEnhancedTests.__mro__[1]):
    model = True
    stage2_model = None

    def test_with_no_stage2_model_it_says_so_honestly(self):
        professional = self.signed_in(**self.professional_details())
        response = self.post("/patient-records/new", {"full_name": "Juan Dela Cruz", "date_of_birth": "1968-01-15", "country": "Other", "gender": "Male", "sex": "Male"},
                             client=professional, token_from="/patient-records/new")
        code = response.headers["Location"].split("/")[-2]
        self.post(f"/patient-records/{code}/screening", answers(), client=professional, token_from=f"/patient-records/{code}/screening")
        response = professional.get(f"/patient-records/{code}/enhanced")
        self.assertEqual(response.status_code, 503)
        self.assertIn("temporarily unavailable", self.text(response))


if __name__ == "__main__":
    unittest.main()


class PatientRecordLabUploadTests(PatientRecordEnhancedTests):
    """The professional's Enhanced assessment can read a patient's lab report with the same Tesseract OCR as a
    General User's own upload; the values only pre-fill the form."""

    def _upload(self, client=None, path=None):
        path = path or os.path.join(os.path.dirname(__file__), "fixtures", "sample_lab_report.png")
        token_page = self.text((client or self.professional).get(f"/patient-records/{self.code}/enhanced"))
        import re
        token = re.search(r'name="csrf_token" value="([^"]+)"', token_page).group(1)
        with open(path, "rb") as handle:
            return (client or self.professional).post(f"/patient-records/{self.code}/enhanced/upload",
                                                     data={"csrf_token": token, "document": (handle, os.path.basename(path))},
                                                     content_type="multipart/form-data")

    def test_the_enhanced_page_offers_an_upload(self):
        self._screen()
        self.assertIn(f'action="/patient-records/{self.code}/enhanced/upload"', self.text(self.professional.get(f"/patient-records/{self.code}/enhanced")))

    def test_an_uploaded_report_is_read_and_prefills_the_form_for_checking(self):
        self._screen()
        response = self._upload()
        self.assertEqual(response.status_code, 302)
        self.assertIn("document=", response.headers["Location"])
        page = self.text(self.professional.get(response.headers["Location"]))
        self.assertIn("Suggested from the upload", page)
        self.assertIn("against the patient&#39;s report", page)          # a professional checks the PATIENT's report
        self.assertRegex(page, r'id="f-Serum_Creatinine"[^>]*value="[0-9.]+"')       # read by Tesseract, shown for checking

    def test_confirming_the_prefilled_values_saves_and_marks_the_document_confirmed(self):
        self._screen()
        location = self._upload().headers["Location"]
        document_id = int(location.split("document=")[-1])
        refused = self.post(location, {"Serum_Creatinine": "1.2"}, client=self.professional, token_from=location)
        self.assertIn("Please confirm that this report is the patient", self.text(refused))   # must be vouched for first
        response = self.post(location, {"Serum_Creatinine": "1.2", "attest": "1"}, client=self.professional, token_from=location)
        self.assertIn("/results/", response.headers["Location"])
        stored = self.app.extensions["lab_document_store"].get_document(self.user_id, document_id)
        self.assertEqual(stored["status"], "confirmed")

    def test_another_professional_cannot_upload_for_this_patient(self):
        self._screen()
        other = self.signed_in(**self.professional_details(email="dr.other3@example.com", full_name="Dr. Other"))
        token = re.search(r'name="csrf_token" value="([^"]+)"', self.text(other.get("/patient-records"))).group(1)
        self.assertEqual(other.post(f"/patient-records/{self.code}/enhanced/upload", data={"csrf_token": token}).status_code, 404)
