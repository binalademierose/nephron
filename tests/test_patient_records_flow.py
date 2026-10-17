"""
Checks for the professional's own patient records: creating one, the auto-generated code, ownership (one
professional never sees another's patient), performing a Preliminary screening on a patient's behalf, and the
Risk Analysis page. Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase  # noqa: E402
from test_screening_flow import answers  # noqa: E402
from services import patient_records, security  # noqa: E402


class CreatePatientTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.professional = self.signed_in(**self.professional_details())

    def _create(self, **changes):
        form = {"full_name": "Juan Dela Cruz", "date_of_birth": "1968-01-15", "country": "Other", "gender": "Male", "sex": "Male"}
        form.update(changes)
        return self.post("/patient-records/new", form, client=self.professional, token_from="/patient-records/new")

    def test_a_complete_form_creates_a_patient_with_a_generated_code(self):
        response = self._create()
        self.assertEqual(response.status_code, 302)
        self.assertIn("/patient-records/NPH-", response.headers["Location"])
        page = self.text(self.professional.get(response.headers["Location"]))
        self.assertIn("Juan Dela Cruz", page)

    def test_two_patients_get_two_different_sequential_codes(self):
        first = self._create(full_name="First Patient")
        second = self._create(full_name="Second Patient")
        self.assertNotEqual(first.headers["Location"], second.headers["Location"])

    def test_an_incomplete_form_is_refused_with_no_patient_created(self):
        response = self._create(full_name="")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Enter the patient", self.text(response))
        self.assertEqual(patient_records.for_professional(self.app.extensions["patient_records_store"], self._professional_id()), [])

    def _professional_id(self):
        return self.store.find_by_email("dr.cruz@example.com")["user_id"]

    def test_a_future_birthday_is_refused(self):
        response = self._create(date_of_birth="2099-01-01")
        self.assertIn("cannot be in the future", self.text(response))

    def test_the_new_patient_page_requires_being_signed_in_as_a_professional(self):
        general = self.signed_in()
        response = self.post("/patient-records/new", {"full_name": "X", "date_of_birth": "1986-01-15", "country": "Other", "gender": "Male", "sex": "Male"}, client=general, token_from="/dashboard")
        self.assertEqual(response.status_code, 403)



class OwnershipTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.professional = self.signed_in(**self.professional_details())
        self.other = self.signed_in(**self.professional_details(email="dr.other@example.com", full_name="Dr. Other"))
        response = self.post("/patient-records/new", {"full_name": "Juan Dela Cruz", "date_of_birth": "1968-01-15", "country": "Other", "gender": "Male", "sex": "Male"},
                             client=self.professional, token_from="/patient-records/new")
        self.code = response.headers["Location"].split("/")[-2]

    def test_the_owning_professional_sees_the_patients_profile(self):
        page = self.text(self.professional.get(f"/patient-records/{self.code}"))
        self.assertIn("Juan Dela Cruz", page)

    def test_a_different_professional_gets_404_for_the_profile(self):
        self.assertEqual(self.other.get(f"/patient-records/{self.code}").status_code, 404)

    def test_a_different_professional_cannot_reach_the_screening_form(self):
        self.assertEqual(self.other.get(f"/patient-records/{self.code}/screening").status_code, 404)

    def test_a_different_professional_does_not_see_the_patient_in_their_own_list(self):
        page = self.text(self.other.get("/patient-records"))
        # "Juan Dela Cruz" also appears as the search box's own placeholder example text, so check for an actual
        # row instead of the name (a plain substring search would pass even if ownership were broken).
        self.assertNotIn('class="patient-name-link"', page)
        self.assertIn("No patients yet", page)

    def test_an_unknown_code_is_404_for_anyone(self):
        self.assertEqual(self.professional.get("/patient-records/NPH-9999").status_code, 404)

    def test_a_general_user_cannot_reach_any_of_it(self):
        general = self.signed_in()
        for path in ("/patient-records", f"/patient-records/{self.code}", f"/patient-records/{self.code}/screening"):
            self.assertEqual(general.get(path).status_code, 403, path)


class ScreeningForAPatientTests(AppTestCase):
    model = "explainable"

    def setUp(self):
        super().setUp()
        self.professional = self.signed_in(**self.professional_details())
        response = self.post("/patient-records/new", {"full_name": "Juan Dela Cruz", "date_of_birth": "1968-01-15", "country": "Other", "gender": "Male", "sex": "Male"},
                             client=self.professional, token_from="/patient-records/new")
        self.code = response.headers["Location"].split("/")[-2]
        self.patient_user_id = self.app.extensions["patient_records_store"].get_by_code(self.code)["user_id"]

    def test_age_sex_and_country_are_fixed_from_the_patient_record(self):
        page = self.text(self.professional.get(f"/patient-records/{self.code}/screening"))
        self.assertIn('<input type="hidden" name="Age" value="58">', page)
        self.assertIn('<input type="hidden" name="Sex" value="Male">', page)
        self.assertIn('<input type="hidden" name="Country" value="Other">', page)
        self.assertIn('<input type="hidden" name="Gender" value="Male">', page)
        self.assertIn("Worked out from your date of birth.", page)

    def test_a_changed_fixed_answer_in_the_submitted_form_is_replaced_by_the_server(self):
        self.post(f"/patient-records/{self.code}/screening", answers(Age="20", Sex="Female"), client=self.professional,
                  token_from=f"/patient-records/{self.code}/screening")
        store = self.app.extensions["assessment_store"]
        saved = store.get_assessment(self.patient_user_id, store.list_assessments(self.patient_user_id)[0]["assessment_id"])
        self.assertEqual((saved["inputs"]["Age"], saved["inputs"]["Sex"]), (58, "Male"))

    def _professional_id(self):
        return self.store.find_by_email("dr.cruz@example.com")["user_id"]

    def test_submitting_saves_the_assessment_under_the_patients_own_shadow_account_not_the_professionals(self):
        response = self.post(f"/patient-records/{self.code}/screening", answers(), client=self.professional, token_from=f"/patient-records/{self.code}/screening")
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"/patient-records/{self.code}/results/", response.headers["Location"])
        store = self.app.extensions["assessment_store"]
        self.assertEqual(len(store.list_assessments(self.patient_user_id)), 1)
        self.assertEqual(len(store.list_assessments(self._professional_id())), 0)

    def test_a_success_toast_and_the_result_page_both_show(self):
        response = self.post(f"/patient-records/{self.code}/screening", answers(), client=self.professional, token_from=f"/patient-records/{self.code}/screening")
        page = self.text(self.professional.get(response.headers["Location"]))
        self.assertIn("saved to this patient", page)          # Jinja escapes the apostrophe in "patient's" to &#39;
        self.assertIn("Risk Classification", page)
        self.assertIn("Juan Dela Cruz", page)

    def test_sending_the_same_answers_twice_quickly_does_not_create_two_assessments(self):
        self.post(f"/patient-records/{self.code}/screening", answers(), client=self.professional, token_from=f"/patient-records/{self.code}/screening")
        self.post(f"/patient-records/{self.code}/screening", answers(), client=self.professional, token_from=f"/patient-records/{self.code}/screening")
        store = self.app.extensions["assessment_store"]
        self.assertEqual(len(store.list_assessments(self.patient_user_id)), 1)

    def test_an_invalid_answer_is_refused_and_nothing_is_saved(self):
        response = self.post(f"/patient-records/{self.code}/screening", answers(Sleep_Duration_Hours="30"), client=self.professional, token_from=f"/patient-records/{self.code}/screening")
        self.assertEqual(response.status_code, 200)
        store = self.app.extensions["assessment_store"]
        self.assertEqual(store.list_assessments(self.patient_user_id), [])


class RiskAnalysisTests(AppTestCase):
    model = "explainable"

    def setUp(self):
        super().setUp()
        self.professional = self.signed_in(**self.professional_details())
        self.other = self.signed_in(**self.professional_details(email="dr.other2@example.com", full_name="Dr. Other"))
        response = self.post("/patient-records/new", {"full_name": "Juan Dela Cruz", "date_of_birth": "1968-01-15", "country": "Other", "gender": "Male", "sex": "Male"},
                             client=self.professional, token_from="/patient-records/new")
        self.code = response.headers["Location"].split("/")[-2]
        result = self.post(f"/patient-records/{self.code}/screening", answers(), client=self.professional, token_from=f"/patient-records/{self.code}/screening")
        self.result_url = result.headers["Location"]
        self.assessment_id = self.result_url.rstrip("/").split("/")[-1]

    def test_the_owning_professional_sees_the_real_result(self):
        page = self.text(self.professional.get(self.result_url))
        self.assertIn("Risk Classification", page)
        self.assertIn("What raised your estimate", page)

    def test_a_different_professional_gets_404(self):
        self.assertEqual(self.other.get(self.result_url).status_code, 404)

    def test_an_assessment_id_that_does_not_belong_to_this_patient_is_404(self):
        self.assertEqual(self.professional.get(f"/patient-records/{self.code}/results/999999").status_code, 404)

    def test_the_profile_links_to_the_same_risk_analysis_page(self):
        page = self.text(self.professional.get(f"/patient-records/{self.code}"))
        self.assertIn(f"/patient-records/{self.code}/results/{self.assessment_id}", page)


class ShadowAccountCannotSignInTests(AppTestCase):
    def test_a_patient_records_shadow_account_can_never_be_authenticated(self):
        professional = self.signed_in(**self.professional_details())
        response = self.post("/patient-records/new", {"full_name": "Juan Dela Cruz", "date_of_birth": "1968-01-15", "country": "Other", "gender": "Male", "sex": "Male"},
                             client=professional, token_from="/patient-records/new")
        code = response.headers["Location"].split("/")[-2]
        record = self.app.extensions["patient_records_store"].get_by_code(code)
        shadow_user = self.store.find_by_id(record["user_id"])
        self.assertTrue(shadow_user["is_patient_record"])
        # Even with (a hypothetically known) correct password, the login route must refuse it.
        known_password = "Whatever-Password-1"
        self.store._users[record["user_id"]]["password_hash"] = security.hash_password(known_password)
        response = self.post("/login", {"email": shadow_user["email"], "password": known_password}, token_from="/login")
        self.assertEqual(response.status_code, 200)                          # stayed on the sign-in page
        self.assertIn("Check your email address and password", self.text(response))

    def test_role_required_blocks_a_patient_record_even_if_a_session_were_forced(self):
        professional = self.signed_in(**self.professional_details())
        response = self.post("/patient-records/new", {"full_name": "Juan Dela Cruz", "date_of_birth": "1968-01-15", "country": "Other", "gender": "Male", "sex": "Male"},
                             client=professional, token_from="/patient-records/new")
        code = response.headers["Location"].split("/")[-2]
        user_id = self.app.extensions["patient_records_store"].get_by_code(code)["user_id"]
        shadow_client = self.app.test_client()
        with shadow_client.session_transaction() as session:
            session["user_id"] = user_id
            from datetime import datetime
            session["issued_at"] = datetime(2026, 1, 1).isoformat()
        self.assertEqual(shadow_client.get("/dashboard").status_code, 302)   # treated as signed out, sent to /login


if __name__ == "__main__":
    unittest.main()


class PatientRecordDraftTests(AppTestCase):
    """A professional's half-finished screening for a patient survives a refresh, a Back or a closed tab - the same
    autosave a General User has - and belongs to that patient record only."""
    model = True

    def setUp(self):
        super().setUp()
        self.professional = self.signed_in(**self.professional_details())
        response = self.post("/patient-records/new", {"full_name": "Juan Dela Cruz", "date_of_birth": "1968-01-15", "country": "Other", "gender": "Male", "sex": "Male"},
                             client=self.professional, token_from="/patient-records/new")
        self.code = response.headers["Location"].split("/")[-2]
        self.url = f"/patient-records/{self.code}/screening"

    def test_the_form_autosaves_to_the_patient_records_own_draft_url(self):
        self.assertIn(f'data-draft-save-url="{self.url}/draft"', self.text(self.professional.get(self.url)))

    def test_a_saved_draft_comes_back_after_a_reload_on_the_step_it_was_on(self):
        self.post(f"{self.url}/draft", {"Ethnicity": "Asian", "height_cm": "171", "Diabetes": "1", "current_step": "history"},
                  client=self.professional, token_from=self.url)
        page = self.text(self.professional.get(self.url))
        self.assertIn('value="171"', page)
        self.assertRegex(page, r'name="Diabetes" value="1"[^>]*checked')
        self.assertIn('data-first-error-step="1"', page)

    def test_submitting_the_screening_clears_the_draft(self):
        self.post(f"{self.url}/draft", {"height_cm": "171", "current_step": "about"}, client=self.professional, token_from=self.url)
        self.post(self.url, answers(), client=self.professional, token_from=self.url)
        self.assertNotIn('value="171"', self.text(self.professional.get(self.url)))

    def test_another_professional_cannot_save_or_read_this_patients_draft(self):
        other = self.signed_in(**self.professional_details(email="dr.other@example.com", full_name="Dr. Other"))
        self.assertEqual(self.post(f"{self.url}/draft", {"height_cm": "171"}, client=other, token_from="/patient-records").status_code, 404)


class PatientGenderTests(AppTestCase):
    """A professional records the patient's gender; the model gets the sex it implies, or the one asked for."""
    model = "explainable"

    def setUp(self):
        super().setUp()
        self.professional = self.signed_in(**self.professional_details())

    def new_patient(self, **fields):
        form = {"full_name": "Alex Reyes", "date_of_birth": "1980-03-02", "country": "Philippines", "province_code": "1300000000", **fields}
        return self.post("/patient-records/new", form, client=self.professional, token_from="/patient-records/new")

    def record(self, response):
        return self.app.extensions["patient_records_store"].get_by_code(response.headers["Location"].split("/")[-2])

    def test_the_form_asks_gender_and_holds_back_sex_at_birth(self):
        page = self.text(self.professional.get("/patient-records/new"))
        self.assertIn('<option value="Lesbian woman" data-sex="Female"', page)
        self.assertIn('data-sex-follow-up hidden', page)

    def test_a_lesbian_woman_is_recorded_with_her_gender_and_female_for_the_model(self):
        record = self.record(self.new_patient(gender="Lesbian woman"))
        self.assertEqual((record["gender"], record["sex"]), ("Lesbian woman", "Female"))

    def test_a_non_binary_patient_needs_the_sex_assigned_at_birth(self):
        response = self.new_patient(gender="Non-binary")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="sex-error"', self.text(response))
        record = self.record(self.new_patient(gender="Non-binary", sex="Male"))
        self.assertEqual((record["gender"], record["sex"]), ("Non-binary", "Male"))

    def test_the_screening_keeps_the_records_gender_and_saves_it_with_the_answers(self):
        record = self.record(self.new_patient(gender="Transgender woman", sex="Male"))
        url = f"/patient-records/{record['patient_code']}/screening"
        page = self.text(self.professional.get(url))
        self.assertIn('<input type="hidden" name="Gender" value="Transgender woman">', page)
        self.post(url, answers(Gender="Female", Sex="Female"), client=self.professional, token_from=url)
        store = self.app.extensions["assessment_store"]
        saved = store.get_assessment(record["user_id"], store.list_assessments(record["user_id"])[0]["assessment_id"])["inputs"]
        self.assertEqual((saved["Gender"], saved["Sex"]), ("Transgender woman", "Male"))
