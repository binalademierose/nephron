"""
Checks for services/assessment_store.py. The SAME checks run against two stores:
  * MemoryAssessmentStore - always runs.
  * MySQLAssessmentStore  - runs on the separate <DB_NAME>_test database (see tests/mysql_support.py).
                            Skipped, with the reason, if MySQL is not available.
"""
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mysql_support  # noqa: E402

import mysql.connector  # noqa: E402

from services.assessment_store import MemoryAssessmentStore, MySQLAssessmentStore, UnknownUserError  # noqa: E402
from services.user_store import MemoryUserStore, MySQLUserStore  # noqa: E402

NOW = datetime(2026, 9, 20, 10, 0, 0)


def setUpModule():
    mysql_support.prepare()


def tearDownModule():
    mysql_support.drop()


def new_user(users, name="Ana Reyes"):
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    return users.create_user({"email": email, "full_name": name, "role": "general", "professional": None}, "h", NOW)


def result(**changes):
    values = {"assessment_type": "preliminary", "probability": 0.31, "classification": "high", "threshold_used": 0.21,
              "model_version": "xgboost-test", "assessed_at": NOW}
    values.update(changes)
    return values


class AssessmentStoreContract:
    def make_stores(self):
        """Return (user store, assessment store)."""
        raise NotImplementedError

    def setUp(self):
        self.users, self.store = self.make_stores()
        self.user_id = new_user(self.users)

    def test_a_saved_assessment_comes_back_with_every_field(self):
        assessment_id = self.store.add_assessment(self.user_id, result())
        (row,) = self.store.list_assessments(self.user_id)
        self.assertEqual(row["assessment_id"], assessment_id)
        self.assertEqual((row["assessment_type"], row["classification"], row["model_version"], row["assessed_at"]),
                         ("preliminary", "high", "xgboost-test", NOW))
        self.assertAlmostEqual(row["probability"], 0.31, places=6)
        self.assertAlmostEqual(row["threshold_used"], 0.21, places=6)
        self.assertIsInstance(row["probability"], float)                 # never a Decimal

    def test_find_owner_returns_the_right_user_id_without_needing_it_first(self):
        assessment_id = self.store.add_assessment(self.user_id, result())
        self.assertEqual(self.store.find_owner(assessment_id), self.user_id)

    def test_find_owner_of_an_unknown_id_is_none(self):
        self.assertIsNone(self.store.find_owner(999999))

    def test_threshold_and_model_are_optional(self):
        self.store.add_assessment(self.user_id, result(threshold_used=None, model_version=None))
        (row,) = self.store.list_assessments(self.user_id)
        self.assertIsNone(row["threshold_used"])
        self.assertIsNone(row["model_version"])

    def test_numbers_are_kept_to_six_decimals_the_same_way_in_every_store(self):
        self.store.add_assessment(self.user_id, result(probability=0.1234567, threshold_used=0.7934912))
        (row,) = self.store.list_assessments(self.user_id)
        self.assertAlmostEqual(row["probability"], 0.123457, places=6)
        self.assertAlmostEqual(row["threshold_used"], 0.793491, places=6)

    def test_newest_first_and_a_reassessment_never_replaces_an_earlier_one(self):
        first = self.store.add_assessment(self.user_id, result(assessed_at=NOW - timedelta(days=40), probability=0.10, classification="low"))
        second = self.store.add_assessment(self.user_id, result(assessed_at=NOW, probability=0.35))
        rows = self.store.list_assessments(self.user_id)
        self.assertEqual([r["assessment_id"] for r in rows], [second, first])
        self.assertEqual(len(rows), 2)

    def test_two_results_at_the_same_moment_keep_a_stable_order(self):
        a = self.store.add_assessment(self.user_id, result())
        b = self.store.add_assessment(self.user_id, result())
        self.assertEqual([r["assessment_id"] for r in self.store.list_assessments(self.user_id)], [b, a])

    def test_one_person_never_sees_another_persons_assessments(self):
        other = new_user(self.users, "Ben Lim")
        self.store.add_assessment(self.user_id, result(probability=0.31))
        self.store.add_assessment(other, result(probability=0.05, classification="low"))
        self.assertEqual([round(r["probability"], 2) for r in self.store.list_assessments(self.user_id)], [0.31])
        self.assertEqual([round(r["probability"], 2) for r in self.store.list_assessments(other)], [0.05])
        self.assertEqual(self.store.list_assessments(987654321), [])

    def test_the_answers_behind_an_assessment_are_saved_with_it_and_read_back_exactly(self):
        inputs = {"Age": 48, "Sex": "Female", "BMI": 27.4, "height_cm": 160.0, "weight_kg": 70.1, "Diabetes": 1, "Alcohol_Consumption": "None"}
        assessment_id = self.store.add_assessment(self.user_id, result(), inputs)
        saved = self.store.get_assessment(self.user_id, assessment_id)
        self.assertEqual(saved["inputs"], inputs)
        self.assertEqual(saved["assessment_id"], assessment_id)
        self.assertAlmostEqual(saved["probability"], 0.31, places=6)
        self.assertEqual(saved["model_version"], "xgboost-test")

    def test_an_assessment_saved_without_answers_has_none(self):
        assessment_id = self.store.add_assessment(self.user_id, result())
        self.assertIsNone(self.store.get_assessment(self.user_id, assessment_id)["inputs"])

    def test_nobody_can_open_another_persons_assessment_or_answers(self):
        other = new_user(self.users, "Ben Lim")
        mine = self.store.add_assessment(self.user_id, result(), {"Age": 48})
        self.assertIsNone(self.store.get_assessment(other, mine))                  # as if it did not exist
        self.assertIsNone(self.store.get_assessment(self.user_id, 987654321))
        self.assertIsNotNone(self.store.get_assessment(self.user_id, mine))

    def test_the_list_does_not_carry_the_answers(self):
        self.store.add_assessment(self.user_id, result(), {"Age": 48})
        self.assertNotIn("inputs", self.store.list_assessments(self.user_id)[0])

    def test_source_assessment_id_is_saved_and_read_back(self):
        earlier = self.store.add_assessment(self.user_id, result())
        later = self.store.add_assessment(self.user_id, result(assessment_type="enhanced", source_assessment_id=earlier))
        rows = {row["assessment_id"]: row for row in self.store.list_assessments(self.user_id)}
        self.assertEqual(rows[later]["source_assessment_id"], earlier)
        self.assertIsNone(rows[earlier]["source_assessment_id"])
        self.assertEqual(self.store.get_assessment(self.user_id, later)["source_assessment_id"], earlier)

    def test_source_assessment_id_is_optional(self):
        assessment_id = self.store.add_assessment(self.user_id, result())
        self.assertIsNone(self.store.get_assessment(self.user_id, assessment_id)["source_assessment_id"])

    def test_an_assessment_for_a_user_that_does_not_exist_is_refused(self):
        with self.assertRaises(UnknownUserError):
            self.store.add_assessment(987654321, result())


