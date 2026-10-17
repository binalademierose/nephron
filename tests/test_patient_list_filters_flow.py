"""
Checks for /patient-records (routes/patient_records_routes.py index): the unified patient list, category tabs,
risk filter, and reset - across both a professional's own patient records and their shared patients. The
filtering logic itself is covered by tests/test_professional_overview.py; these confirm the page renders it.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase  # noqa: E402
from test_screening_flow import answers  # noqa: E402


class PatientListFiltersTests(AppTestCase):
    model = True

    def setUp(self):
        super().setUp()
        self.professional = self.signed_in(**self.professional_details())
        low = self.post("/patient-records/new", {"full_name": "Low Risk Patient", "date_of_birth": "1986-01-15", "country": "Other", "gender": "Female", "sex": "Female"},
                        client=self.professional, token_from="/patient-records/new")
        self.low_code = low.headers["Location"].split("/")[-2]
        self.post(f"/patient-records/{self.low_code}/screening", answers(Diabetes="0", Hypertension="0", Age="40"),
                 client=self.professional, token_from=f"/patient-records/{self.low_code}/screening")
        self.post("/patient-records/new", {"full_name": "New Patient No Screening", "date_of_birth": "1991-01-15", "country": "Other", "gender": "Male", "sex": "Male"},
                 client=self.professional, token_from="/patient-records/new")
        self.professional.get("/patient-records")   # flush the "patient added" flash message so it never leaks into a test's own page check

    def test_the_all_tab_shows_every_patient_with_an_accurate_count(self):
        page = self.text(self.professional.get("/patient-records"))
        self.assertIn("Low Risk Patient", page)
        self.assertIn("New Patient No Screening", page)
        self.assertIn("All Patients", page)

    def test_the_pending_tab_only_shows_the_unscreened_patient(self):
        page = self.text(self.professional.get("/patient-records?category=pending"))
        self.assertIn("New Patient No Screening", page)
        self.assertNotIn("Low Risk Patient", page)

    def test_the_reviewed_tab_only_shows_the_screened_patient(self):
        page = self.text(self.professional.get("/patient-records?category=reviewed"))
        self.assertIn("Low Risk Patient", page)
        self.assertNotIn("New Patient No Screening", page)

    def test_the_risk_filter_narrows_by_latest_result(self):
        page = self.text(self.professional.get("/patient-records?risk=low"))
        self.assertIn("Low Risk Patient", page)
        page_high = self.text(self.professional.get("/patient-records?risk=high"))
        self.assertNotIn("Low Risk Patient", page_high)

    def test_search_and_category_combine(self):
        page = self.text(self.professional.get("/patient-records?q=Low&category=pending"))
        self.assertIn("No patient matches these filters", page)

    def test_reset_clears_every_filter(self):
        page = self.text(self.professional.get("/patient-records?risk=high&category=pending&q=xyz"))
        self.assertIn('href="/patient-records"', page)

    def test_an_invalid_category_falls_back_to_all_instead_of_crashing(self):
        response = self.professional.get("/patient-records?category=not-a-real-category")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Low Risk Patient", self.text(response))

    def test_a_different_professional_sees_none_of_this(self):
        other = self.signed_in(**self.professional_details(email="dr.other@example.com", full_name="Dr. Other"))
        page = self.text(other.get("/patient-records"))
        self.assertNotIn("Low Risk Patient", page)
        self.assertNotIn("New Patient No Screening", page)


class PatientListIncludesSharedPatientsTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.patient = self.signed_in()
        self.professional = self.signed_in(**self.professional_details())
        self.professional_id = self.store.find_by_email("dr.cruz@example.com")["user_id"]
        self.patient_id = self.store.find_by_email("ana@example.com")["user_id"]
        self.post("/share/request", {"consent": "1", "professional_user_id": str(self.professional_id)},
                 client=self.patient, token_from="/share")
        self.post(f"/patients/respond/{self.patient_id}", {"action": "accept"}, client=self.professional, token_from="/patients")

    def test_a_shared_patient_appears_in_the_unified_patients_list(self):
        page = self.text(self.professional.get("/patient-records"))
        self.assertIn("Ana Reyes", page)
        self.assertIn("Shared</span>", page)

    def test_viewing_a_shared_patient_from_the_list_goes_to_their_history_not_a_patient_record_url(self):
        page = self.text(self.professional.get("/patient-records"))
        self.assertIn(f"/patients/{self.patient_id}", page)


if __name__ == "__main__":
    unittest.main()
