"""
Checks for the Enhanced Screening pages: upload, OCR, confirmation, analysis, and the saved result.

Uses STAND-IN models (tests/model_fixtures.py) for both Stage 1 and Stage 2, and in-memory stores. Proves the rules:
Enhanced Screening needs a Preliminary assessment to extend; nothing OCR proposes is ever saved without the person
confirming it; a value outside its range is refused; people only ever see their own uploads and results.
Run everything with:   python -m unittest discover -s tests -v
"""
import io
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import AppTestCase  # noqa: E402
import model_fixtures  # noqa: E402

from services import lab_contract, screening_contract  # noqa: E402

NEEDS_ML = unittest.skipUnless(model_fixtures.libraries_available(), "needs scikit-learn, pandas, numpy and joblib (see requirements.txt)")
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
SAMPLE_REPORT = os.path.join(FIXTURES, "sample_lab_report.png")

try:
    import pytesseract
    pytesseract.get_tesseract_version()
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False
NEEDS_OCR = unittest.skipUnless(OCR_AVAILABLE, "needs tesseract and pytesseract")


def stage1_answers(**changes):
    form = {"Country": "Other", "Gender": "Female", "Sex": "Female", "Ethnicity": "Asian", "Age": "48", "height_cm": "160", "weight_kg": "70",
            "Diabetes": "1", "Hypertension": "0", "Cardiovascular_Disease": "0", "Heart_Failure": "0", "Hyperlipidemia": "1",
            "Kidney_Stones": "0", "Recurrent_UTI": "0", "Autoimmune_Disease": "0", "Family_History_CKD": "1",
            "ACE_Inhibitor": "0", "ARB": "1", "Diabetes_Medication": "1", "Diuretic": "0", "Statin": "1", "NSAID_Usage": "0",
            "Smoking_Status": "Never", "Alcohol_Consumption": "None", "Physical_Activity_Level": "Light",
            "Exercise_Hours_Per_Week": "2.5", "Water_Intake_L": "1.8", "Fast_Food_Frequency_Per_Week": "2", "Sleep_Duration_Hours": "6.8",
            "SugaryDrinksAddedSugar": "None", "UltraProcessedFoodFrequency": "Never", "SaturatedFatDairyIntake": "Low"}
    form.update(changes)
    return form


@NEEDS_ML
class NoPreliminaryTests(AppTestCase):
    stage2_model = True

    def test_enhanced_screening_is_blocked_until_a_preliminary_screening_exists(self):
        member = self.signed_in()
        page = self.text(member.get("/enhanced-screening"))
        self.assertIn("Complete a preliminary screening first", page)
        self.assertIn('href="/screening"', page)
        self.assertIn("Complete a preliminary screening first", self.text(member.get("/enhanced-screening/manual")))
        page = self.text(self.post("/enhanced-screening/upload", {}, client=member, token_from="/enhanced-screening"))
        self.assertIn("Complete a preliminary screening first", page)


@NEEDS_ML
class ModelUnavailableTests(AppTestCase):
    stage2_model = None       # no Stage 2 model installed

    def test_enhanced_screening_is_honestly_unavailable_without_a_model(self):
        member = self.signed_in()
        self.add_assessment(inputs=screening_contract.validate_answers(screening_contract.load_catalog(), stage1_answers())[0])
        page = self.text(member.get("/enhanced-screening"))
        self.assertIn("Enhanced Screening is temporarily unavailable", page)


@NEEDS_ML
class EnhancedScreeningTestCase(AppTestCase):
    stage2_model = "explainable"

    def setUp(self):
        super().setUp()
        self.member = self.signed_in()
        self.catalog = screening_contract.load_catalog()
        values, inputs, errors = screening_contract.validate_answers(self.catalog, stage1_answers())
        self.assertEqual(errors, {})
        self.source_id = self.add_assessment(inputs=inputs)
        self.lab_catalog = lab_contract.load_lab_catalog()

    def confirm_form(self, page):
        return set(re.findall(r'name="([A-Za-z0-9_]+)"', page)) & {f["name"] for f in self.lab_catalog["fields"]}


