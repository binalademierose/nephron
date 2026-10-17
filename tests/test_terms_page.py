"""The Terms & Conditions page (routes/main_routes.py, templates/legal/terms.html).
Promises worth guarding: it is public (no sign-in), it loads, it carries the not-a-diagnosis disclaimer, and it is
linked from the places a new user meets it (the footer and the registration page)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from helpers import AppTestCase  # noqa: E402


class TermsPageTests(AppTestCase):
    def test_terms_is_public_and_complete(self):
        response = self.client.get("/terms")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Terms &amp; Conditions", body)
        self.assertIn("not a diagnosis", body)          # the disclaimer heading must be there
        self.assertIn("Your information and privacy", body)

    def test_registration_links_to_terms(self):
        self.assertIn('href="/terms"', self.client.get("/register").get_data(as_text=True))

    def test_footer_links_to_terms(self):
        self.assertIn('href="/terms"', self.client.get("/").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
