"""
Checks for the Professional Dashboard (routes/account_routes.py professional_home). The aggregation logic itself
is covered by tests/test_professional_overview.py; these confirm the page actually renders it and behaves
correctly end to end. Run everything with:   python -m unittest discover -s tests -v
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase  # noqa: E402
from test_screening_flow import answers  # noqa: E402


class EmptyDashboardTests(AppTestCase):
    def test_a_professional_with_no_patients_sees_an_honest_empty_state(self):
        professional = self.signed_in(**self.professional_details())
        page = self.text(professional.get("/professional"))
        self.assertIn("No patients yet", page)
        self.assertNotIn("Total Patient Records", page)          # the stat row does not render at all when empty

    def test_a_general_user_cannot_reach_it(self):
        general = self.signed_in()
        self.assertEqual(general.get("/professional").status_code, 403)


class PopulatedDashboardTests(AppTestCase):
    model = True

    def setUp(self):
        super().setUp()
        self.professional = self.signed_in(**self.professional_details())
        response = self.post("/patient-records/new", {"full_name": "Juan Dela Cruz", "date_of_birth": "1968-01-15", "country": "Other", "gender": "Male", "sex": "Male"},
                             client=self.professional, token_from="/patient-records/new")
        self.code = response.headers["Location"].split("/")[-2]
        self.post(f"/patient-records/{self.code}/screening", answers(), client=self.professional, token_from=f"/patient-records/{self.code}/screening")

    def test_the_stat_row_reflects_the_one_patient_and_their_result(self):
        page = self.text(self.professional.get("/professional"))
        self.assertIn("Total Patient Records", page)
        self.assertRegex(page, r'Total Patient Records</p>\s*<p class="stat-value">1</p>')
        self.assertIn("Juan Dela Cruz", page)
        self.assertIn("NPH-", page)

    def test_a_patient_records_own_assessment_shows_as_self_recorded(self):
        page = self.text(self.professional.get("/professional"))
        self.assertIn("Self-recorded", page)
        self.assertNotIn("Awaiting review", page)

    def test_the_risk_donut_renders_once_there_is_at_least_one_result(self):
        page = self.text(self.professional.get("/professional"))
        self.assertIn("Patient risk distribution", page)

    def test_a_different_professional_sees_their_own_empty_dashboard_not_this_one(self):
        other = self.signed_in(**self.professional_details(email="dr.other@example.com", full_name="Dr. Other"))
        page = self.text(other.get("/professional"))
        self.assertIn("No patients yet", page)
        self.assertNotIn("Juan Dela Cruz", page)


class SharedPatientReviewStatusTests(AppTestCase):
    model = True

    def setUp(self):
        super().setUp()
        self.patient = self.signed_in()
        self.professional = self.signed_in(**self.professional_details())
        self.professional_id = self.store.find_by_email("dr.cruz@example.com")["user_id"]
        self.patient_id = self.store.find_by_email("ana@example.com")["user_id"]
        self.post("/share/request", {"consent": "1", "professional_user_id": str(self.professional_id)},
                 client=self.patient, token_from="/share")
        self.post(f"/patients/respond/{self.patient_id}", {"action": "accept", "consent": "1"},
                 client=self.professional, token_from="/patients")
        self.post("/screening", answers(), client=self.patient, token_from="/screening")

    def test_a_shared_patients_assessment_shows_as_awaiting_review_and_counts_as_pending(self):
        page = self.text(self.professional.get("/professional"))
        self.assertIn("Awaiting review", page)
        self.assertRegex(page, r'Pending Reviews</p>\s*<p class="stat-value">1</p>')

    def test_adding_a_clinical_review_updates_the_dashboard(self):
        assessment_id = self.app.extensions["assessment_store"].list_assessments(self.patient_id)[0]["assessment_id"]
        self.post(f"/patients/{self.patient_id}/review", {"assessment_id": str(assessment_id), "note": "Looks stable."},
                 client=self.professional, token_from=f"/patients/{self.patient_id}")
        page = self.text(self.professional.get("/professional"))
        self.assertIn("Reviewed", page)
        self.assertRegex(page, r'Pending Reviews</p>\s*<p class="stat-value">0</p>')

    def test_a_shared_patients_result_appears_in_recent_activity(self):
        # the dashboard's compact Recent Activity table shows Patient/Date/Risk/Status only (no ID column,
        # matching the same table style the patient dashboard itself never had either) - a shared patient's own
        # row is confirmed by their name and "Awaiting review" showing up together.
        page = self.text(self.professional.get("/professional"))
        self.assertIn("Ana Reyes", page)
        self.assertIn("Awaiting review", page)


if __name__ == "__main__":
    unittest.main()


class PatientInsightsOnDashboardTests(AppTestCase):
    model = True

    def setUp(self):
        super().setUp()
        self.professional = self.signed_in(**self.professional_details())

    def _add(self, name, age, sex, high_risk):
        response = self.post("/patient-records/new", {"full_name": name, "date_of_birth": f"{2026 - age}-01-15", "country": "Other", "gender": sex, "sex": sex},
                             client=self.professional, token_from="/patient-records/new")
        code = response.headers["Location"].split("/")[-2]
        form = answers(Age=str(age), Gender=sex, Sex=sex, Diabetes="1" if high_risk else "0", Hypertension="1" if high_risk else "0")
        self.post(f"/patient-records/{code}/screening", form, client=self.professional, token_from=f"/patient-records/{code}/screening")

    def test_fewer_than_three_results_shows_no_insights_section(self):
        self._add("Patient A", 40, "Female", False)
        self._add("Patient B", 50, "Male", True)
        page = self.text(self.professional.get("/professional"))
        self.assertNotIn("Your patients, at a glance", page)

    def test_three_or_more_results_shows_the_insights_section(self):
        self._add("Patient A", 30, "Female", False)
        self._add("Patient B", 50, "Male", True)
        self._add("Patient C", 70, "Male", True)
        page = self.text(self.professional.get("/professional"))
        self.assertIn("Your patients, at a glance", page)
        self.assertIn("not a general population statistic", page)
        self.assertIn("18-44", page)
        self.assertIn("65+", page)
        # the gender count plot: 1 woman (none at higher risk), 2 men (both at higher risk)
        self.assertIn("Your patients, by gender", page)
        self.assertIn('aria-label="Female: 1 patient, 0 at higher risk"', page)
        self.assertIn('aria-label="Male: 2 patients, 2 at higher risk"', page)
        self.assertIn("2 (100%)", page)

    def test_a_different_professional_with_no_patients_sees_no_insights_section(self):
        self._add("Patient A", 30, "Female", False)
        self._add("Patient B", 50, "Male", True)
        self._add("Patient C", 70, "Male", True)
        other = self.signed_in(**self.professional_details(email="dr.other@example.com", full_name="Dr. Other"))
        page = self.text(other.get("/professional"))
        self.assertNotIn("Your patients, at a glance", page)
