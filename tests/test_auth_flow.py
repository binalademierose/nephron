"""
Checks for registering, signing in and out, roles, and changing a password: the whole path a person takes.
They use an in-memory user store, so no database is needed. Run everything with:
    python -m unittest discover -s tests -v
"""
import os
import re
import sys
import unittest
from datetime import datetime, timedelta
from html.parser import HTMLParser
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import NEW_PASSWORD, PASSWORD, AppTestCase  # noqa: E402

import mysql.connector  # noqa: E402
from jinja2 import StrictUndefined  # noqa: E402

from app import create_app  # noqa: E402
from services.user_store import MemoryUserStore  # noqa: E402

T0 = datetime(2026, 9, 20, 10, 0, 0)


def at(moment):
    """Make the app believe it is this time (all stored times come from services.clock.now_utc)."""
    return mock.patch("services.clock.now_utc", return_value=moment)


class RegistrationTests(AppTestCase):
    def test_a_general_user_registers_and_is_signed_in(self):
        response = self.register()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/dashboard"))
        user = self.store.find_by_email("ana@example.com")
        self.assertEqual((user["role"], user["full_name"]), ("general", "Ana Reyes"))
        self.assertIsNone(user["profession_title"])
        home = self.client.get("/dashboard")
        self.assertEqual(home.status_code, 200)
        self.assertIn("Ana", self.text(home))
        self.assertIn("Welcome to Nephron", self.text(home))

    def test_the_password_is_stored_only_as_a_hash(self):
        self.register()
        stored = self.store.find_by_email("ana@example.com")["password_hash"]
        self.assertNotIn(PASSWORD, stored)
        self.assertTrue(stored.startswith(("scrypt:", "pbkdf2:")))

    def test_a_professional_registers_with_their_details(self):
        response = self.register(**self.professional_details(institution="City Hospital", license_number="PRC-12345"))
        self.assertTrue(response.headers["Location"].endswith("/professional"))
        user = self.store.find_by_email("dr.cruz@example.com")
        self.assertEqual((user["role"], user["profession_title"], user["institution"], user["license_number"]),
                         ("professional", "Nephrologist", "City Hospital", "PRC-12345"))
        page = self.text(self.client.get("/account"))
        self.assertIn("not verified", page)                        # the page is honest that these are self-declared

    def test_bad_input_shows_a_message_beside_each_field_and_keeps_what_was_typed(self):
        response = self.register(full_name="Ana Reyes", email="not-an-email", password="password123")
        page = self.text(response)
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="email-error"', page)
        self.assertIn('id="password-error"', page)
        self.assertIn('value="Ana Reyes"', page)                   # kept
        self.assertNotIn("password123", page)                      # the password is never sent back
        self.assertEqual(self.store._users, {})                    # nothing was created

    def test_the_same_email_cannot_register_twice_whatever_the_letter_case(self):
        self.register()
        second = self.register(self.new_browser(), email="  ANA@Example.COM ", full_name="Someone Else")
        self.assertEqual(second.status_code, 200)
        self.assertIn("already exists", self.text(second))
        self.assertEqual(len(self.store._users), 1)

    def test_a_role_cannot_be_forged(self):
        for forged in ("admin", "administrator", ""):
            response = self.register(role=forged)
            self.assertEqual(response.status_code, 200, forged)
            self.assertIn('id="role-error"', self.text(response))
        self.assertEqual(self.store._users, {})

    def test_a_professional_must_choose_a_profession_from_the_list(self):
        response = self.register(**self.professional_details(profession_title="Wizard"))
        self.assertIn('id="profession_title-error"', self.text(response))
        self.assertEqual(self.store._users, {})

    def test_professional_fields_sent_by_a_general_user_are_ignored(self):
        self.register(profession_title="Nephrologist", institution="Hospital", license_number="X1")
        user = self.store.find_by_email("ana@example.com")
        self.assertEqual((user["role"], user["profession_title"], user["institution"]), ("general", None, None))

    def test_a_signed_in_person_is_sent_home_instead_of_seeing_the_forms(self):
        browser = self.signed_in()
        for page in ("/register", "/login"):
            response = browser.get(page)
            self.assertEqual(response.status_code, 302, page)
            self.assertTrue(response.headers["Location"].endswith("/dashboard"), page)


class LoginTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.register(self.new_browser())                          # Ana exists; self.client is a signed-out visitor
        self.register(self.new_browser(), **self.professional_details())

    def test_the_right_email_and_password_sign_a_person_in_and_record_it(self):
        response = self.login()
        self.assertTrue(response.headers["Location"].endswith("/dashboard"))
        self.assertEqual(self.client.get("/dashboard").status_code, 200)
        self.assertIsNotNone(self.store.find_by_email("ana@example.com")["last_login_at"])

    def test_each_role_lands_on_its_own_home_page(self):
        self.assertTrue(self.login().headers["Location"].endswith("/dashboard"))
        professional = self.new_browser()
        self.assertTrue(self.login(professional, email="dr.cruz@example.com").headers["Location"].endswith("/professional"))

    def test_email_letter_case_and_surrounding_spaces_do_not_matter(self):
        self.assertEqual(self.login(email="  ANA@example.COM ").status_code, 302)

    def test_a_wrong_password_and_an_unknown_email_look_exactly_the_same(self):
        wrong_password = self.login(password="not-her-password")
        unknown_email = self.login(email="nobody@example.com")
        self.assertEqual(wrong_password.status_code, unknown_email.status_code)
        message = re.compile(r'<div class="alert-text">(.*?)</div>', re.S)
        self.assertEqual(message.search(self.text(wrong_password)).group(1), message.search(self.text(unknown_email)).group(1))
        self.assertIn("Check your email address and password", self.text(wrong_password))

    def test_empty_fields_get_field_messages(self):
        page = self.text(self.login(email="", password=""))
        self.assertIn('id="email-error"', page)
        self.assertIn('id="password-error"', page)

    def test_the_session_cookie_cannot_be_read_by_scripts(self):
        cookie = self.login().headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)

    def test_signing_in_throws_away_whatever_was_in_the_old_session(self):
        with self.client.session_transaction() as old:
            old["left_by_someone_else"] = "yes"
        before = self.csrf()
        self.login()
        with self.client.session_transaction() as new:
            self.assertNotIn("left_by_someone_else", new)
            self.assertNotEqual(new.get("csrf_token"), before)
            self.assertIn("user_id", new)

    def test_after_signing_in_the_person_goes_to_the_page_they_wanted(self):
        self.assertTrue(self.client.get("/account").headers["Location"].endswith("/login?next=/account"))
        response = self.login(next="/account")
        self.assertTrue(response.headers["Location"].endswith("/account"))

    def test_a_next_address_that_leaves_the_site_is_ignored(self):
        for evil in ("https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)"):
            browser = self.new_browser()
            response = self.login(browser, next=evil)
            self.assertTrue(response.headers["Location"].endswith("/dashboard"), evil)


class LockoutTests(AppTestCase):
    def setUp(self):
        super().setUp()
        with at(T0):
            self.register(self.new_browser())

    def fail(self, times, email="ana@example.com"):
        for _ in range(times):
            self.login(email=email, password="wrong-guess-xx")

    def test_five_wrong_passwords_pause_signing_in_even_with_the_right_password(self):
        with at(T0):
            self.fail(5)
            response = self.login()
        self.assertEqual(response.status_code, 429)
        self.assertIn("Too many attempts", self.text(response))
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)

    def test_four_wrong_passwords_do_not_lock_anyone_out(self):
        with at(T0):
            self.fail(4)
            self.assertEqual(self.login().status_code, 302)

    def test_the_lock_ends_by_itself(self):
        with at(T0):
            self.fail(5)
        with at(T0 + timedelta(minutes=14)):
            self.assertEqual(self.login().status_code, 429)
        with at(T0 + timedelta(minutes=16)):
            self.assertEqual(self.login().status_code, 302)

    def test_an_email_with_no_account_is_locked_in_exactly_the_same_way(self):
        with at(T0):
            self.fail(5, email="ghost@example.com")
            ghost = self.login(email="ghost@example.com", password="anything-at-all")
        self.assertEqual(ghost.status_code, 429)                   # so the lock reveals nothing about which emails exist

    def test_one_person_being_locked_does_not_lock_another(self):
        with at(T0):
            self.register(self.new_browser(), email="ben@example.com", full_name="Ben Lim")
            self.fail(5)
            self.assertEqual(self.login(self.new_browser(), email="ben@example.com").status_code, 302)

    def test_a_good_sign_in_wipes_the_earlier_failures(self):
        with at(T0):
            self.fail(4)
            self.login(self.new_browser())
            self.fail(4)                                           # counts from zero again
            self.assertEqual(self.login(self.new_browser()).status_code, 302)


