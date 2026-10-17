"""
Checks for the feedback and consent path: a share request is refused without an explicit yes (on the SERVER, not
just the page), the agreement is recorded, success is a toast and errors stay banners, and every consequential
form asks first. Run everything with:   python -m unittest discover -s tests -v
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase  # noqa: E402


class ShareConsentTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.patient = self.signed_in()
        self.professional = self.signed_in(**self.professional_details())
        self.professional_id = self.store.find_by_email("dr.cruz@example.com")["user_id"]
        self.patient_id = self.store.find_by_email("ana@example.com")["user_id"]

    def _request(self, **form):
        return self.post("/share/request", {"professional_user_id": str(self.professional_id), **form}, client=self.patient, token_from="/share")

    def _pending_for_professional(self):
        return "Ana Reyes" in self.text(self.professional.get("/patients")).split("Pending requests")[1].split("Authorized patients")[0]

    def test_a_request_with_no_consent_is_refused_and_nothing_is_sent(self):
        response = self._request()
        page = self.text(self.patient.get(response.headers["Location"]))
        self.assertIn("Please confirm what you are sharing", page)
        self.assertIn("Nothing was sent", page)
        self.assertFalse(self._pending_for_professional())
        self.assertEqual(self.app.extensions["consent_store"].list_for_patient(self.patient_id), [])

    def test_an_empty_consent_field_is_not_consent(self):
        self._request(consent="")
        self.assertFalse(self._pending_for_professional())

    def test_a_request_with_consent_is_sent_and_the_agreement_is_recorded(self):
        self._request(consent="1")
        self.assertTrue(self._pending_for_professional())
        records = self.app.extensions["consent_store"].list_for_patient(self.patient_id)
        self.assertEqual(len(records), 1)
        self.assertEqual((records[0]["professional_user_id"], records[0]["consent_type"], records[0]["consent_version"]),
                         (self.professional_id, "share_history", "share-history-v1"))

    def test_the_share_page_then_shows_when_the_person_agreed(self):
        self._request(consent="1")
        self.assertIn("You agreed to share on", self.text(self.patient.get("/share")))

    def test_the_refusal_does_not_notify_the_professional(self):
        self._request()
        self.assertNotIn("wants to share", self.text(self.professional.get("/notifications")))


class ConsentWordingTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.patient = self.signed_in()

    def test_the_consent_states_what_who_why_and_the_persons_control(self):
        page = self.text(self.patient.get("/share"))
        self.assertIn('id="share-consent-template"', page)
        for heading in ("What will be shared", "Who receives it", "Why", "Your control"):
            self.assertIn(heading, page)
        self.assertIn("If you go back now, nothing is sent", page)

    def test_a_search_result_carries_the_consent_dialog_and_a_no_javascript_checkbox(self):
        self.signed_in(**self.professional_details())
        page = self.text(self.patient.get("/share?q=cruz"))
        self.assertIn('data-confirm="consent"', page)
        self.assertIn('data-confirm-template="share-consent-template"', page)
        self.assertIn('name="consent" value=""', page)              # the field the dialog fills in
        self.assertRegex(page, r'<noscript><label class="consent-inline"><input type="checkbox" name="consent" value="1" required>')


class FeedbackStyleTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.patient = self.signed_in()
        self.professional = self.signed_in(**self.professional_details())
        self.professional_id = self.store.find_by_email("dr.cruz@example.com")["user_id"]
        self.patient_id = self.store.find_by_email("ana@example.com")["user_id"]

    def test_good_news_is_a_toast_not_a_banner(self):
        response = self.post("/share/request", {"consent": "1", "professional_user_id": str(self.professional_id)}, client=self.patient, token_from="/share")
        page = self.text(self.patient.get(response.headers["Location"]))
        self.assertIn("toast toast-success", page)
        self.assertIn("Request sent to Dr. Luis Cruz", page)
        self.assertNotIn("alert alert-success", page)

    def test_an_error_stays_a_banner_that_must_be_dismissed(self):
        response = self.post("/share/request", {"professional_user_id": str(self.professional_id)}, client=self.patient, token_from="/share")
        page = self.text(self.patient.get(response.headers["Location"]))
        self.assertIn("alert alert-error", page)
        self.assertNotIn("toast toast-error", page)

    def _accepted(self):
        self.post("/share/request", {"consent": "1", "professional_user_id": str(self.professional_id)}, client=self.patient, token_from="/share")
        self.post(f"/patients/respond/{self.patient_id}", {"action": "accept"}, client=self.professional, token_from="/patients")

    def test_the_professional_acknowledges_confidentiality_before_accepting(self):
        self.post("/share/request", {"consent": "1", "professional_user_id": str(self.professional_id)}, client=self.patient, token_from="/share")
        page = self.text(self.professional.get("/patients"))
        self.assertRegex(page, r'data-confirm="consent"[^>]*data-confirm-name="Ana Reyes"')
        self.assertIn("keep {name}", page)

    def test_ending_access_asks_first_on_both_sides(self):
        self._accepted()
        patient_page = self.text(self.patient.get("/share"))
        self.assertRegex(patient_page, r'revoke[^>]*\s+data-confirm="danger"')
        self.assertIn("Keep sharing", patient_page)
        professional_page = self.text(self.professional.get("/patients"))
        self.assertRegex(professional_page, r'revoke[^>]*\s+data-confirm="danger"')
        self.assertIn("Keep access", professional_page)

    def test_cancelling_or_deleting_an_appointment_asks_first(self):
        self._accepted()
        self.post(f"/patients/{self.patient_id}/appointments", {"date": "2030-11-10", "time": "14:30", "purpose": "Recheck labs"},
                 client=self.professional, token_from=f"/patients/{self.patient_id}")
        page = self.text(self.professional.get(f"/patients/{self.patient_id}"))
        self.assertEqual(len(re.findall(r'data-confirm="danger"', page)), 2)
        self.assertIn("Cancel this appointment?", page)
        self.assertIn("Delete this appointment?", page)

    def test_discarding_a_draft_asks_first(self):
        self.post("/screening/draft", {"Age": "52", "current_step": "about"}, client=self.patient, token_from="/screening")
        page = self.text(self.patient.get("/dashboard"))
        self.assertIn("Discard your unfinished screening?", page)
        self.assertRegex(page, r'discard[^>]*\s+data-confirm="danger"')

    def test_one_confirmation_dialog_exists_on_every_page(self):
        for path in ("/dashboard", "/share", "/notifications", "/follow-up"):
            self.assertEqual(self.text(self.patient.get(path)).count('id="nephron-confirm"'), 1, path)


if __name__ == "__main__":
    unittest.main()
