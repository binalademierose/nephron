"""
Checks for services/clinical_review_store.py. The SAME checks run against two stores:
  * MemoryClinicalReviewStore - always runs.
  * MySQLClinicalReviewStore  - runs on the separate <DB_NAME>_test database (see tests/mysql_support.py).
                                Skipped, with the reason, if MySQL is not available.
"""
import os
import sys
import unittest
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mysql_support  # noqa: E402

import mysql.connector  # noqa: E402

from services.assessment_store import MemoryAssessmentStore, MySQLAssessmentStore  # noqa: E402
from services.clinical_review_store import MemoryClinicalReviewStore, MySQLClinicalReviewStore, UnknownAssessmentError  # noqa: E402
from services.user_store import MemoryUserStore, MySQLUserStore  # noqa: E402

NOW = datetime(2026, 9, 20, 10, 0, 0)
LATER = datetime(2026, 9, 21, 10, 0, 0)


def setUpModule():
    mysql_support.prepare()


def tearDownModule():
    mysql_support.drop()


def new_user(users, role, name):
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    return users.create_user({"email": email, "full_name": name, "role": role, "professional": None}, "h", NOW)


class ClinicalReviewStoreContract:
    def make_stores(self):
        raise NotImplementedError

    def setUp(self):
        self.users, self.assessments, self.store = self.make_stores()
        self.patient = new_user(self.users, "general", "Ana Reyes")
        self.professional = new_user(self.users, "professional", "Dr. Maria Cruz")
        self.assessment_id = self.assessments.add_assessment(self.patient, {"assessment_type": "preliminary",
                                                                             "probability": 0.3, "classification": "low", "assessed_at": NOW})

    def add(self, **changes):
        defaults = dict(assessment_id=self.assessment_id, professional_user_id=self.professional,
                        professional_name="Dr. Maria Cruz", profession_title="Nephrologist",
                        note="Looks reasonable, recheck in 3 months.", created_at=NOW)
        defaults.update(changes)
        return self.store.add_review(**defaults)

    def test_a_written_review_is_read_back_exactly(self):
        self.add()
        reviews = self.store.list_for_assessment(self.assessment_id)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["professional_name"], "Dr. Maria Cruz")
        self.assertEqual(reviews[0]["profession_title"], "Nephrologist")
        self.assertEqual(reviews[0]["note"], "Looks reasonable, recheck in 3 months.")
        self.assertEqual(reviews[0]["created_at"], NOW)
        self.assertEqual(reviews[0]["professional_user_id"], self.professional)

    def test_several_reviews_on_one_assessment_are_kept_oldest_first(self):
        self.add(note="First note.", created_at=NOW)
        self.add(note="Second note.", created_at=LATER)
        notes = [r["note"] for r in self.store.list_for_assessment(self.assessment_id)]
        self.assertEqual(notes, ["First note.", "Second note."])

    def test_a_review_for_an_assessment_that_does_not_exist_is_refused(self):
        with self.assertRaises(UnknownAssessmentError):
            self.add(assessment_id=987654321)

    def test_an_assessment_with_no_reviews_returns_an_empty_list(self):
        self.assertEqual(self.store.list_for_assessment(self.assessment_id), [])

    def test_list_for_assessments_batches_several_at_once(self):
        second_assessment = self.assessments.add_assessment(self.patient, {"assessment_type": "preliminary",
                                                                            "probability": 0.4, "classification": "low", "assessed_at": NOW})
        self.add(assessment_id=self.assessment_id, note="On the first.")
        self.add(assessment_id=second_assessment, note="On the second.")
        by_assessment = self.store.list_for_assessments([self.assessment_id, second_assessment])
        self.assertEqual([r["note"] for r in by_assessment[self.assessment_id]], ["On the first."])
        self.assertEqual([r["note"] for r in by_assessment[second_assessment]], ["On the second."])

    def test_list_for_assessments_includes_an_empty_list_for_one_with_no_reviews(self):
        third_assessment = self.assessments.add_assessment(self.patient, {"assessment_type": "preliminary",
                                                                           "probability": 0.2, "classification": "low", "assessed_at": NOW})
        by_assessment = self.store.list_for_assessments([self.assessment_id, third_assessment])
        self.assertEqual(by_assessment[third_assessment], [])

    def test_list_for_assessments_with_an_empty_list_returns_an_empty_dict(self):
        self.assertEqual(self.store.list_for_assessments([]), {})


class MemoryStoreTests(ClinicalReviewStoreContract, unittest.TestCase):
    def make_stores(self):
        users = MemoryUserStore()
        assessments = MemoryAssessmentStore(users)
        return users, assessments, MemoryClinicalReviewStore(assessments)


class MySQLStoreTests(ClinicalReviewStoreContract, unittest.TestCase):
    def make_stores(self):
        if mysql_support.problem:
            self.skipTest(mysql_support.problem)
        mysql_support.push_app_context(self)
        return MySQLUserStore(), MySQLAssessmentStore(), MySQLClinicalReviewStore()

    def test_deleting_the_assessment_deletes_its_reviews(self):
        from db import execute, query_one
        self.add()
        execute("DELETE FROM assessments WHERE assessment_id = %s", (self.assessment_id,))
        self.assertEqual(query_one("SELECT COUNT(*) AS n FROM clinical_reviews WHERE assessment_id = %s", (self.assessment_id,))["n"], 0)

    def test_deleting_the_professional_keeps_the_review_but_clears_the_link(self):
        from db import execute, query_one
        self.add()
        execute("DELETE FROM users WHERE user_id = %s", (self.professional,))
        row = query_one("SELECT professional_user_id, professional_name, note FROM clinical_reviews WHERE assessment_id = %s", (self.assessment_id,))
        self.assertIsNone(row["professional_user_id"])
        self.assertEqual(row["professional_name"], "Dr. Maria Cruz")             # the snapshot survives


if __name__ == "__main__":
    unittest.main()
