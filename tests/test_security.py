"""
Checks for services/security.py: password hashing, the CSRF token and safe redirects.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

os.environ.setdefault("SECRET_KEY", "test-only-secret-key")
os.environ["FLASK_DEBUG"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, session  # noqa: E402

from services import security  # noqa: E402


class PasswordHashTests(unittest.TestCase):
    def test_the_hash_is_not_the_password_and_verifies(self):
        stored = security.hash_password("a-long-enough-phrase")
        self.assertNotIn("a-long-enough-phrase", stored)
        self.assertTrue(stored.startswith(("scrypt:", "pbkdf2:")))
        self.assertLess(len(stored), 255)                                   # it must fit the password_hash column
        self.assertTrue(security.verify_password(stored, "a-long-enough-phrase"))
        self.assertFalse(security.verify_password(stored, "a-long-enough-phrasE"))

    def test_the_same_password_gets_a_different_hash_each_time(self):
        self.assertNotEqual(security.hash_password("same-phrase-here"), security.hash_password("same-phrase-here"))

    def test_the_dummy_hash_never_matches_a_real_guess(self):
        for guess in ("", "password", "a-long-enough-phrase"):
            self.assertFalse(security.verify_password(security.DUMMY_HASH, guess))


class SafeRedirectTests(unittest.TestCase):
    def test_paths_inside_the_site_are_kept(self):
        for target in ("/account", "/dashboard?tab=1", "/a/b/c"):
            self.assertEqual(security.safe_next_url(target, "/home"), target)

    def test_everything_that_could_leave_the_site_is_replaced(self):
        for target in ("https://evil.example", "http://evil.example/x", "//evil.example", "/\\evil.example", "javascript:alert(1)",
                       "evil.example", "", None, "/ok\nSet-Cookie: x=1", "/ok\r\nLocation: http://evil.example", "\\\\evil.example",
                       "///evil.example", 5):
            self.assertEqual(security.safe_next_url(target, "/home"), "/home", repr(target))


class CsrfTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test"

    def test_the_token_is_stable_within_a_session_and_hard_to_guess(self):
        with self.app.test_request_context():
            first = security.csrf_token()
            self.assertEqual(first, security.csrf_token())
            self.assertGreaterEqual(len(first), 40)
            self.assertEqual(session["csrf_token"], first)

    def test_only_the_exact_token_is_accepted(self):
        with self.app.test_request_context():
            token = security.csrf_token()
            self.assertTrue(security.csrf_is_valid(token))
            for wrong in (None, "", token[:-1], token + "x", "guess"):
                self.assertFalse(security.csrf_is_valid(wrong), repr(wrong))

    def test_without_a_session_token_nothing_is_valid(self):
        with self.app.test_request_context():
            self.assertFalse(security.csrf_is_valid("anything"))


if __name__ == "__main__":
    unittest.main()