class ManualEntryTests(EnhancedScreeningTestCase):
    def test_the_manual_form_lists_every_lab_field_grouped_and_only_creatinine_is_marked_required(self):
        page = self.text(self.member.get("/enhanced-screening/manual"))
        self.assertEqual(self.confirm_form(page), {f["name"] for f in self.lab_catalog["fields"]})
        for group in self.lab_catalog["groups"]:
            self.assertIn(group["title"], page)
        self.assertEqual(page.count('<span class="required-mark"'), 1)

    def test_only_creatinine_is_enough_to_get_a_result(self):
        response = self.post("/enhanced-screening/confirm", {"Serum_Creatinine": "1.1"}, client=self.member, token_from="/enhanced-screening/manual")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].startswith("/results/"))
        page = self.text(self.member.get(response.headers["Location"]))
        self.assertIn("Risk Classification", page)
        self.assertIn("Enhanced Screening", page)

    def test_the_new_assessment_is_linked_back_to_the_preliminary_one_it_extends(self):
        response = self.post("/enhanced-screening/confirm", {"Serum_Creatinine": "1.1"}, client=self.member, token_from="/enhanced-screening/manual")
        assessment_id = int(response.headers["Location"].rsplit("/", 1)[1])
        row = self.app.extensions["assessment_store"].get_assessment(self.store.find_by_email("ana@example.com")["user_id"], assessment_id)
        self.assertEqual(row["assessment_type"], "enhanced")
        self.assertEqual(row["source_assessment_id"], self.source_id)
        page = self.text(self.member.get(f"/results/{assessment_id}"))
        self.assertIn(f'href="/results/{self.source_id}"', page)
        self.assertIn("View the preliminary screening it extends", page)

    def test_missing_creatinine_is_refused_and_nothing_is_saved(self):
        before = len(self.app.extensions["assessment_store"].list_assessments(self.store.find_by_email("ana@example.com")["user_id"]))
        page = self.text(self.post("/enhanced-screening/confirm", {"Sodium": "140"}, client=self.member, token_from="/enhanced-screening/manual"))
        self.assertIn("is required", page)
        after = len(self.app.extensions["assessment_store"].list_assessments(self.store.find_by_email("ana@example.com")["user_id"]))
        self.assertEqual(before, after)

    def test_a_value_outside_the_plausible_range_is_refused_and_the_form_is_redisplayed(self):
        page = self.text(self.post("/enhanced-screening/confirm", {"Serum_Creatinine": "1.1", "Sodium": "9999"},
                                   client=self.member, token_from="/enhanced-screening/manual"))
        self.assertIn("must be between", page)
        self.assertIn('value="1.1"', page)                        # the good value the person typed is not lost

    def test_more_lab_values_can_be_given_and_are_all_used(self):
        response = self.post("/enhanced-screening/confirm", {"Serum_Creatinine": "1.1", "Sodium": "140", "HbA1c": "5.4"},
                             client=self.member, token_from="/enhanced-screening/manual")
        assessment_id = int(response.headers["Location"].rsplit("/", 1)[1])
        row = self.app.extensions["assessment_store"].get_assessment(self.store.find_by_email("ana@example.com")["user_id"], assessment_id)
        self.assertEqual(row["inputs"]["Sodium"], 140.0)
        self.assertEqual(row["inputs"]["HbA1c"], 5.4)

    def test_alcohol_none_from_the_preliminary_answer_does_not_break_analysis(self):
        # stage1_answers() sets Alcohol_Consumption to "None" (does not drink), which the Stage 2 model has never
        # seen (see services/model_service_stage2.STAGE1_VOCABULARY_GAPS) - this must not surface as a server error.
        response = self.post("/enhanced-screening/confirm", {"Serum_Creatinine": "1.1"}, client=self.member, token_from="/enhanced-screening/manual")
        self.assertEqual(response.status_code, 302)

    def test_the_result_shows_two_explanation_cards(self):
        response = self.post("/enhanced-screening/confirm", {"Serum_Creatinine": "3.4"}, client=self.member, token_from="/enhanced-screening/manual")
        page = self.text(self.member.get(response.headers["Location"]))
        self.assertIn("What raised your estimate", page)
        self.assertIn("What lowered your estimate", page)


