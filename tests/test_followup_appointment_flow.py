"""
Checks for the follow-up appointment and checklist website paths: scheduling, editing, cancelling, completing,
and deleting an appointment (professional side), and the patient's own calendar/checklist page.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase  # noqa: E402


class AppointmentCrudTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.patient = self.signed_in()
        self.professional = self.signed_in(**self.professional_details())
        self.professional_id = self.store.find_by_email("dr.cruz@example.com")["user_id"]
        self.patient_id = self.store.find_by_email("ana@example.com")["user_id"]
        self.post("/share/request", {"consent": "1", "professional_user_id": str(self.professional_id)}, client=self.patient, token_from="/share")
        self.post(f"/patients/respond/{self.patient_id}", {"action": "accept"}, client=self.professional, token_from="/patients")

    def _schedule(self, **changes):
        form = {"date": "2026-11-10", "time": "14:30", "purpose": "Recheck labs", "notes": "Bring results"}
        form.update(changes)
        return self.post(f"/patients/{self.patient_id}/appointments", form, client=self.professional,
                         token_from=f"/patients/{self.patient_id}")

    def test_scheduling_shows_up_on_the_professionals_own_patient_page(self):
        self._schedule()
        page = self.text(self.professional.get(f"/patients/{self.patient_id}"))
        self.assertIn("Recheck labs", page)
        self.assertIn("Bring results", page)

    def test_scheduling_shows_up_on_the_patients_own_follow_up_page(self):
        self._schedule()
        page = self.text(self.patient.get("/follow-up"))
        self.assertIn("Recheck labs", page)

    def test_a_blank_purpose_is_refused_with_a_flash_not_a_crash(self):
        response = self._schedule(purpose="")
        self.assertEqual(response.status_code, 302)
        page = self.text(self.professional.get(response.headers["Location"]))
        self.assertIn("Enter what the follow-up is for", page)

    def test_a_past_date_is_refused(self):
        response = self._schedule(date="2020-01-01")
        page = self.text(self.professional.get(response.headers["Location"]))
        self.assertIn("future", page)

    def test_an_unauthorized_professional_cannot_schedule_for_a_patient(self):
        other = self.signed_in(**self.professional_details(email="dr.other@example.com", full_name="Dr. Other"))
        response = self.post(f"/patients/{self.patient_id}/appointments", {"date": "2026-11-10", "time": "10:00", "purpose": "x"},
                             client=other, token_from="/patients")
        self.assertEqual(response.status_code, 404)

    def test_editing_changes_the_purpose_and_time(self):
        self._schedule()
        page = self.text(self.professional.get(f"/patients/{self.patient_id}"))
        import re
        appointment_id = re.search(r"/appointments/(\d+)/edit", page).group(1)
        self.post(f"/patients/{self.patient_id}/appointments/{appointment_id}/edit",
                 {"date": "2026-11-15", "time": "09:00", "purpose": "Changed purpose", "notes": ""},
                 client=self.professional, token_from=f"/patients/{self.patient_id}")
        page = self.text(self.professional.get(f"/patients/{self.patient_id}"))
        self.assertIn("Changed purpose", page)
        self.assertNotIn("Recheck labs", page)

    def test_completing_changes_its_status(self):
        self._schedule()
        page = self.text(self.professional.get(f"/patients/{self.patient_id}"))
        import re
        appointment_id = re.search(r"/appointments/(\d+)/complete", page).group(1)
        self.post(f"/patients/{self.patient_id}/appointments/{appointment_id}/complete", {},
                 client=self.professional, token_from=f"/patients/{self.patient_id}")
        page = self.text(self.professional.get(f"/patients/{self.patient_id}"))
        self.assertIn("Completed", page)

    def test_cancelling_changes_its_status(self):
        self._schedule()
        page = self.text(self.professional.get(f"/patients/{self.patient_id}"))
        import re
        appointment_id = re.search(r"/appointments/(\d+)/cancel", page).group(1)
        self.post(f"/patients/{self.patient_id}/appointments/{appointment_id}/cancel", {},
                 client=self.professional, token_from=f"/patients/{self.patient_id}")
        page = self.text(self.professional.get(f"/patients/{self.patient_id}"))
        self.assertIn("Cancelled", page)

    def test_deleting_removes_it_entirely(self):
        self._schedule()
        page = self.text(self.professional.get(f"/patients/{self.patient_id}"))
        import re
        appointment_id = re.search(r"/appointments/(\d+)/delete", page).group(1)
        self.post(f"/patients/{self.patient_id}/appointments/{appointment_id}/delete", {},
                 client=self.professional, token_from=f"/patients/{self.patient_id}")
        page = self.text(self.professional.get(f"/patients/{self.patient_id}"))
        self.assertNotIn("Recheck labs", page)
        self.assertIn("No appointments scheduled yet", page)

    def test_a_different_professional_cannot_edit_or_delete_it(self):
        self._schedule()
        page = self.text(self.professional.get(f"/patients/{self.patient_id}"))
        import re
        appointment_id = re.search(r"/appointments/(\d+)/edit", page).group(1)
        other = self.signed_in(**self.professional_details(email="dr.other2@example.com", full_name="Dr. Other"))
        response = self.post(f"/patients/{self.patient_id}/appointments/{appointment_id}/delete", {},
                             client=other, token_from="/patients")
        self.assertEqual(response.status_code, 404)


class PatientFollowUpPageTests(AppTestCase):
    model = "explainable"

    def setUp(self):
        super().setUp()
        self.patient = self.signed_in()

    def test_the_calendar_shows_an_empty_state_with_no_appointments(self):
        page = self.text(self.patient.get("/follow-up"))
        self.assertIn("No follow-up appointments are currently scheduled", page)

    def test_the_checklist_shows_a_message_with_no_assessment_yet(self):
        page = self.text(self.patient.get("/follow-up"))
        self.assertIn("Complete a screening to get your own personalized checklist", page)

    def test_the_checklist_appears_once_an_assessment_exists(self):
        self.add_assessment(inputs={"Diabetes": 1})
        page = self.text(self.patient.get("/follow-up"))
        self.assertIn("Your kidney-health checklist", page)
        self.assertIn("Never stop, start, or change", page)

    def test_toggling_a_checklist_item_persists(self):
        self.add_assessment(inputs={"Diabetes": 1})
        page = self.text(self.patient.get("/follow-up"))
        import re
        tip_id = re.search(r"/follow-up/checklist/([\w-]+)", page).group(1)
        self.post(f"/follow-up/checklist/{tip_id}", {"is_complete": "1"}, client=self.patient, token_from="/follow-up")
        page_again = self.text(self.patient.get("/follow-up"))
        self.assertIn("checklist-item is-done", page_again)

    def test_the_month_navigation_moves_forward_and_back(self):
        page = self.text(self.patient.get("/follow-up?year=2026&month=12"))
        self.assertIn("December 2026", page)
        page = self.text(self.patient.get("/follow-up?year=2027&month=1"))
        self.assertIn("January 2027", page)

    def test_a_nonsense_month_falls_back_to_today_instead_of_crashing(self):
        response = self.patient.get("/follow-up?year=2026&month=99")
        self.assertEqual(response.status_code, 200)

    def test_signed_out_is_sent_to_sign_in(self):
        response = self.client.get("/follow-up")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])


if __name__ == "__main__":
    unittest.main()
