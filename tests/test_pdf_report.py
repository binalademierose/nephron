"""
Checks for services/pdf_report.py. Structural checks (valid PDF bytes) always run; checks that read the actual
text back out of the PDF need pypdf, a test-only convenience - not required to generate reports, only to verify
their content here - and are skipped, with the reason, when it is not installed (pip install pypdf).
Run everything with:   python -m unittest discover -s tests -v
"""
import io
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import pdf_report  # noqa: E402

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

NEEDS_PYPDF = unittest.skipUnless(PYPDF_AVAILABLE, "needs pypdf to read the generated PDF back (pip install pypdf)")

DISCLAIMER = "Nephron provides risk screening and decision-support information."


def _text_of(pdf_bytes):
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


def single_data(**changes):
    data = {
        "patient_name": "Ana Reyes", "patient_email": "ana@example.com", "generated_at_text": "Sep 26, 2026",
        "record": {"date_text": "Sep 26, 2026", "type": "Preliminary screening", "probability_text": "70.8%",
                  "classification": "high", "classification_text": "High Preliminary Risk",
                  "threshold_text": "Validated threshold: 61%",
                  "what_this_means": "Higher-risk group. This is screening information, not a diagnosis."},
        "answers": [("Health history", [("Diabetes", "Yes"), ("High blood pressure", "Yes")])],
        "factors_up": ["Diabetes: Yes"], "factors_down": ["Obesity (from BMI): No"],
        "reviews": [],
        "disclaimer": DISCLAIMER,
    }
    data.update(changes)
    return data


def history_data(**changes):
    data = {
        "patient_name": "Ana Reyes", "patient_email": "ana@example.com", "generated_at_text": "Sep 26, 2026",
        "rows": [
            {"assessment_id": 1, "date_text": "Jul 1, 2026", "type": "Preliminary screening", "probability_text": "59.3%",
             "classification": "high", "classification_text": "High Preliminary Risk"},
            {"assessment_id": 2, "date_text": "Sep 26, 2026", "type": "Preliminary screening", "probability_text": "70.8%",
             "classification": "high", "classification_text": "High Preliminary Risk"},
        ],
        "reviews_by_assessment": {},
        "disclaimer": DISCLAIMER,
    }
    data.update(changes)
    return data


class AssessmentReportTests(unittest.TestCase):
    def test_it_produces_real_pdf_bytes(self):
        pdf_bytes = pdf_report.build_assessment_report(single_data())
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 500)

    def test_it_works_with_no_factors_and_no_reviews(self):
        # a saved result the current model can no longer explain, and no clinical note yet - still a valid PDF
        pdf_bytes = pdf_report.build_assessment_report(single_data(factors_up=[], factors_down=[], reviews=[]))
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    @NEEDS_PYPDF
    def test_the_patients_own_name_and_result_appear(self):
        text = _text_of(pdf_report.build_assessment_report(single_data()))
        self.assertIn("Ana Reyes", text)
        self.assertIn("70.8%", text)
        self.assertIn("High Preliminary Risk", text)
        self.assertIn("Diabetes", text)

    @NEEDS_PYPDF
    def test_a_review_is_included_when_given(self):
        data = single_data(reviews=[{"professional_name": "Dr. Maria Cruz", "profession_title": "Nephrologist",
                                    "date": date(2026, 9, 26), "note": "Recheck in three months."}])
        text = _text_of(pdf_report.build_assessment_report(data))
        self.assertIn("Dr. Maria Cruz", text)
        self.assertIn("Recheck in three months.", text)

    @NEEDS_PYPDF
    def test_no_reviews_given_means_none_appear(self):
        text = _text_of(pdf_report.build_assessment_report(single_data(reviews=[])))
        self.assertNotIn("Notes from your professional", text)

    @NEEDS_PYPDF
    def test_the_medical_disclaimer_is_always_present(self):
        text = _text_of(pdf_report.build_assessment_report(single_data()))
        self.assertIn("Nephron provides risk screening", text)

    def test_a_review_note_containing_xml_special_characters_does_not_break_the_pdf(self):
        # a clinical review note is free text a professional typed - the one place in a report that is not a
        # controlled vocabulary - so it can contain '<', '>' or '&' without breaking Paragraph's own XML-like markup
        data = single_data(reviews=[{"professional_name": "Dr. A & B", "profession_title": "Nephrologist",
                                    "date": date(2026, 9, 26), "note": "BP < 120 & pulse > 60, target achieved."}])
        pdf_bytes = pdf_report.build_assessment_report(data)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    @NEEDS_PYPDF
    def test_a_review_note_with_special_characters_reads_back_correctly(self):
        data = single_data(reviews=[{"professional_name": "Dr. A & B", "profession_title": "Nephrologist",
                                    "date": date(2026, 9, 26), "note": "BP < 120 & pulse > 60, target achieved."}])
        text = _text_of(pdf_report.build_assessment_report(data))
        self.assertIn("Dr. A & B", text)
        self.assertIn("BP < 120 & pulse > 60, target achieved.", text)

    @NEEDS_PYPDF
    def test_a_superscript_two_unit_reads_back_as_a_plain_2(self):
        # the PDF has no glyph for U+00B2 at all (see pdf_report._escape) - it is rendered as a real <super> 2
        # instead, which pypdf's own text extraction reads back as a plain "2"
        data = single_data(answers=[("Kidney function", [("eGFR", "42.8 mL/min/1.73m\u00b2")])])
        text = _text_of(pdf_report.build_assessment_report(data))
        self.assertIn("1.73m2", text.replace("\n", ""))


class HistoryReportTests(unittest.TestCase):
    def test_it_produces_real_pdf_bytes(self):
        pdf_bytes = pdf_report.build_history_report(history_data())
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_it_works_with_a_single_assessment_and_no_reviews(self):
        data = history_data(rows=history_data()["rows"][:1])
        pdf_bytes = pdf_report.build_history_report(data)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    @NEEDS_PYPDF
    def test_every_row_appears(self):
        text = _text_of(pdf_report.build_history_report(history_data()))
        self.assertIn("Jul 1, 2026", text)
        self.assertIn("Sep 26, 2026", text)
        self.assertIn("59.3%", text)
        self.assertIn("70.8%", text)

    @NEEDS_PYPDF
    def test_reviews_are_grouped_under_the_assessment_they_belong_to(self):
        data = history_data(reviews_by_assessment={2: [{"professional_name": "Dr. Maria Cruz", "profession_title": "Nephrologist",
                                                        "date": date(2026, 9, 26), "note": "Latest result looks stable."}]})
        text = _text_of(pdf_report.build_history_report(data))
        self.assertIn("Latest result looks stable.", text)

    @NEEDS_PYPDF
    def test_no_reviews_at_all_means_the_section_is_left_out(self):
        text = _text_of(pdf_report.build_history_report(history_data(reviews_by_assessment={})))
        self.assertNotIn("Notes from your professional", text)


if __name__ == "__main__":
    unittest.main()