class UploadTests(EnhancedScreeningTestCase):
    def upload(self, path=SAMPLE_REPORT, content_type="image/png", filename="report.png"):
        token = self.csrf(self.member, "/enhanced-screening")
        with open(path, "rb") as handle:
            data = handle.read()
        return self.member.post("/enhanced-screening/upload", data={"csrf_token": token,
                                "document": (io.BytesIO(data), filename, content_type)}, content_type="multipart/form-data")

    @NEEDS_OCR
    def test_uploading_a_real_report_redirects_to_a_confirmation_form_with_suggested_values(self):
        response = self.upload()
        self.assertEqual(response.status_code, 302)
        self.assertRegex(response.headers["Location"], r"^/enhanced-screening/confirm/\d+$")
        page = self.text(self.member.get(response.headers["Location"]))
        self.assertIn("We found", page)
        self.assertIn("Suggested from the upload", page)
        self.assertIn('value="1.4"', page)                        # the report's own Serum Creatinine value
        self.assertIn("Found in the upload", page)

    @NEEDS_OCR
    def test_confirming_the_suggested_values_saves_a_result_and_marks_the_document_confirmed(self):
        response = self.upload()
        lab_document_id = int(response.headers["Location"].rsplit("/", 1)[1])
        page = self.text(self.member.get(response.headers["Location"]))
        form = dict(re.findall(r'name="([A-Za-z_]+)"[^>]*value="([^"]*)"', page))
        form = {k: v for k, v in form.items() if k in {f["name"] for f in self.lab_catalog["fields"]}}
        refused = self.post(response.headers["Location"], form, client=self.member, token_from=response.headers["Location"])
        self.assertEqual(refused.status_code, 200)                          # an uploaded report needs the person's confirmation
        self.assertIn("Please confirm that this report is yours", self.text(refused))
        form["attest"] = "1"
        result = self.post(response.headers["Location"], form, client=self.member, token_from=response.headers["Location"])
        self.assertEqual(result.status_code, 302)
        document = self.app.extensions["lab_document_store"].get_document(self.store.find_by_email("ana@example.com")["user_id"], lab_document_id)
        self.assertEqual(document["status"], "confirmed")
        self.assertEqual(f"/results/{document['assessment_id']}", result.headers["Location"])

    def test_a_disguised_non_image_file_is_rejected_before_ocr_even_runs(self):
        token = self.csrf(self.member, "/enhanced-screening")
        response = self.member.post("/enhanced-screening/upload", data={"csrf_token": token,
                                    "document": (io.BytesIO(b"not a real image"), "photo.jpg", "image/jpeg")}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/enhanced-screening")
        page = self.text(self.member.get("/enhanced-screening"))
        self.assertIn("only jpeg, png or pdf", page.lower())

    def test_no_file_chosen_is_a_plain_message_not_a_crash(self):
        token = self.csrf(self.member, "/enhanced-screening")
        response = self.member.post("/enhanced-screening/upload", data={"csrf_token": token}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 302)
        self.assertIn("choose a file", self.text(self.member.get("/enhanced-screening")).lower())

    def test_a_document_that_belongs_to_someone_else_is_answered_like_one_that_does_not_exist(self):
        response = self.upload()
        lab_document_id = response.headers["Location"].rsplit("/", 1)[1]
        stranger = self.signed_in(email="ben@example.com", full_name="Ben Cruz")
        values, inputs, _ = screening_contract.validate_answers(self.catalog, stage1_answers())
        self.add_assessment(email="ben@example.com", inputs=inputs)
        missing = stranger.get("/enhanced-screening/confirm/999999")
        theirs = stranger.get(f"/enhanced-screening/confirm/{lab_document_id}")
        self.assertEqual((missing.status_code, theirs.status_code), (404, 404))


if __name__ == "__main__":
    unittest.main()



class ReportCheckTests(UploadTests):
    """The report checks (services/lab_verification.py) appear beside the values of an uploaded report."""

    def test_the_report_checks_are_shown_with_the_sample_reports_own_name_and_date(self):
        response = self.upload()
        page = self.text(self.member.get(response.headers["Location"]))
        self.assertIn("Report checks", page)
        self.assertIn("2026-09-20", page)                                # the date read from the sample report
        self.assertIn("does not match your name", page)                  # the sample is Jane Doe's, not this member's
        self.assertIn("No signature, licence number", page)              # the sample carries no signature
        self.assertIn("signs, not proof", page)
