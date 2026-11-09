"""
test_review_and_labels.py - the October 27 revision:
  * a professional reviews a shared result in ONE form: a clinical note only, or a clinical note + a follow-up
    appointment (optionally letting the patient screen again now) - all checked before anything is saved;
  * a shared result offers both, already pointed at that result;
  * a note can only ever be attached to the shared patient's own result;
  * required fields carry an asterisk with words for screen readers; no Required/Optional chips are shown.
"""
import datetime
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase  # noqa: E402
from test_screening_flow import answers  # noqa: E402


class SharedPatientCase(AppTestCase):
    model = "explainable"

    def setUp(self):
        super().setUp()
        self.patient = self.signed_in()
        self.post("/screening", answers(), client=self.patient, token_from="/screening")
        self.professional = self.signed_in(**self.professional_details())
        self.patient_id = self.store.find_by_email("ana@example.com")["user_id"]
        self.professional_id = self.store.find_by_email("dr.cruz@example.com")["user_id"]
        self.post("/share/request", {"consent": "1", "professional_user_id": str(self.professional_id)}, client=self.patient, token_from="/share")
        self.post(f"/patients/respond/{self.patient_id}", {"action": "accept"}, client=self.professional, token_from="/patients")
        self.assessment_id = self.app.extensions["assessment_store"].list_assessments(self.patient_id)[0]["assessment_id"]
        self.history = f"/patients/{self.patient_id}"

    def review(self, **form):
        data = {"assessment_id": str(self.assessment_id), "mode": "note", "note": "Kidney function needs a recheck."}
        data.update(form)
        return self.post(f"{self.history}/review", data, client=self.professional, token_from=self.history)

    def notes(self):
        return self.app.extensions["clinical_review_store"].list_for_assessment(self.assessment_id)

    def appointments(self):
        return self.app.extensions["followup_appointment_store"].list_for_patient(self.patient_id)

    def rescreen_requests(self):
        return self.app.extensions["followup_store"].list_for_patient(self.patient_id)


def next_week():
    return (datetime.date.today() + datetime.timedelta(days=7)).isoformat()


class CombinedReviewTests(SharedPatientCase):
    def test_a_clinical_note_only_saves_just_the_note(self):
        response = self.review()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith(f"{self.history}#assessment-{self.assessment_id}"))
        self.assertEqual([n["note"] for n in self.notes()], ["Kidney function needs a recheck."])
        self.assertEqual(self.appointments(), [])
        self.assertEqual(self.rescreen_requests(), [])

    def test_a_note_only_ignores_follow_up_fields_that_were_left_in_the_form(self):
        self.review(date=next_week(), time="09:00", purpose="leftover")
        self.assertEqual(len(self.notes()), 1)
        self.assertEqual(self.appointments(), [])

    def test_a_clinical_note_with_a_follow_up_saves_both(self):
        response = self.review(mode="note_follow_up", date=next_week(), time="09:30", purpose="Repeat creatinine and ACR", notes="Fasting")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(self.notes()), 1)
        (appointment,) = self.appointments()
        self.assertEqual((appointment["purpose"], appointment["notes"]), ("Repeat creatinine and ACR", "Fasting"))
        self.assertEqual(self.rescreen_requests(), [])

    def test_the_follow_up_can_also_let_the_patient_screen_again_now(self):
        self.review(mode="note_follow_up", date=next_week(), time="09:30", purpose="Recheck", rescreen="1")
        self.assertEqual(len(self.rescreen_requests()), 1)
        self.assertIn("requested a follow-up screening", self.text(self.patient.get("/dashboard")))

    def test_nothing_is_saved_when_the_follow_up_is_incomplete_and_what_was_typed_is_kept(self):
        for missing in ({"purpose": "Recheck"}, {"date": next_week(), "time": "09:30"}, {"date": "2020-01-01", "time": "09:00", "purpose": "Recheck"}):
            response = self.review(mode="note_follow_up", note="A long careful clinical note.", **missing)
            page = self.text(response)
            self.assertEqual(response.status_code, 200, missing)
            self.assertIn("Nothing was saved yet", page)
            self.assertIn("A long careful clinical note.", page)
            self.assertIn('value="note_follow_up" checked', page)
            self.assertEqual(self.notes(), [], missing)
            self.assertEqual(self.appointments(), [], missing)

    def test_an_empty_note_is_refused_either_way(self):
        for mode in ("note", "note_follow_up"):
            page = self.text(self.review(mode=mode, note="   ", date=next_week(), time="09:00", purpose="Recheck"))
            self.assertIn("Write your clinical note.", page)
        self.assertEqual((self.notes(), self.appointments()), ([], []))

    def test_a_note_can_only_go_on_this_patients_own_results(self):
        stranger = self.signed_in(email="stranger@example.com")
        self.post("/screening", answers(), client=stranger, token_from="/screening")
        theirs = self.app.extensions["assessment_store"].list_assessments(self.store.find_by_email("stranger@example.com")["user_id"])[0]["assessment_id"]
        self.assertEqual(self.review(assessment_id=str(theirs)).status_code, 404)
        self.assertEqual(self.app.extensions["clinical_review_store"].list_for_assessment(theirs), [])
        self.assertEqual(self.review(assessment_id="999999").status_code, 404)
        self.assertEqual(self.review(mode="something-else").status_code, 400)

    def test_the_page_has_one_review_form_instead_of_three(self):
        page = self.text(self.professional.get(self.history))
        self.assertEqual(page.count('action="/patients/%d/review"' % self.patient_id), 1)
        self.assertNotIn('action="/patients/%d/follow-up"' % self.patient_id, page)
        self.assertNotIn('action="/patients/%d/appointments"' % self.patient_id, page)
        self.assertIn("Clinical note only", page)
        self.assertIn("Clinical note + follow-up", page)

    def test_a_link_can_open_the_form_on_a_result_with_the_follow_up_chosen(self):
        page = self.text(self.professional.get(f"{self.history}?assessment={self.assessment_id}&with=follow-up"))
        self.assertIn('value="note_follow_up" checked', page)
        self.assertIn(f'<option value="{self.assessment_id}" selected', page)
        self.assertNotIn('data-shown-when="mode=note_follow_up" hidden', page)
        page = self.text(self.professional.get(self.history))
        self.assertIn('value="note" checked', page)
        self.assertIn('data-shown-when="mode=note_follow_up" hidden', page)


