"""
Checks for services/lab_document_store.py. The SAME checks run against two stores:
  * MemoryLabDocumentStore - always runs.
  * MySQLLabDocumentStore  - runs on the separate <DB_NAME>_test database (see tests/mysql_support.py).
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

from services.lab_document_store import MemoryLabDocumentStore, MySQLLabDocumentStore, UnknownUserError  # noqa: E402
from services.user_store import MemoryUserStore, MySQLUserStore  # noqa: E402

NOW = datetime(2026, 9, 20, 10, 0, 0)


def setUpModule():
    mysql_support.prepare()


def tearDownModule():
    mysql_support.drop()


def new_user(users, name="Ana Reyes"):
    email = f"{uuid.uuid4().hex[:10]}@example.com"
    return users.create_user({"email": email, "full_name": name, "role": "general", "professional": None}, "h", NOW)


class LabDocumentStoreContract:
    def make_stores(self):
        raise NotImplementedError

    def setUp(self):
        self.users, self.store = self.make_stores()
        self.user_id = new_user(self.users)

    def upload(self, **overrides):
        defaults = dict(user_id=self.user_id, original_filename="labs.jpg", stored_filename="abc123.jpg",
                        content_type="image/jpeg", uploaded_at=NOW)
        defaults.update(overrides)
        return self.store.add_document(**defaults)

    def test_a_fresh_upload_starts_as_uploaded_with_nothing_extracted_yet(self):
        document_id = self.upload()
        row = self.store.get_document(self.user_id, document_id)
        self.assertEqual(row["status"], "uploaded")
        self.assertIsNone(row["ocr_values"])
        self.assertIsNone(row["confirmed_values"])
        self.assertIsNone(row["assessment_id"])
        self.assertEqual((row["original_filename"], row["stored_filename"], row["content_type"]), ("labs.jpg", "abc123.jpg", "image/jpeg"))

    def test_setting_ocr_values_moves_it_to_extracted(self):
        document_id = self.upload()
        self.store.set_ocr_values(self.user_id, document_id, {"Serum_Creatinine": 1.1, "Sodium": 140.0})
        row = self.store.get_document(self.user_id, document_id)
        self.assertEqual(row["status"], "extracted")
        self.assertEqual(row["ocr_values"], {"Serum_Creatinine": 1.1, "Sodium": 140.0})

    def test_confirming_moves_it_to_confirmed_and_records_the_assessment(self):
        from services.assessment_store import MemoryAssessmentStore, MySQLAssessmentStore
        assessments = MySQLAssessmentStore() if isinstance(self.store, MySQLLabDocumentStore) else MemoryAssessmentStore(self.users)
        assessment_id = assessments.add_assessment(self.user_id, {"assessment_type": "preliminary", "probability": 0.3,
                                                                   "classification": "low", "assessed_at": NOW})
        document_id = self.upload()
        self.store.set_ocr_values(self.user_id, document_id, {"Serum_Creatinine": 1.1})
        self.store.confirm(self.user_id, document_id, {"Serum_Creatinine": 1.2}, assessment_id=assessment_id, confirmed_at=NOW)
        row = self.store.get_document(self.user_id, document_id)
        self.assertEqual(row["status"], "confirmed")
        self.assertEqual(row["confirmed_values"], {"Serum_Creatinine": 1.2})     # the CONFIRMED value, which the person may have edited
        self.assertEqual(row["assessment_id"], assessment_id)
        self.assertEqual(row["confirmed_at"], NOW)

    def test_discarding_moves_it_to_discarded(self):
        document_id = self.upload()
        self.store.discard(self.user_id, document_id)
        self.assertEqual(self.store.get_document(self.user_id, document_id)["status"], "discarded")

    def test_listed_newest_first(self):
        first = self.upload()
        second = self.upload(uploaded_at=datetime(2026, 9, 21, 10, 0, 0))
        ids = [row["lab_document_id"] for row in self.store.list_documents(self.user_id)]
        self.assertEqual(ids, [second, first])

    def test_one_person_never_sees_or_changes_another_persons_upload(self):
        other = new_user(self.users, "Ben Cruz")
        mine = self.upload()
        self.assertIsNone(self.store.get_document(other, mine))
        self.store.set_ocr_values(other, mine, {"Serum_Creatinine": 9.9})       # silently affects nothing
        self.store.confirm(other, mine, {"Serum_Creatinine": 9.9}, assessment_id=1, confirmed_at=NOW)
        self.store.discard(other, mine)
        row = self.store.get_document(self.user_id, mine)
        self.assertEqual(row["status"], "uploaded")
        self.assertIsNone(row["ocr_values"])

    def test_an_upload_for_a_user_that_does_not_exist_is_refused(self):
        with self.assertRaises(UnknownUserError):
            self.upload(user_id=987654321)


class MemoryStoreTests(LabDocumentStoreContract, unittest.TestCase):
    def make_stores(self):
        users = MemoryUserStore()
        return users, MemoryLabDocumentStore(users)


class MySQLStoreTests(LabDocumentStoreContract, unittest.TestCase):
    def make_stores(self):
        if mysql_support.problem:
            self.skipTest(mysql_support.problem)
        mysql_support.push_app_context(self)
        return MySQLUserStore(), MySQLLabDocumentStore()

    def test_deleting_a_user_deletes_their_uploads(self):
        from db import execute, query_one
        self.upload()
        execute("DELETE FROM users WHERE user_id = %s", (self.user_id,))
        self.assertEqual(query_one("SELECT COUNT(*) AS n FROM lab_documents WHERE user_id = %s", (self.user_id,))["n"], 0)

    def test_an_upload_for_an_assessment_that_does_not_exist_is_refused_by_the_database(self):
        from db import execute
        try:
            from db import query_one
            query_one("SELECT VERSION() AS v")
        except mysql.connector.Error:
            self.skipTest("the sandbox stand-in cannot add a foreign key to an existing table; this needs real MySQL")
        with self.assertRaises(mysql.connector.IntegrityError):
            execute("UPDATE lab_documents SET assessment_id = %s WHERE lab_document_id = %s", (987654321, self.upload()))


if __name__ == "__main__":
    unittest.main()