class LogoutAndCsrfTests(AppTestCase):
    def test_signing_out_ends_the_session(self):
        browser = self.signed_in()
        response = self.post("/logout", client=browser, token_from="/account")
        self.assertTrue(response.headers["Location"].endswith("/login"))
        self.assertIn("signed out", self.text(browser.get("/login")))
        self.assertTrue(browser.get("/dashboard").headers["Location"].startswith("/login"))

    def test_signing_out_is_not_possible_with_a_plain_link(self):
        browser = self.signed_in()
        self.assertEqual(browser.get("/logout").status_code, 405)
        self.assertEqual(browser.get("/dashboard").status_code, 200)

    def test_a_form_without_the_secret_token_is_refused(self):
        self.register(self.new_browser())
        for path, data in (("/login", {"email": "ana@example.com", "password": PASSWORD}),
                           ("/register", {"role": "general", "full_name": "B B", "email": "b@example.com", "password": PASSWORD})):
            response = self.post(path, data, token=None)
            self.assertEqual(response.status_code, 400, path)
            self.assertIn("expired", self.text(response))
        self.assertEqual(len(self.store._users), 1)

    def test_a_wrong_token_is_refused_and_a_signed_in_person_stays_signed_in(self):
        browser = self.signed_in()
        self.assertEqual(self.post("/logout", client=browser, token="forged-token").status_code, 400)
        self.assertEqual(self.post("/account/password", {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
                                   client=browser, token="forged-token").status_code, 400)
        self.assertEqual(browser.get("/dashboard").status_code, 200)
        self.assertIsNotNone(self.store.find_by_email("ana@example.com")["last_login_at"])
        self.assertIsNone(self.store.find_by_email("ana@example.com")["password_changed_at"])

    def test_a_token_from_one_browser_does_not_work_in_another(self):
        one, two = self.new_browser(), self.new_browser()
        stolen = self.csrf(one)
        response = self.post("/login", {"email": "a@example.com", "password": "x"}, client=two, token=stolen)
        self.assertEqual(response.status_code, 400)

    def test_the_right_error_is_given_for_a_missing_page_or_a_wrong_method(self):
        self.assertEqual(self.client.post("/no-such-page", data={}).status_code, 404)       # not "expired"
        self.assertEqual(self.client.post("/about", data={}).status_code, 405)

    def test_reading_pages_needs_no_token(self):
        self.assertEqual(self.client.get("/login").status_code, 200)
        self.assertEqual(self.client.get("/about").status_code, 200)


class AccessControlTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.general = self.signed_in()
        self.professional = self.signed_in(**self.professional_details())

    def test_a_visitor_who_is_not_signed_in_is_sent_to_sign_in(self):
        for path in ("/dashboard", "/professional", "/account"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302, path)
            self.assertIn("/login?next=" + path, response.headers["Location"])

    def test_each_role_can_open_its_own_home_and_not_the_others(self):
        self.assertEqual(self.general.get("/dashboard").status_code, 200)
        self.assertEqual(self.professional.get("/professional").status_code, 200)
        wrong_for_general = self.general.get("/professional")
        wrong_for_professional = self.professional.get("/dashboard")
        for response in (wrong_for_general, wrong_for_professional):
            self.assertEqual(response.status_code, 403)
            self.assertIn("Access not allowed", self.text(response))

    def test_both_roles_can_open_their_own_account_page_and_only_see_their_own_details(self):
        general_page = self.text(self.general.get("/account"))
        professional_page = self.text(self.professional.get("/account"))
        self.assertIn("ana@example.com", general_page)
        self.assertNotIn("dr.cruz@example.com", general_page)
        self.assertIn("dr.cruz@example.com", professional_page)
        self.assertNotIn("ana@example.com", professional_page)

    def test_the_role_is_read_from_the_database_every_time(self):
        user = self.store.find_by_email("ana@example.com")
        self.store._users[user["user_id"]]["role"] = "professional"       # changed behind the browser's back
        self.assertEqual(self.general.get("/dashboard").status_code, 403)
        self.assertEqual(self.general.get("/professional").status_code, 200)

    def test_a_session_for_an_account_that_no_longer_exists_is_ended(self):
        self.store._users.clear()
        response = self.general.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        with self.general.session_transaction() as session:
            self.assertNotIn("user_id", session)

    def test_a_forged_user_number_in_a_cookie_is_useless_without_the_server_secret(self):
        # The cookie is signed with SECRET_KEY, so editing it makes it invalid and the visitor stays signed out.
        cookie = self.general.get_cookie("session")
        forged = self.new_browser()
        forged.set_cookie("session", cookie.value[:-3] + "abc")
        self.assertEqual(forged.get("/dashboard").status_code, 302)

    def test_the_navigation_shows_the_right_things_for_each_state(self):
        visitor = self.text(self.client.get("/"))
        self.assertIn("Create account", visitor)
        self.assertNotIn("Sign out", visitor)
        member = self.text(self.general.get("/"))
        self.assertIn("Sign out", member)
        self.assertIn("My home", member)
        self.assertNotIn("Create account", member)

    def test_the_rail_shows_only_what_exists_and_says_so(self):
        page = self.text(self.general.get("/dashboard"))
        self.assertIn('aria-current="page"', page)
        self.assertIn("Coming soon", page)                          # unbuilt items are honestly unavailable
        self.assertNotIn('data-preview-link', page)                 # and nothing pretends to work
        self.assertIn("Notifications", page)                        # the bell is real now (services/notifications.py)
        professional_rail = self.text(self.professional.get("/professional"))
        self.assertIn("Shared assessments", professional_rail)
        self.assertNotIn('href="/screening"', professional_rail)   # a professional does not screen THEMSELVES here - "New assessment" now means assessing a patient


class AccountTests(AppTestCase):
    def test_changing_the_password_signs_out_other_devices_but_not_this_one(self):
        with at(T0):
            laptop = self.signed_in()
            phone = self.new_browser()
            self.login(phone)
        with at(T0 + timedelta(minutes=5)):
            response = self.post("/account/password", {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
                                 client=laptop, token_from="/account")
            self.assertEqual(response.status_code, 302)
            self.assertEqual(laptop.get("/account").status_code, 200)         # this device stays signed in
            self.assertEqual(phone.get("/account").status_code, 302)          # the other one is signed out
            self.assertEqual(self.login(self.new_browser(), password=PASSWORD).status_code, 200)       # the old password no longer works
            self.assertEqual(self.login(self.new_browser(), password=NEW_PASSWORD).status_code, 302)   # the new one does

    def test_a_wrong_current_password_changes_nothing(self):
        browser = self.signed_in()
        before = self.store.find_by_email("ana@example.com")["password_hash"]
        response = self.post("/account/password", {"current_password": "not-mine-at-all", "new_password": NEW_PASSWORD},
                             client=browser, token_from="/account")
        self.assertEqual(response.status_code, 200)
        self.assertIn("not your current password", self.text(response))
        self.assertEqual(self.store.find_by_email("ana@example.com")["password_hash"], before)

    def test_a_weak_or_unchanged_new_password_is_refused(self):
        browser = self.signed_in()
        for new in ("short", "password123", PASSWORD, ""):
            response = self.post("/account/password", {"current_password": PASSWORD, "new_password": new},
                                 client=browser, token_from="/account")
            self.assertEqual(response.status_code, 200, new)
            self.assertIn('id="new_password-error"', self.text(response), new)

    def test_guessing_the_current_password_is_limited_like_signing_in(self):
        with at(T0):
            browser = self.signed_in()
            for _ in range(5):
                self.post("/account/password", {"current_password": "guess-guess-1", "new_password": NEW_PASSWORD},
                          client=browser, token_from="/account")
            response = self.post("/account/password", {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
                                 client=browser, token_from="/account")
        self.assertIn("Too many wrong attempts", self.text(response))
        self.assertIsNone(self.store.find_by_email("ana@example.com")["password_changed_at"])

    def test_the_password_hash_never_reaches_a_page(self):
        browser = self.signed_in()
        stored = self.store.find_by_email("ana@example.com")["password_hash"]
        for path in ("/dashboard", "/account"):
            page = self.text(browser.get(path))
            self.assertNotIn(stored, page)
            self.assertNotIn("password_hash", page)


class ResetPasswordTests(AppTestCase):
    """reset_password.py lets whoever runs the server unlock an account. No web page can do this."""

    def test_the_operator_can_set_a_new_password_unlock_the_account_and_end_old_sessions(self):
        from services import auth_service
        with at(T0):
            phone = self.signed_in()
            for _ in range(5):
                self.login(self.new_browser(), password="wrong-guess-xx")
        with at(T0 + timedelta(minutes=1)):
            self.assertEqual(self.login(self.new_browser()).status_code, 429)                 # locked
            self.assertTrue(auth_service.reset_password(self.store, "ana@example.com", NEW_PASSWORD, clock_now()))
        with at(T0 + timedelta(minutes=2)):
            self.assertEqual(self.login(self.new_browser(), password=NEW_PASSWORD).status_code, 302)   # unlocked, new password works
            self.assertEqual(phone.get("/dashboard").status_code, 302)                               # the old session is gone

    def test_an_unknown_account_is_reported_not_created(self):
        from services import auth_service
        self.assertFalse(auth_service.reset_password(self.store, "ghost@example.com", NEW_PASSWORD, T0))
        self.assertEqual(self.store._users, {})

    def test_there_is_no_web_route_for_it(self):
        for path in ("/reset-password", "/reset_password", "/forgot-password"):
            self.assertEqual(self.client.get(path).status_code, 404, path)


def clock_now():
    from services import clock
    return clock.now_utc()


class HeadersAndCacheTests(AppTestCase):
    def test_private_pages_may_not_be_stored_by_the_browser(self):
        browser = self.signed_in()
        for path in ("/dashboard", "/account", "/login"):
            self.assertIn("no-store", browser.get(path).headers.get("Cache-Control", ""), path)
        self.assertIn("no-store", self.client.get("/login").headers.get("Cache-Control", ""))

    def test_public_pages_are_not_marked_private(self):
        self.assertNotIn("no-store", self.client.get("/about").headers.get("Cache-Control", ""))


class PageQualityTests(AppTestCase):
    def test_no_page_uses_a_variable_that_was_never_passed_to_it(self):
        """Signed-out, general and professional views, and every error state of the forms."""
        self.app.jinja_env.undefined = StrictUndefined
        member, doctor = self.signed_in(), self.signed_in(**self.professional_details())
        for path in ("/", "/about", "/login", "/register", "/login?next=/account", "/nowhere"):
            self.assertIn(self.client.get(path).status_code, (200, 404), path)
        for path in ("/dashboard", "/account"):
            self.assertEqual(member.get(path).status_code, 200, path)
        self.assertEqual(member.get("/professional").status_code, 403)
        for path in ("/professional", "/account"):
            self.assertEqual(doctor.get(path).status_code, 200, path)
        self.assertEqual(self.register(self.new_browser(), email="bad").status_code, 200)
        self.assertEqual(self.register(self.new_browser(), **self.professional_details(email="x@example.com", profession_title="")).status_code, 200)
        self.assertEqual(self.login(email="", password="").status_code, 200)
        self.assertEqual(self.login(email="zz@example.com", password="nope-nope-no").status_code, 200)
        self.assertEqual(self.post("/account/password", {"current_password": "", "new_password": ""}, client=member, token_from="/account").status_code, 200)

    def test_every_field_has_a_label_and_the_forms_are_wired_correctly(self):
        member = self.signed_in()
        for client, path in ((self.client, "/login"), (self.client, "/register"), (member, "/account")):
            checker = FormChecker()
            checker.feed(self.text(client.get(path)))
            self.assertEqual(checker.unlabelled, [], f"{path}: fields without a label")
            self.assertEqual(checker.duplicate_ids, [], f"{path}: repeated ids")
            self.assertTrue(checker.forms, path)
            for method, has_token in checker.forms:
                self.assertEqual(method, "post", path)
                self.assertTrue(has_token, f"{path}: a form has no CSRF token")

    def test_password_fields_tell_the_browser_what_they_are(self):
        member = self.signed_in()
        self.assertIn('autocomplete="current-password"', self.text(self.client.get("/login")))
        self.assertIn('autocomplete="new-password"', self.text(self.client.get("/register")))
        page = self.text(member.get("/account"))
        self.assertIn('autocomplete="current-password"', page)
        self.assertIn('autocomplete="new-password"', page)

    def test_the_pages_do_not_claim_to_diagnose(self):
        member = self.signed_in()
        for page in (self.text(member.get("/dashboard")), self.text(self.client.get("/register"))):
            for phrase in ("you have ckd", "confirms kidney disease", "confidence score"):
                self.assertNotIn(phrase, page.lower())

    def test_the_home_page_of_a_new_account_shows_no_invented_numbers(self):
        page = self.text(self.signed_in().get("/dashboard"))
        self.assertIn("No assessments yet", page)
        self.assertNotIn("Preliminary Risk", page)
        self.assertNotIn('class="chart-line"', page)
        self.assertNotIn("sample-tag", page)


class FormChecker(HTMLParser):
    """Finds fields with no <label for>, repeated ids, and forms without a CSRF token."""

    def __init__(self):
        super().__init__()
        self.label_for, self.fields, self.ids, self.forms = set(), [], [], []
        self._form = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.append(a["id"])
        if tag == "label" and a.get("for"):
            self.label_for.add(a["for"])
        if tag == "form":
            self._form = [a.get("method", "get").lower(), False]
            self.forms.append(self._form)
        if tag in ("input", "select", "textarea"):
            if a.get("type") == "hidden":
                if a.get("name") == "csrf_token" and self._form:
                    self._form[1] = True
            elif a.get("type") not in ("radio", "button", "submit"):
                self.fields.append(a.get("id"))

    def handle_endtag(self, tag):
        if tag == "form":
            self._form = None

    @property
    def unlabelled(self):
        return [field for field in self.fields if field not in self.label_for]

    @property
    def duplicate_ids(self):
        return sorted({i for i in self.ids if self.ids.count(i) > 1})

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


class BrokenStore(MemoryUserStore):
    """A store whose database is down."""

    def find_by_id(self, user_id):
        raise mysql.connector.OperationalError("SELECT secret FROM hidden failed")

    def find_by_email(self, email):
        raise mysql.connector.OperationalError("SELECT secret FROM hidden failed")


class DatabaseDownTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(user_store=BrokenStore())
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = 1
            session["issued_at"] = T0.isoformat()

    def test_public_pages_still_work_when_the_database_is_down(self):
        for path in ("/", "/about", "/login", "/register"):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_a_private_page_says_the_service_is_unavailable_instead_of_guessing(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 503)
        self.assertIn("temporarily unavailable", response.get_data(as_text=True))

    def test_signing_in_shows_the_friendly_page_and_never_the_technical_detail(self):
        with self.client.session_transaction() as session:
            session.clear()
        token = re.search(r'name="csrf_token" value="([^"]+)"', self.client.get("/login").get_data(as_text=True)).group(1)
        response = self.client.post("/login", data={"email": "a@example.com", "password": PASSWORD, "csrf_token": token})
        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret", page)
        self.assertNotIn("SELECT", page)


class DesignPreviewIsolationTests(AppTestCase):
    debug = True

    def test_design_previews_keep_showing_a_made_up_person_even_when_someone_is_signed_in(self):
        browser = self.signed_in(full_name="Real Person")
        page = self.text(browser.get("/design/dashboard"))
        self.assertIn("Sample User", page)
        self.assertNotIn("Real Person", page)
        self.assertIn("data-preview-link", page)                    # previews keep their own behaviour
        real = self.text(browser.get("/dashboard"))
        self.assertIn("Real", real)
        self.assertNotIn("Sample User", real)


if __name__ == "__main__":
    unittest.main()
