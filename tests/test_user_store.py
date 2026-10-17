"""
Checks for services/user_store.py. The SAME checks run against two stores:

  * MemoryUserStore  - always runs.
  * MySQLUserStore   - runs against a separate database called <DB_NAME>_test (for example nephron_test) that this
                       file creates, fills using the real migration files, and DELETES again at the end.
                       Your real database is never touched. If MySQL is not running, or the MySQL user is not
                       allowed to create databases, these tests are skipped and say why.

Running the MySQL part is how you know the SQL and the migration files really work on YOUR MySQL:
    python -m unittest tests.test_user_store -v
"""
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mysql_support  # noqa: E402

import mysql.connector  # noqa: E402

from services.user_store import DuplicateEmailError, DuplicateUsernameError, MemoryUserStore, MySQLUserStore  # noqa: E402

NOW = datetime(2026, 9, 20, 10, 0, 0)
def setUpModule():
    mysql_support.prepare()


def tearDownModule():
    mysql_support.drop()


def new_email():
    return f"{uuid.uuid4().hex[:10]}@example.com"


def general(email=None, name="Ana Reyes"):
    return {"email": email or new_email(), "full_name": name, "role": "general", "professional": None}


def professional(email=None, name="Dr. Luis Cruz"):
    return {"email": email or new_email(), "full_name": name, "role": "professional",
            "professional": {"profession_title": "Nephrologist", "institution": "City Hospital", "license_number": "PRC-1"}}


