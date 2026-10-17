"""
Checks for services/lab_ocr.py: turning a lab document into candidate values. Uses tests/fixtures/sample_lab_report
(a synthetic report with known, exact values baked in) so the expected numbers below are ground truth, not guesses.
Needs a real tesseract binary and pytesseract/pdf2image/Pillow; skipped cleanly where they are not installed.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-only-secret-key")

from services import lab_contract  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
IMAGE = os.path.join(FIXTURES, "sample_lab_report.png")
PDF = os.path.join(FIXTURES, "sample_lab_report.pdf")

try:
    import pytesseract
    pytesseract.get_tesseract_version()
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

NEEDS_OCR = unittest.skipUnless(OCR_AVAILABLE and shutil.which("pdftoppm"), "needs tesseract, pytesseract and poppler (pdftoppm)")

# What tests/fixtures/sample_lab_report actually says, so the extraction can be checked against known-true values.
KNOWN_VALUES = {
    "Systolic_BP": 138, "Diastolic_BP": 88, "Serum_Creatinine": 1.4, "Blood_Urea_Nitrogen": 22, "Urine_ACR": 145,
    "HbA1c": 6.8, "Fasting_Glucose": 118, "Hemoglobin": 12.1, "Sodium": 139, "Potassium": 4.6,
    "Total_Cholesterol": 205, "HDL": 42, "LDL": 128,
}
NOT_ON_THE_REPORT = {"Albumin", "Urine_Protein", "Calcium", "Phosphorus", "Uric_Acid", "Triglycerides", "CRP"}


@NEEDS_OCR
class ExtractTextTests(unittest.TestCase):
    def setUp(self):
        from services import lab_ocr
        self.lab_ocr = lab_ocr

    def test_a_png_is_read(self):
        text = self.lab_ocr.extract_text(IMAGE, "image/png")
        self.assertIn("Creatinine", text)

    def test_a_pdf_is_read_the_same_way(self):
        text = self.lab_ocr.extract_text(PDF, "application/pdf")
        self.assertIn("Creatinine", text)

    def test_an_unsupported_content_type_is_refused(self):
        with self.assertRaises(self.lab_ocr.UnreadableDocument):
            self.lab_ocr.extract_text(IMAGE, "text/plain")

    def test_a_tesseract_cmd_is_passed_through_to_pytesseract_when_given(self):
        import pytesseract
        original = pytesseract.pytesseract.tesseract_cmd
        try:
            self.lab_ocr.extract_text(IMAGE, "image/png", tesseract_cmd="tesseract")   # "tesseract" alone: already on PATH here
            self.assertEqual(pytesseract.pytesseract.tesseract_cmd, "tesseract")
        finally:
            pytesseract.pytesseract.tesseract_cmd = original

    def test_no_tesseract_cmd_leaves_pytesseracts_own_default_alone(self):
        import pytesseract
        from unittest import mock
        original = pytesseract.pytesseract.tesseract_cmd
        try:
            pytesseract.pytesseract.tesseract_cmd = "a-sentinel-value"
            with mock.patch.object(pytesseract, "image_to_string", return_value="text"):
                self.lab_ocr.extract_text(IMAGE, "image/png")               # tesseract_cmd not given: nothing to pass through
            self.assertEqual(pytesseract.pytesseract.tesseract_cmd, "a-sentinel-value")   # untouched
        finally:
            pytesseract.pytesseract.tesseract_cmd = original

    def test_tesseract_itself_failing_to_run_is_never_a_crash_for_an_image(self):
        # Covers every real way tesseract can fail to even start: not installed, not on PATH, TESSERACT_CMD
        # pointing at the wrong thing, no permission to run it, an antivirus block. All of these surface as SOME
        # exception from pytesseract.image_to_string - never caught by Image.open() succeeding first.
        import pytesseract
        from unittest import mock
        with mock.patch.object(pytesseract, "image_to_string", side_effect=PermissionError(5, "Access is denied")):
            with self.assertRaisesRegex(self.lab_ocr.UnreadableDocument, "could not run OCR"):
                self.lab_ocr.extract_text(IMAGE, "image/png")

    def test_tesseract_itself_failing_to_run_is_never_a_crash_for_a_pdf(self):
        import pytesseract
        from unittest import mock
        with mock.patch.object(pytesseract, "image_to_string", side_effect=PermissionError(5, "Access is denied")):
            with self.assertRaisesRegex(self.lab_ocr.UnreadableDocument, "could not read this PDF"):
                self.lab_ocr.extract_text(PDF, "application/pdf")

    def test_a_file_that_is_not_really_an_image_is_refused_not_crashed(self):
        bogus = os.path.join(FIXTURES, "not_really_an_image.png")
        with open(bogus, "wb") as handle:
            handle.write(b"this is not image data")
        self.addCleanup(os.remove, bogus)
        with self.assertRaises(self.lab_ocr.UnreadableDocument):
            self.lab_ocr.extract_text(bogus, "image/png")


@NEEDS_OCR
class ExtractCandidateValuesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from services import lab_ocr
        cls.lab_ocr = lab_ocr
        cls.catalog = lab_contract.load_lab_catalog()
        cls.text = lab_ocr.extract_text(IMAGE, "image/png")
        cls.found = lab_ocr.extract_candidate_values(cls.text, cls.catalog)

    def test_every_value_actually_on_the_report_is_found_and_exactly_right(self):
        for name, expected in KNOWN_VALUES.items():
            self.assertIn(name, self.found, name)
            self.assertAlmostEqual(self.found[name], expected, places=1, msg=name)

    def test_a_field_that_is_not_on_the_report_is_left_out_not_guessed(self):
        for name in NOT_ON_THE_REPORT:
            self.assertNotIn(name, self.found, name)

    def test_egfr_is_never_extracted_it_is_always_computed_from_creatinine(self):
        self.assertNotIn("eGFR", self.found)                     # even though the fixture prints an eGFR line

    def test_only_real_catalog_fields_are_ever_returned(self):
        names = {f["name"] for f in self.catalog["fields"]}
        self.assertTrue(set(self.found) <= names)

    def test_a_value_outside_the_plausible_range_is_dropped_not_offered(self):
        text = "Sodium: 9999 mmol/L\nPotassium: 4.6 mmol/L"
        found = self.lab_ocr.extract_candidate_values(text, self.catalog)
        self.assertNotIn("Sodium", found)
        self.assertIn("Potassium", found)

    def test_text_with_no_lab_values_at_all_finds_nothing(self):
        self.assertEqual(self.lab_ocr.extract_candidate_values("Just a note with no numbers on it.", self.catalog), {})

    def test_a_number_found_is_a_plain_float_ready_for_the_confirmation_form(self):
        for value in self.found.values():
            self.assertIsInstance(value, float)

    def test_albumin_is_not_confused_with_the_urine_albumin_creatinine_ratio(self):
        text = "Urine Albumin-to-Creatinine Ratio: 145 mg/g\nAlbumin: 4.2 g/dL"
        found = self.lab_ocr.extract_candidate_values(text, self.catalog)
        self.assertEqual(found.get("Urine_ACR"), 145.0)
        self.assertEqual(found.get("Albumin"), 4.2)

    def test_hemoglobin_is_not_confused_with_hba1c(self):
        text = "HbA1c: 6.8 %\nHemoglobin: 13.5 g/dL"
        found = self.lab_ocr.extract_candidate_values(text, self.catalog)
        self.assertEqual(found.get("HbA1c"), 6.8)
        self.assertEqual(found.get("Hemoglobin"), 13.5)

    def test_a_scattering_of_unrelated_letters_and_digits_is_not_mistaken_for_a_value(self):
        text = "This has no lab values at all, just some random Hb and 1 and c letters scattered 6.8 around."
        self.assertEqual(self.lab_ocr.extract_candidate_values(text, self.catalog), {})


if __name__ == "__main__":
    unittest.main()
