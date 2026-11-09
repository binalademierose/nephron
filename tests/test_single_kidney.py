"""
test_single_kidney.py - the "only one kidney" question.

It is asked in the Preliminary screening, saved with the answers, carried into the Enhanced Screening, and never
given to either model. A Yes adds a fixed notice: a higher chance of CKD and an annual eGFR, urine ACR and blood
pressure check.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import model_fixtures  # noqa: E402
from helpers import AppTestCase, ready_model_service  # noqa: E402
from test_screening_flow import answers  # noqa: E402
from services import lab_contract, screening_contract  # noqa: E402

RECOMMENDATION = "Annual eGFR, urine ACR and blood pressure check advised."
RISK = "Having only one kidney increases the chance of developing chronic kidney disease over time."


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.catalog = screening_contract.load_catalog()

    def test_it_is_not_a_model_input(self):
        self.assertNotIn("Single_Kidney", screening_contract.feature_names(self.catalog))
        values, inputs, errors = screening_contract.validate_answers(self.catalog, answers(Single_Kidney="1"))
        self.assertEqual(errors, {})
        self.assertNotIn("Single_Kidney", values)
        self.assertEqual(inputs["Single_Kidney"], 1)

    def test_it_must_be_answered_yes_or_no(self):
        for bad in ("", "2", "maybe"):
            errors = screening_contract.validate_answers(self.catalog, answers(Single_Kidney=bad))[2]
            self.assertEqual(errors.get("Single_Kidney"), "Choose Yes or No.")
        form = answers()
        del form["Single_Kidney"]
        self.assertIn("Single_Kidney", screening_contract.validate_answers(self.catalog, form)[2])
        self.assertIn("history", screening_contract.steps_with_errors(self.catalog, {"Single_Kidney": "Choose Yes or No."}))

    def test_the_answer_is_listed_under_health_history(self):
        inputs = screening_contract.validate_answers(self.catalog, answers(Single_Kidney="1"))[1]
        groups = dict(screening_contract.describe_inputs(self.catalog, inputs))
        self.assertIn(("Only one kidney", "Yes"), groups["Health history"])

    def test_older_results_without_the_answer_show_no_notice(self):
        self.assertFalse(screening_contract.has_single_kidney({"Age": 50}))
        self.assertFalse(screening_contract.has_single_kidney(None))
        self.assertFalse(screening_contract.has_single_kidney({"Single_Kidney": 0}))
        self.assertTrue(screening_contract.has_single_kidney({"Single_Kidney": 1}))


class FlowTests(AppTestCase):
    model = True

    def setUp(self):
        super().setUp()
        self.member = self.signed_in()
        self.user_id = self.store.find_by_email("ana@example.com")["user_id"]
        self.assessments = self.app.extensions["assessment_store"]

    def submit(self, **changes):
        return self.post("/screening", answers(**changes), client=self.member, token_from="/screening")

    def test_the_form_asks_it_in_health_history_with_the_risk_sign(self):
        page = self.text(self.member.get("/screening"))
        self.assertIn("Do you have only one kidney (born with one, removed, or donated)?", page)
        self.assertIn("Living with one kidney can increase the chance of developing CKD.", page)
        history = page[page.index('data-step-key="history"'):page.index('data-step-key="medicines"')]
        self.assertIn('name="Single_Kidney"', history)

    def test_a_yes_shows_the_notice_and_recommendation_and_does_not_change_the_estimate(self):
        expected = ready_model_service().predict(screening_contract.validate_answers(screening_contract.load_catalog(), answers())[0])
        response = self.submit(Single_Kidney="1")
        page = self.text(self.member.get(response.headers["Location"]))
        self.assertIn(RISK, page)
        self.assertIn(RECOMMENDATION, page)
        self.assertIn("single-kidney-notice", page)
        row = self.assessments.list_assessments(self.user_id)[0]
        self.assertAlmostEqual(row["probability"], expected["probability"], places=6)

    def test_a_no_shows_no_notice(self):
        response = self.submit(Single_Kidney="0")
        page = self.text(self.member.get(response.headers["Location"]))
        self.assertNotIn(RECOMMENDATION, page)
        self.assertNotIn("single-kidney-notice", page)

    def test_the_pdf_report_carries_the_recommendation(self):
        from routes import report_routes
        self.submit(Single_Kidney="1")
        assessment_id = self.assessments.list_assessments(self.user_id)[0]["assessment_id"]
        built = {}
        original = report_routes.build_assessment_report

        def capture(data):
            built.update(data)
            return original(data)

        with mock.patch.object(report_routes, "build_assessment_report", capture):
            response = self.post("/reports/download", {"report_type": "single", "assessment_id": str(assessment_id)},
                                 client=self.member, token_from="/reports")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b"%PDF"))
        self.assertEqual(built["single_kidney"]["recommendation"], RECOMMENDATION)


@unittest.skipUnless(model_fixtures.libraries_available(), "needs scikit-learn, pandas, numpy and joblib")
class EnhancedTests(AppTestCase):
    stage2_model = "explainable"

    def test_the_answer_is_carried_into_the_enhanced_screening_and_its_result(self):
        member = self.signed_in()
        inputs = screening_contract.validate_answers(screening_contract.load_catalog(), answers(Single_Kidney="1"))[1]
        self.add_assessment(inputs=inputs)
        response = self.post("/enhanced-screening/confirm", {"Serum_Creatinine": "1.1"}, client=member, token_from="/enhanced-screening/manual")
        self.assertEqual(response.status_code, 302)
        page = self.text(member.get(response.headers["Location"]))
        self.assertIn(RECOMMENDATION, page)
        user_id = self.store.find_by_email("ana@example.com")["user_id"]
        store = self.app.extensions["assessment_store"]
        newest = store.get_assessment(user_id, store.list_assessments(user_id)[0]["assessment_id"])
        self.assertEqual((newest["assessment_type"], newest["inputs"]["Single_Kidney"]), ("enhanced", 1))
        self.assertNotIn("Single_Kidney", lab_contract.field_names(lab_contract.load_lab_catalog()))


if __name__ == "__main__":
    unittest.main()