class UserStoreContract:
    """The checks every user store must pass. A subclass says how to make a store."""

    def make_store(self):
        raise NotImplementedError

    def setUp(self):
        self.store = self.make_store()

    def test_a_general_user_can_be_saved_and_found_by_email_and_by_number(self):
        values = general()
        user_id = self.store.create_user(values, "hash-1", NOW)
        for user in (self.store.find_by_email(values["email"]), self.store.find_by_id(user_id)):
            self.assertEqual(user["user_id"], user_id)
            self.assertEqual((user["email"], user["full_name"], user["role"], user["password_hash"]),
                             (values["email"], "Ana Reyes", "general", "hash-1"))
            self.assertEqual(user["created_at"], NOW)
            self.assertIsNone(user["last_login_at"])
            self.assertIsNone(user["password_changed_at"])
            self.assertEqual((user["profession_title"], user["institution"], user["license_number"]), (None, None, None))

    def test_a_professional_is_saved_together_with_their_details(self):
        values = professional()
        user_id = self.store.create_user(values, "hash-2", NOW)
        user = self.store.find_by_id(user_id)
        self.assertEqual(user["role"], "professional")
        self.assertEqual((user["profession_title"], user["institution"], user["license_number"]),
                         ("Nephrologist", "City Hospital", "PRC-1"))

    def test_optional_professional_details_may_be_empty(self):
        values = professional()
        values["professional"] = {"profession_title": "Nurse", "institution": None, "license_number": None}
        user = self.store.find_by_id(self.store.create_user(values, "h", NOW))
        self.assertEqual((user["profession_title"], user["institution"], user["license_number"]), ("Nurse", None, None))

    def test_the_same_email_cannot_be_saved_twice_whatever_the_letter_case(self):
        email = new_email()
        self.store.create_user(general(email), "h", NOW)
        for again in (email, email.upper()):
            with self.assertRaises(DuplicateEmailError):
                self.store.create_user(general(again, "Someone Else"), "h", NOW)

    def test_finding_someone_who_does_not_exist_gives_nothing(self):
        self.assertIsNone(self.store.find_by_email("nobody-" + new_email()))
        self.assertIsNone(self.store.find_by_id(987654321))

    def test_signing_in_and_changing_a_password_are_recorded(self):
        user_id = self.store.create_user(general(), "old-hash", NOW)
        later = NOW + timedelta(hours=2)
        self.store.mark_login(user_id, later)
        self.store.update_password(user_id, "new-hash", later)
        user = self.store.find_by_id(user_id)
        self.assertEqual((user["last_login_at"], user["password_changed_at"], user["password_hash"]), (later, later, "new-hash"))

    def test_failed_attempts_are_counted_only_inside_the_window_and_only_for_that_email(self):
        email, other = new_email(), new_email()
        self.store.record_login_attempt(email, "10.0.0.1", False, NOW - timedelta(minutes=30))   # too old
        self.store.record_login_attempt(email, "10.0.0.1", False, NOW - timedelta(minutes=5))
        self.store.record_login_attempt(email, None, False, NOW - timedelta(minutes=1))
        self.store.record_login_attempt(email, "10.0.0.1", True, NOW - timedelta(minutes=2))     # successes never count
        self.store.record_login_attempt(other, "10.0.0.1", False, NOW - timedelta(minutes=1))
        self.assertEqual(self.store.count_failed_attempts(email, NOW - timedelta(minutes=15)), 2)
        self.assertEqual(self.store.count_failed_attempts(other, NOW - timedelta(minutes=15)), 1)
        self.assertEqual(self.store.count_failed_attempts(new_email(), NOW - timedelta(minutes=15)), 0)

    def test_clearing_failures_affects_only_that_email(self):
        email, other = new_email(), new_email()
        for who in (email, other):
            self.store.record_login_attempt(who, None, False, NOW)
        self.store.clear_failed_attempts(email)
        self.assertEqual(self.store.count_failed_attempts(email, NOW - timedelta(minutes=1)), 0)
        self.assertEqual(self.store.count_failed_attempts(other, NOW - timedelta(minutes=1)), 1)

    def test_old_attempts_can_be_deleted_and_new_ones_stay(self):
        email = new_email()
        self.store.record_login_attempt(email, None, False, NOW - timedelta(days=40))
        self.store.record_login_attempt(email, None, False, NOW - timedelta(days=1))
        self.store.delete_old_login_attempts(NOW - timedelta(days=30))
        self.assertEqual(self.store.count_failed_attempts(email, NOW - timedelta(days=100)), 1)

    # ---- new profile fields (Phase 9 refinement) ----
    def test_username_date_of_birth_address_and_avatar_are_saved_and_read_back(self):
        from datetime import date
        values = general()
        values.update({"username": "ana_r", "date_of_birth": date(1990, 5, 14), "address": "123 Main St", "avatar": "avatar-2"})
        user_id = self.store.create_user(values, "h", NOW)
        found = self.store.find_by_id(user_id)
        self.assertEqual(found["username"], "ana_r")
        self.assertEqual(found["date_of_birth"], date(1990, 5, 14))
        self.assertEqual(found["address"], "123 Main St")
        self.assertEqual(found["avatar"], "avatar-2")

    def test_address_and_avatar_are_optional(self):
        values = general(); values["username"] = f"user{uuid.uuid4().hex[:8]}"
        user_id = self.store.create_user(values, "h", NOW)
        found = self.store.find_by_id(user_id)
        self.assertIsNone(found["address"])
        self.assertIsNone(found["avatar"])

    def test_the_same_username_cannot_be_saved_twice_whatever_the_letter_case(self):
        base = f"user{uuid.uuid4().hex[:8]}"
        values = general(email=new_email()); values["username"] = base
        self.store.create_user(values, "h", NOW)
        with self.assertRaises(DuplicateUsernameError):
            self.store.create_user(general(email=new_email(), name="Other")|{"username": base.upper()}, "h", NOW)

    def test_find_by_username_finds_the_account_case_insensitively(self):
        base = f"user{uuid.uuid4().hex[:8]}"
        values = general(); values["username"] = base
        user_id = self.store.create_user(values, "h", NOW)
        found = self.store.find_by_username(base.upper())
        self.assertIsNotNone(found)
        self.assertEqual(found["user_id"], user_id)

    def test_find_by_username_with_no_match_is_none(self):
        self.assertIsNone(self.store.find_by_username("no-such-user-xyz"))

    # ---- search_professionals ----
    # Each test below uses its OWN never-reused surname (a fresh uuid fragment): the MySQL contract runs against a
    # single shared database across every test method in the file (see tests/mysql_support.py), so a name reused
    # across tests would collide with rows an earlier test already inserted and never removes.
    def test_search_finds_a_professional_by_partial_name_case_insensitively(self):
        surname = f"Cruz{uuid.uuid4().hex[:8]}"
        self.store.create_user(professional(name=f"Dr. Maria {surname}"), "h", NOW)
        self.assertEqual([u["full_name"] for u in self.store.search_professionals(surname)], [f"Dr. Maria {surname}"])
        self.assertEqual([u["full_name"] for u in self.store.search_professionals(surname.upper())], [f"Dr. Maria {surname}"])

    def test_search_finds_a_professional_by_their_exact_email(self):
        values = professional(name=f"Dr. Jose {uuid.uuid4().hex[:8]}")
        self.store.create_user(values, "h", NOW)
        self.assertEqual([u["full_name"] for u in self.store.search_professionals(values["email"])], [values["full_name"]])

    def test_search_never_returns_a_general_account(self):
        surname = f"Cruz{uuid.uuid4().hex[:8]}"
        values = general(name=f"Ana {surname}")
        self.store.create_user(values, "h", NOW)
        self.assertEqual(self.store.search_professionals(surname), [])
        self.assertEqual(self.store.search_professionals(values["email"]), [])

    def test_search_returns_every_match_sorted_by_name(self):
        surname = f"Cruz{uuid.uuid4().hex[:8]}"
        self.store.create_user(professional(name=f"Dr. Zed {surname}"), "h", NOW)
        self.store.create_user(professional(name=f"Dr. Ana {surname}"), "h", NOW)
        self.assertEqual([u["full_name"] for u in self.store.search_professionals(surname)], [f"Dr. Ana {surname}", f"Dr. Zed {surname}"])

    def test_search_with_a_blank_term_finds_nothing(self):
        self.store.create_user(professional(name=f"Dr. {uuid.uuid4().hex[:8]}"), "h", NOW)
        self.assertEqual(self.store.search_professionals(""), [])
        self.assertEqual(self.store.search_professionals("   "), [])

    def test_a_percent_in_the_search_term_still_finds_the_exact_name_it_is_part_of(self):
        # % is SQL's own wildcard, so this also matches a little more broadly than the exact text (see
        # search_professionals's own docstring for why that trade-off is fine) - what matters here is that a name
        # that genuinely contains a % is still found by a search that includes it, on both stores alike.
        surname = f"Cruz{uuid.uuid4().hex[:8]}"
        self.store.create_user(professional(name=f"Dr. 100% {surname}"), "h", NOW)
        self.assertIn(f"Dr. 100% {surname}", [u["full_name"] for u in self.store.search_professionals(f"100% {surname}")])


