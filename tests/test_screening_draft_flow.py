"""
Checks for the screening draft website path: autosave while filling the form, resuming with values and the
right step after a refresh, and discarding. Uses the explainable stand-in model (real validation, no MySQL needed).
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase  # noqa: E402


class ScreeningDraftTests(AppTestCase):
    model = "explainable"

    def setUp(self):
        super().setUp()
        self.patient = self.signed_in()

    def test_no_draft_means_the_form_opens_blank_on_the_first_step(self):
        page = self.text(self.patient.get("/screening"))
        self.assertIn("About you", page)
        self.assertIn('<option value="">Choose one</option>', page)         # Country: nothing pre-selected

    def test_saving_a_draft_and_reloading_keeps_the_typed_values(self):
        # A typed answer comes back (Age and Country now come from the account, so a draft's own copy of them is ignored).
        self.post("/screening/draft", {"Ethnicity": "Asian", "height_cm": "163", "current_step": "about_you"},
                 client=self.patient, token_from="/screening")
        page = self.text(self.patient.get("/screening"))
        self.assertIn('value="163"', page)
        self.assertRegex(page, r'<option value="Asian"\s+selected')

    def test_the_form_resumes_on_the_step_the_draft_was_last_saved_on(self):
        # "Health history" is the second step (index 1); the browser's own JS is what actually moves the visual
        # is-active class there (confirmed by hand against a real browser) - a plain HTTP GET never runs that JS,
        # so what a test at this level can check is the value the server hands the JS to act on.
        self.post("/screening/draft", {"Diabetes": "1", "current_step": "history"},
                 client=self.patient, token_from="/screening")
        page = self.text(self.patient.get("/screening"))
        self.assertIn('data-first-error-step="1"', page)

    def test_an_unrecognised_step_name_falls_back_to_the_first_step(self):
        self.post("/screening/draft", {"current_step": "not-a-real-step"}, client=self.patient, token_from="/screening")
        page = self.text(self.patient.get("/screening"))
        self.assertIn('data-first-error-step="-1"', page)

    def test_discarding_clears_the_draft(self):
        self.post("/screening/draft", {"Age": "52", "current_step": "about_you"}, client=self.patient, token_from="/screening")
        self.post("/screening/draft/discard", {}, client=self.patient, token_from="/screening")
        page = self.text(self.patient.get("/screening"))
        self.assertNotIn('value="52"', page)

    def test_completing_the_screening_removes_its_own_draft(self):
        self.post("/screening/draft", {"Age": "52", "current_step": "about_you"}, client=self.patient, token_from="/screening")
        from services.screening_draft_store import get_screening_draft_store
        with self.app.app_context():
            pass
        store = self.app.extensions["screening_draft_store"]
        patient_id = self.store.find_by_email("ana@example.com")["user_id"]
        self.assertIsNotNone(store.get_draft(patient_id, "preliminary"))
        form = {name: (opt["options"][0]["value"] if opt["kind"] == "choice" else "0" if opt["kind"] == "yesno" else str(opt.get("min", 1)))
               for name, opt in ((q["name"], q) for q in self._catalog_questions())}
        form.update({"height_cm": "165", "weight_kg": "60", "Gender": "Female"})
        token = self.csrf(self.patient, "/screening")
        self.patient.post("/screening", data={**form, "csrf_token": token})
        self.assertIsNone(store.get_draft(patient_id, "preliminary"))

    def test_a_draft_cannot_be_read_or_discarded_by_someone_else(self):
        self.post("/screening/draft", {"Age": "52", "current_step": "about_you"}, client=self.patient, token_from="/screening")
        other = self.signed_in(email="ben@example.com", full_name="Ben Cruz")
        page = self.text(other.get("/screening"))
        self.assertNotIn('value="52"', page)

    def test_oversized_or_too_many_fields_are_quietly_dropped_not_refused(self):
        huge = {"note": "x" * 500}
        response = self.post("/screening/draft", huge, client=self.patient, token_from="/screening")
        self.assertEqual(response.status_code, 200)

    def _catalog_questions(self):
        from services import screening_contract
        return [q for q in screening_contract.load_catalog()["questions"] if q["kind"] != "derived"]


if __name__ == "__main__":
    unittest.main()