class MemoryStoreTests(AssessmentStoreContract, unittest.TestCase):
    def make_stores(self):
        users = MemoryUserStore()
        return users, MemoryAssessmentStore(users)


class MySQLStoreTests(AssessmentStoreContract, unittest.TestCase):
    def make_stores(self):
        if mysql_support.problem:
            self.skipTest(mysql_support.problem)
        mysql_support.push_app_context(self)
        return MySQLUserStore(), MySQLAssessmentStore()

    # ---- checks that only make sense for a real database ----
    def test_the_database_itself_refuses_a_probability_outside_zero_to_one(self):
        from db import execute, query_one
        version = None
        try:
            version = query_one("SELECT VERSION() AS v")["v"]
        except mysql.connector.Error:
            pass                                                        # (the sandbox stand-in has no VERSION(); it enforces CHECK)
        if version and version[0].isdigit():
            numbers = tuple(int(part) for part in version.split("-")[0].split(".")[:3])
            if numbers < (8, 0, 16) and "MariaDB" not in version:
                self.skipTest(f"MySQL {version} does not enforce CHECK constraints (8.0.16 or newer does)")
        with self.assertRaises(mysql.connector.Error):
            execute("INSERT INTO assessments (user_id, assessment_type, probability, classification, assessed_at) "
                    "VALUES (%s, 'preliminary', 1.5, 'high', %s)", (self.user_id, NOW))

    def test_deleting_a_user_deletes_their_assessments_and_the_answers_behind_them(self):
        from db import execute, query_one
        assessment_id = self.store.add_assessment(self.user_id, result(), {"Age": 48})
        execute("DELETE FROM users WHERE user_id = %s", (self.user_id,))
        self.assertEqual(query_one("SELECT COUNT(*) AS n FROM assessments WHERE user_id = %s", (self.user_id,))["n"], 0)
        self.assertEqual(query_one("SELECT COUNT(*) AS n FROM assessment_inputs WHERE assessment_id = %s", (assessment_id,))["n"], 0)

    def test_a_snapshot_cannot_exist_for_an_assessment_that_does_not_exist(self):
        from db import execute
        with self.assertRaises(mysql.connector.IntegrityError):
            execute("INSERT INTO assessment_inputs (assessment_id, inputs) VALUES (%s, %s)", (987654321, "{}"))

    def test_deleting_the_source_assessment_sets_the_link_to_null_not_the_enhanced_result(self):
        # Meaningful only against a real MySQL server: the sandbox's SQLite stand-in cannot add a foreign key to an
        # existing table (see stubs/mysql/connector.py), so ON DELETE SET NULL is not actually enforced there -
        # skip rather than let that gap masquerade as a pass.
        from db import execute, query_one
        try:
            query_one("SELECT VERSION() AS v")
        except mysql.connector.Error:
            self.skipTest("the sandbox stand-in cannot add a foreign key to an existing table; this needs real MySQL")
        earlier = self.store.add_assessment(self.user_id, result())
        later = self.store.add_assessment(self.user_id, result(assessment_type="enhanced", source_assessment_id=earlier))
        execute("DELETE FROM assessments WHERE assessment_id = %s", (earlier,))
        still_there = query_one("SELECT assessment_id, source_assessment_id FROM assessments WHERE assessment_id = %s", (later,))
        self.assertIsNotNone(still_there, "the enhanced result must not be deleted when its source is")
        self.assertIsNone(still_there["source_assessment_id"])


if __name__ == "__main__":
    unittest.main()
