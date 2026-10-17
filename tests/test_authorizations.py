"""
Checks for services/authorizations.py: the business rules on top of authorization_store.py. Uses in-memory stores
only - the store's own behaviour (accept/decline/revoke, reusing a row) is already checked in
tests/test_authorization_store.py; this file is about what may and may not happen, and how a row is described.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import authorizations  # noqa: E402
from services.authorization_store import MemoryAuthorizationStore  # noqa: E402
from services.user_store import MemoryUserStore  # noqa: E402

NOW = datetime(2026, 9, 20, 10, 0, 0)
LATER = datetime(2026, 9, 21, 10, 0, 0)


def new_user(users, role, name, **professional):
    return users.create_user({"email": f"{name.lower().replace(' ', '.')}@example.com", "full_name": name, "role": role,
                              "professional": professional or None}, "h", NOW)


class AuthorizationsTests(unittest.TestCase):
    def setUp(self):
        self.users = MemoryUserStore()
        self.auth = MemoryAuthorizationStore(self.users)
        self.patient = new_user(self.users, "general", "Ana Reyes")
        self.professional = new_user(self.users, "professional", "Dr. Maria Cruz", profession_title="Nephrologist", institution="City Hospital")

    def test_a_patient_can_request_a_real_professional(self):
        row = authorizations.request_authorization(self.auth, self.users, self.patient, self.professional, NOW)
        self.assertEqual(row["status"], "pending")

    def test_a_patient_cannot_request_a_general_account(self):
        other_general = new_user(self.users, "general", "Ben Cruz")
        with self.assertRaises(authorizations.NotAProfessionalError):
            authorizations.request_authorization(self.auth, self.users, self.patient, other_general, NOW)

    def test_a_patient_cannot_request_an_account_that_does_not_exist(self):
        with self.assertRaises(authorizations.NotAProfessionalError):
            authorizations.request_authorization(self.auth, self.users, self.patient, 987654321, NOW)

    def test_a_patient_cannot_request_their_own_account(self):
        with self.assertRaises(ValueError):
            authorizations.request_authorization(self.auth, self.users, self.patient, self.patient, NOW)

    def test_the_professional_can_accept_a_pending_request(self):
        authorizations.request_authorization(self.auth, self.users, self.patient, self.professional, NOW)
        self.assertTrue(authorizations.respond_to_request(self.auth, self.patient, self.professional, True, LATER))
        self.assertTrue(authorizations.is_authorized(self.auth, self.patient, self.professional))

    def test_the_professional_can_decline_a_pending_request(self):
        authorizations.request_authorization(self.auth, self.users, self.patient, self.professional, NOW)
        self.assertTrue(authorizations.respond_to_request(self.auth, self.patient, self.professional, False, LATER))
        self.assertFalse(authorizations.is_authorized(self.auth, self.patient, self.professional))

    def test_is_authorized_is_false_before_any_request(self):
        self.assertFalse(authorizations.is_authorized(self.auth, self.patient, self.professional))

    def test_is_authorized_is_false_while_only_pending(self):
        authorizations.request_authorization(self.auth, self.users, self.patient, self.professional, NOW)
        self.assertFalse(authorizations.is_authorized(self.auth, self.patient, self.professional))

    def test_revoking_ends_an_accepted_authorization(self):
        authorizations.request_authorization(self.auth, self.users, self.patient, self.professional, NOW)
        authorizations.respond_to_request(self.auth, self.patient, self.professional, True, LATER)
        self.assertTrue(authorizations.revoke(self.auth, self.patient, self.professional, LATER))
        self.assertFalse(authorizations.is_authorized(self.auth, self.patient, self.professional))

    def test_describe_for_patient_attaches_the_professionals_own_details(self):
        authorizations.request_authorization(self.auth, self.users, self.patient, self.professional, NOW)
        described = authorizations.describe_for_patient(self.auth, self.users, self.patient)
        self.assertEqual(len(described), 1)
        self.assertEqual(described[0]["professional_name"], "Dr. Maria Cruz")
        self.assertEqual(described[0]["profession_title"], "Nephrologist")
        self.assertEqual(described[0]["institution"], "City Hospital")
        self.assertEqual(described[0]["status"], "pending")

    def test_describe_for_professional_attaches_the_patients_own_details(self):
        authorizations.request_authorization(self.auth, self.users, self.patient, self.professional, NOW)
        described = authorizations.describe_for_professional(self.auth, self.users, self.professional)
        self.assertEqual(len(described), 1)
        self.assertEqual(described[0]["patient_name"], "Ana Reyes")
        self.assertEqual(described[0]["patient_email"], "ana.reyes@example.com")

    def test_describe_for_professional_can_be_narrowed_to_pending_only(self):
        other_patient = new_user(self.users, "general", "Ben Cruz")
        authorizations.request_authorization(self.auth, self.users, self.patient, self.professional, NOW)
        authorizations.request_authorization(self.auth, self.users, other_patient, self.professional, NOW)
        authorizations.respond_to_request(self.auth, other_patient, self.professional, True, LATER)
        pending = authorizations.describe_for_professional(self.auth, self.users, self.professional, statuses={"pending"})
        self.assertEqual([row["patient_name"] for row in pending], ["Ana Reyes"])


class SearchProfessionalsTests(unittest.TestCase):
    def setUp(self):
        self.users = MemoryUserStore()
        self.cruz = new_user(self.users, "professional", "Dr. Maria Cruz", profession_title="Nephrologist")
        self.santos = new_user(self.users, "professional", "Dr. Jose Santos", profession_title="Nurse")
        self.patient = new_user(self.users, "general", "Ana Reyes")

    def test_search_by_partial_name_is_case_insensitive(self):
        self.assertEqual([u["full_name"] for u in self.users.search_professionals("cruz")], ["Dr. Maria Cruz"])
        self.assertEqual([u["full_name"] for u in self.users.search_professionals("CRUZ")], ["Dr. Maria Cruz"])

    def test_search_by_exact_email_matches_even_when_the_name_does_not_contain_it(self):
        santos_email = self.users.find_by_id(self.santos)["email"]
        self.assertEqual([u["full_name"] for u in self.users.search_professionals(santos_email)], ["Dr. Jose Santos"])
        self.assertEqual(self.users.search_professionals("not-a-real-email@example.com"), [])

    def test_a_general_account_is_never_returned_even_with_a_matching_name(self):
        self.assertEqual(self.users.search_professionals("ana"), [])
        self.assertEqual(self.users.search_professionals("ana.reyes@example.com"), [])

    def test_a_search_matching_several_professionals_returns_all_of_them_sorted_by_name(self):
        self.assertEqual([u["full_name"] for u in self.users.search_professionals("dr.")], ["Dr. Jose Santos", "Dr. Maria Cruz"])

    def test_a_blank_search_returns_nothing(self):
        self.assertEqual(self.users.search_professionals(""), [])
        self.assertEqual(self.users.search_professionals("   "), [])

    def test_no_match_returns_an_empty_list_not_an_error(self):
        self.assertEqual(self.users.search_professionals("nobody with this name"), [])


if __name__ == "__main__":
    unittest.main()
