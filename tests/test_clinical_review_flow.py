"""
Checks for clinical reviews (a professional's note on one assessment) and follow-up requests (asking a patient to
screen again, bypassing the normal waiting period). Uses in-memory stores; no database and no ML model needed
except where a real screening is submitted. Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import AppTestCase  # noqa: E402


class ReviewAndFollowUpTestCase(AppTestCase):
    def setUp(self):
        super().setUp()
        self.patient = self.signed_in()
        self.professional = self.signed_in(**self.professional_details())
        self.professional_id = self.store.find_by_email("dr.cruz@example.com")["user_id"]
        self.patient_id = self.store.find_by_email("ana@example.com")["user_id"]
        self.assessment_id = self.add_assessment()
        # request and accept, so the professional is authorized before each test runs
        self.post("/share/request", {"consent": "1", "professional_user_id": str(self.professional_id)}, client=self.patient, token_from="/share")
        self.post(f"/patients/respond/{self.patient_id}", {"action": "accept"}, client=self.professional, token_from="/patients")


class ClinicalReviewTests(ReviewAndFollowUpTestCase):
    def add_note(self, note="Looks reasonable, recheck in 3 months."):
        return self.post(f"/patients/{self.patient_id}/review", {"assessment_id": str(self.assessment_id), "note": note},
                         client=self.professional, token_from=f"/patients/{self.patient_id}")

    def test_an_authorized_professional_can_add_a_note(self):
        response = self.add_note()
        self.assertEqual(response.status_code, 302)
        page = self.text(self.professional.get(f"/patients/{self.patient_id}"))
        self.assertIn("Looks reasonable, recheck in 3 months.", page)
        self.assertIn("Dr. Luis Cruz", page)

    def test_the_patient_sees_the_note_on_their_own_result_page(self):
        self.add_note("Your creatinine looks stable.")
        page = self.text(self.patient.get(f"/results/{self.assessment_id}"))
        self.assertIn("Your creatinine looks stable.", page)
        self.assertIn("Notes from your professional", page)

    def test_a_result_page_with_no_reviews_does_not_show_the_section(self):
        page = self.text(self.patient.get(f"/results/{self.assessment_id}"))
        self.assertNotIn("Notes from your professional", page)

    def test_several_notes_are_kept_oldest_first(self):
        self.add_note("First note.")
        self.add_note("Second note.")
        page = self.text(self.patient.get(f"/results/{self.assessment_id}"))
        self.assertLess(page.index("First note."), page.index("Second note."))

    def test_a_blank_note_is_refused(self):
        response = self.add_note("   ")
        page = self.text(self.professional.get(response.headers["Location"]))
        self.assertIn("cannot be empty", page)

    def test_a_professional_who_is_not_authorized_cannot_add_a_note(self):
        other_professional = self.signed_in(**self.professional_details(email="dr.other@example.com", full_name="Dr. Ana Other"))
        response = self.post(f"/patients/{self.patient_id}/review", {"assessment_id": str(self.assessment_id), "note": "Sneaky note"},
                             client=other_professional, token_from=f"/patients")
        self.assertEqual(response.status_code, 404)

    def test_revoking_access_still_leaves_the_note_on_the_patients_record(self):
        self.add_note("Please monitor closely.")
        self.post(f"/share/revoke/{self.professional_id}", {}, client=self.patient, token_from="/share")
        page = self.text(self.patient.get(f"/results/{self.assessment_id}"))
        self.assertIn("Please monitor closely.", page)

    def test_a_note_cannot_be_added_after_access_is_revoked(self):
        self.post(f"/share/revoke/{self.professional_id}", {}, client=self.patient, token_from="/share")
        response = self.add_note()
        self.assertEqual(response.status_code, 404)


class FollowUpTests(ReviewAndFollowUpTestCase):
    def request_followup(self, message="Please redo after your medication change."):
        return self.post(f"/patients/{self.patient_id}/follow-up", {"message": message}, client=self.professional, token_from=f"/patients/{self.patient_id}")

    def test_an_authorized_professional_can_request_a_follow_up(self):
        response = self.request_followup()
        self.assertEqual(response.status_code, 302)
        page = self.text(self.professional.get(f"/patients/{self.patient_id}"))
        self.assertIn("A follow-up screening was requested", page)

    def test_the_patient_sees_the_request_on_their_dashboard(self):
        self.request_followup("Please redo after your medication change.")
        page = self.text(self.patient.get("/dashboard"))
        self.assertIn("requested a follow-up screening", page)
        self.assertIn("Please redo after your medication change.", page)

    def test_with_no_open_request_the_dashboard_shows_no_banner(self):
        page = self.text(self.patient.get("/dashboard"))
        self.assertNotIn("requested a follow-up screening", page)

    def test_a_message_is_optional(self):
        response = self.request_followup(message="")
        self.assertEqual(response.status_code, 302)

    def test_a_professional_who_is_not_authorized_cannot_request_a_follow_up(self):
        other_professional = self.signed_in(**self.professional_details(email="dr.other@example.com", full_name="Dr. Ana Other"))
        response = self.post(f"/patients/{self.patient_id}/follow-up", {"message": "sneaky"}, client=other_professional, token_from="/patients")
        self.assertEqual(response.status_code, 404)


class FollowUpEligibilityTests(ReviewAndFollowUpTestCase):
    model = "explainable"

    def test_an_open_follow_up_lets_the_patient_screen_again_during_the_normal_waiting_period(self):
        self.app.config["REASSESSMENT_DAYS"] = 30
        page = self.text(self.patient.get("/screening"))
        self.assertIn("not open yet", page)                          # normally blocked
        self.post(f"/patients/{self.patient_id}/follow-up", {"message": ""}, client=self.professional, token_from=f"/patients/{self.patient_id}")
        page = self.text(self.patient.get("/screening"))
        self.assertNotIn("not open yet", page)

    def test_completing_a_new_screening_closes_the_open_follow_up_request(self):
        self.app.config["REASSESSMENT_DAYS"] = None
        self.post(f"/patients/{self.patient_id}/follow-up", {"message": ""}, client=self.professional, token_from=f"/patients/{self.patient_id}")
        self.assertIn("requested a follow-up screening", self.text(self.patient.get("/dashboard")))
        from services import screening_contract
        catalog = screening_contract.load_catalog()
        form = {name: (opt["options"][0]["value"] if opt["kind"] == "choice" else "0" if opt["kind"] == "yesno" else str(opt.get("min", 1)))
               for name, opt in ((q["name"], q) for q in catalog["questions"] if q["kind"] != "derived")}
        form.update({"height_cm": "165", "weight_kg": "60", "Gender": "Female"})
        token = self.csrf(self.patient, "/screening")
        self.patient.post("/screening", data={**form, "csrf_token": token})
        page = self.text(self.patient.get("/dashboard"))
        # The bell's own notification is a permanent record of the request and rightly still mentions it -
        # what must actually disappear once fulfilled is the dashboard's own "still open" banner.
        self.assertNotIn('<div class="notice reveal"', page)


if __name__ == "__main__":
    unittest.main()
