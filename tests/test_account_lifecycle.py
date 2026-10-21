"""
test_account_lifecycle.py - the three account features added before launch:
  * the Terms & Conditions checkbox must be ticked to register,
  * the public FAQ page,
  * a signed-in person deactivating or permanently deleting their own account.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase, PASSWORD  # noqa: E402


class TermsCheckboxTests(AppTestCase):
    def test_registration_is_refused_without_agreeing_to_terms(self):
        page = self.register(self.new_browser(), agree_terms="")
        self.assertEqual(page.status_code, 200)                       # stays on the form, not signed in
        self.assertIn("agree to the Terms", self.text(page))
        self.assertIsNone(self.store.find_by_email("ana@example.com"))  # no account was created

    def test_registration_succeeds_when_the_box_is_ticked(self):
        self.register(self.new_browser(), agree_terms="agree")
        self.assertIsNotNone(self.store.find_by_email("ana@example.com"))


class FaqPageTests(AppTestCase):
    def test_faq_is_public_and_renders(self):
        page = self.client.get("/faq")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Frequently asked questions", self.text(page))


class DeactivateTests(AppTestCase):
    def test_a_person_can_deactivate_their_own_account(self):
        browser = self.signed_in()
        resp = self.post("/account/deactivate", {"password": PASSWORD}, client=browser, token_from="/account")
        self.assertEqual(resp.status_code, 302)                       # signed out, sent to login
        self.assertFalse(self.store.find_by_email("ana@example.com")["is_active"])
        # the right password is now refused because the account is switched off
        self.assertEqual(self.login(self.new_browser()).status_code, 403)

    def test_the_wrong_password_does_not_deactivate(self):
        browser = self.signed_in()
        resp = self.post("/account/deactivate", {"password": "not-my-password"}, client=browser, token_from="/account")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(self.store.find_by_email("ana@example.com")["is_active"])

    def test_a_professional_can_deactivate_too(self):
        doctor = self.signed_in(**self.professional_details())
        resp = self.post("/account/deactivate", {"password": PASSWORD}, client=doctor, token_from="/account")
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(self.store.find_by_email("dr.cruz@example.com")["is_active"])


class DeleteTests(AppTestCase):
    def test_a_person_can_permanently_delete_their_own_account(self):
        browser = self.signed_in()
        resp = self.post("/account/delete", {"password": PASSWORD, "confirm_delete": "delete"},
                         client=browser, token_from="/account")
        self.assertEqual(resp.status_code, 302)
        self.assertIsNone(self.store.find_by_email("ana@example.com"))   # the account is gone

    def test_delete_needs_the_confirmation_box(self):
        browser = self.signed_in()
        resp = self.post("/account/delete", {"password": PASSWORD}, client=browser, token_from="/account")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(self.store.find_by_email("ana@example.com"))  # still there

    def test_delete_needs_the_right_password(self):
        browser = self.signed_in()
        resp = self.post("/account/delete", {"password": "wrong-one", "confirm_delete": "delete"},
                         client=browser, token_from="/account")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(self.store.find_by_email("ana@example.com"))
