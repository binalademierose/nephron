"""Checks for services/patient_records.py: validation, registering a new patient, and scoping to one professional."""
import os
import sys
import unittest
import uuid
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import patient_records  # noqa: E402
from services.patient_records_store import MemoryPatientRecordsStore  # noqa: E402
from services.user_store import MemoryUserStore  # noqa: E402

NOW = datetime(2026, 9, 20, 10, 0, 0)


def new_professional(users):
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    return users.create_user({"email": email, "full_name": "Dr. Luis Cruz", "role": "professional",
                              "professional": {"profession_title": "Nephrologist", "institution": None, "license_number": None}}, "h", NOW)


class ValidationTests(unittest.TestCase):
    TODAY = date(2026, 10, 3)

    def form(self, **changes):
        form = {"full_name": "Juan Dela Cruz", "date_of_birth": "1974-01-15", "gender": "Male", "sex": "Male", "country": "Philippines", "province_code": "1300000000"}
        form.update(changes)
        return patient_records.validate_new_patient(form, today=self.TODAY)

    def test_a_complete_form_has_no_errors_and_the_age_comes_from_the_birthday(self):
        values, errors = self.form()
        self.assertEqual(errors, {})
        self.assertEqual((values["age"], values["date_of_birth"], values["country"]), (52, date(1974, 1, 15), "Philippines"))

    def test_the_age_only_changes_on_the_birthday(self):
        self.assertEqual(self.form(date_of_birth="1974-10-04")[0]["age"], 51)    # birthday is tomorrow
        self.assertEqual(self.form(date_of_birth="1974-10-03")[0]["age"], 52)    # birthday is today

    def test_a_blank_name_is_refused(self):
        self.assertIn("full_name", self.form(full_name="  ")[1])

    def test_a_name_with_no_letters_is_refused(self):
        self.assertIn("full_name", self.form(full_name="12345")[1])

    def test_a_missing_future_or_unrealistic_birthday_is_refused(self):
        for bad in ("", "not-a-date", "2030-01-01", "1890-01-01"):
            self.assertIn("date_of_birth", self.form(date_of_birth=bad)[1], bad)
        self.assertNotIn("date_of_birth", self.form(date_of_birth="2010-06-01")[1])     # a 16-year-old is accepted

    def test_sex_at_birth_is_needed_only_when_the_gender_does_not_tell(self):
        self.assertIn("sex", self.form(gender="Non-binary", sex="Other")[1])
        self.assertIn("sex", self.form(gender="Prefer not to say", sex="")[1])
        values, errors = self.form(gender="Transgender woman", sex="Male")
        self.assertEqual((errors, values["sex"], values["gender"]), ({}, "Male", "Transgender woman"))

    def test_a_gender_that_tells_the_sex_gives_the_model_that_sex(self):
        for gender, sex in (("Gay man", "Male"), ("Lesbian woman", "Female"), ("Bisexual man", "Male"), ("Female", "Female")):
            values, errors = self.form(gender=gender, sex="")
            self.assertEqual((errors, values["sex"], values["gender"]), ({}, sex, gender), gender)

    def test_gender_must_be_one_the_form_offers(self):
        self.assertIn("gender", self.form(gender="")[1])
        self.assertIn("gender", self.form(gender="Martian")[1])

    def test_country_must_be_one_the_screening_offers(self):
        self.assertIn("country", self.form(country="Atlantis")[1])
        self.assertIn("country", self.form(country="")[1])

    def test_every_field_can_be_wrong_at_once(self):
        _, errors = self.form(full_name="", date_of_birth="", gender="", sex="", country="")
        self.assertEqual(set(errors), {"full_name", "date_of_birth", "gender", "country"})
        _, errors = self.form(full_name="", date_of_birth="", gender="Non-binary", sex="", country="")
        self.assertEqual(set(errors), {"full_name", "date_of_birth", "sex", "country"})


class RegisterAndScopeTests(unittest.TestCase):
    def setUp(self):
        self.users = MemoryUserStore()
        self.store = MemoryPatientRecordsStore(self.users)
        self.professional_id = new_professional(self.users)

    def test_registering_creates_a_real_shadow_account_with_an_unusable_password(self):
        user_id, code = patient_records.register_patient(self.store, self.professional_id, "Juan Dela Cruz", 52, "Male", NOW)
        self.assertRegex(code, r"^NPH-\d{4}$")
        shadow = self.users.find_by_id(user_id)
        self.assertEqual(shadow["role"], "general")
        self.assertTrue(shadow["is_patient_record"])
        self.assertTrue(shadow["email"].endswith("@patient-records.nephron.invalid"))
        self.assertGreater(len(shadow["password_hash"]), 20)             # a real, unguessable hash, not a placeholder

    def test_for_professional_lists_only_this_professionals_own_and_supports_a_search_term(self):
        other = new_professional(self.users)
        patient_records.register_patient(self.store, other, "Not Mine", 30, "Female", NOW)
        patient_records.register_patient(self.store, self.professional_id, "Juan Dela Cruz", 52, "Male", NOW)
        _, code = patient_records.register_patient(self.store, self.professional_id, "Maria Santos", 40, "Female", NOW)

        mine = patient_records.for_professional(self.store, self.professional_id)
        self.assertEqual({r["full_name"] for r in mine}, {"Juan Dela Cruz", "Maria Santos"})

        by_name = patient_records.for_professional(self.store, self.professional_id, term="maria")
        self.assertEqual([r["full_name"] for r in by_name], ["Maria Santos"])

        by_code = patient_records.for_professional(self.store, self.professional_id, term=code.lower())
        self.assertEqual([r["full_name"] for r in by_code], ["Maria Santos"])

    def test_get_owned_returns_none_for_a_record_belonging_to_another_professional(self):
        other = new_professional(self.users)
        user_id, _ = patient_records.register_patient(self.store, other, "Not Mine", 30, "Female", NOW)
        self.assertIsNone(patient_records.get_owned(self.store, user_id, self.professional_id))

    def test_get_owned_returns_the_record_for_its_own_professional(self):
        user_id, code = patient_records.register_patient(self.store, self.professional_id, "Juan Dela Cruz", 52, "Male", NOW)
        record = patient_records.get_owned(self.store, user_id, self.professional_id)
        self.assertEqual(record["patient_code"], code)


if __name__ == "__main__":
    unittest.main()