class SharedResultButtonsTests(SharedPatientCase):
    def test_a_shared_result_offers_a_note_or_a_note_with_a_follow_up_for_that_result(self):
        page = self.text(self.professional.get(f"{self.history}/assessments/{self.assessment_id}"))
        note_link = f"/patients/{self.patient_id}?assessment={self.assessment_id}#write-review"
        follow_up_link = f"/patients/{self.patient_id}?assessment={self.assessment_id}&amp;with=follow-up#write-review"
        self.assertIn(note_link, page)
        self.assertIn(follow_up_link, page)
        self.assertIn("Add a clinical note", page)
        self.assertIn("Add note + follow-up", page)


class RequiredOptionalLabelTests(SharedPatientCase):
    MARK = re.compile(r'<span class="required-mark" aria-hidden="true">\*</span>(?!<span class="visually-hidden">\(required| Required</p>)')

    def check(self, client, path):
        page = self.text(client.get(path))
        self.assertIn("<form", page, path)
        self.assertNotIn("chip-required", page, f"{path}: the old Required chip is still shown")
        self.assertNotIn("chip-optional", page, f"{path}: the old Optional chip is still shown")
        self.assertIsNone(self.MARK.search(page), f"{path}: a required mark without words for screen readers")
        return page

    def test_general_user_forms(self):
        self.check(self.client, "/login")
        page = self.check(self.client, "/register")
        self.assertIn("Account type", page)
        self.assertNotIn("I am a", page)
        page = self.check(self.signed_in(email="new@example.com"), "/screening")
        self.assertIn('<p class="form-required-note">', page)
        self.assertEqual(page.count("<legend>") + page.count('<label class="form-label" for="f-'),
                         len(re.findall(r'(?:<legend>|<label class="form-label" for="f-)[^<]*<span class="required-mark"', page)))
        self.check(self.patient, "/account")
        self.check(self.patient, "/reports")

    def test_healthcare_professional_forms(self):
        self.review(mode="note_follow_up", date=next_week(), time="09:30", purpose="Recheck")
        self.check(self.professional, self.history)
        self.check(self.professional, "/patient-records/new")
        self.check(self.professional, "/account")