class MemoryStoreTests(UserStoreContract, unittest.TestCase):
    def make_store(self):
        return MemoryUserStore()


class MySQLStoreTests(UserStoreContract, unittest.TestCase):
    def make_store(self):
        if mysql_support.problem:
            self.skipTest(mysql_support.problem)
        mysql_support.push_app_context(self)
        return MySQLUserStore()

    # ---- checks that only make sense for a real database ----
    def test_a_failed_professional_insert_leaves_no_user_behind(self):
        values = professional()
        values["professional"]["profession_title"] = None            # violates NOT NULL in the second table
        with self.assertRaises(mysql.connector.Error):
            self.store.create_user(values, "h", NOW)
        self.assertIsNone(self.store.find_by_email(values["email"]))   # the first insert was undone as well

    def test_the_database_itself_refuses_details_for_a_user_that_does_not_exist(self):
        from db import execute
        with self.assertRaises(mysql.connector.IntegrityError):
            execute("INSERT INTO professionals (user_id, profession_title) VALUES (%s, %s)", (987654321, "Nurse"))

    def test_deleting_a_user_deletes_their_professional_details(self):
        from db import execute, query_one
        user_id = self.store.create_user(professional(), "h", NOW)
        execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        self.assertEqual(query_one("SELECT COUNT(*) AS n FROM professionals WHERE user_id = %s", (user_id,))["n"], 0)

    def test_running_the_migrations_again_changes_nothing(self):
        mysql_support.rerun_migrations()
        user_id = self.store.create_user(general(), "h", NOW)
        self.assertIsNotNone(self.store.find_by_id(user_id))


if __name__ == "__main__":
    unittest.main()
