"""Checks for services/consent_store.py and services/consents.py. The store checks run on Memory and MySQL."""
import os
import sys
import unittest
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mysql_support  # noqa: E402

from werkzeug.datastructures import MultiDict  # noqa: E402

from services import consents  # noqa: E402
from services.consent_store import MemoryConsentStore, MySQLConsentStore  # noqa: E402
from services.user_store import MemoryUserStore, MySQLUserStore  # noqa: E402

NOW = datetime(2026, 9, 20, 10, 0, 0)
LATER = datetime(2026, 9, 21, 10, 0, 0)


def setUpModule():
    mysql_support.prepare()


def tearDownModule():
    mysql_support.drop()


def new_user(users):
    return users.create_user({"email": f"{uuid.uuid4().hex[:10]}@example.com", "full_name": "Ana Reyes", "role": "general", "professional": None}, "h", NOW)


class ConsentStoreContract:
    def make_stores(self):
        raise NotImplementedError

    def setUp(self):
        self.users, self.store = self.make_stores()
        self.patient, self.professional = new_user(self.users), new_user(self.users)

    def test_an_agreement_is_recorded_with_its_version_and_time(self):
        self.store.record(self.patient, self.professional, "share_history", "share-history-v1", NOW)
        row = self.store.list_for_patient(self.patient)[0]
        self.assertEqual((row["professional_user_id"], row["consent_type"], row["consent_version"], row["consented_at"]),
                         (self.professional, "share_history", "share-history-v1", NOW))

    def test_every_agreement_stays_on_record_newest_first(self):
        self.store.record(self.patient, self.professional, "share_history", "share-history-v1", NOW)
        self.store.record(self.patient, self.professional, "share_history", "share-history-v1", LATER)
        self.assertEqual([r["consented_at"] for r in self.store.list_for_patient(self.patient)], [LATER, NOW])

    def test_one_patients_agreements_are_invisible_to_another(self):
        other = new_user(self.users)
        self.store.record(self.patient, self.professional, "share_history", "share-history-v1", NOW)
        self.assertEqual(self.store.list_for_patient(other), [])

    def test_nobody_with_no_agreements_has_an_empty_list(self):
        self.assertEqual(self.store.list_for_patient(self.patient), [])


class MemoryStoreTests(ConsentStoreContract, unittest.TestCase):
    def make_stores(self):
        return MemoryUserStore(), MemoryConsentStore()


class MySQLStoreTests(ConsentStoreContract, unittest.TestCase):
    def make_stores(self):
        if mysql_support.problem:
            self.skipTest(mysql_support.problem)
        mysql_support.push_app_context(self)
        return MySQLUserStore(), MySQLConsentStore()


class ConsentRulesTests(unittest.TestCase):
    def test_only_an_explicit_one_counts_as_consent(self):
        self.assertTrue(consents.given(MultiDict([("consent", "1")])))
        self.assertTrue(consents.given(MultiDict([("consent", ""), ("consent", "1")])))     # hidden field + ticked checkbox
        for form in (MultiDict(), MultiDict([("consent", "")]), MultiDict([("consent", "0")]), MultiDict([("consent", "true")])):
            self.assertFalse(consents.given(form), form)

    def test_the_latest_agreement_per_professional_wins(self):
        store = MemoryConsentStore()
        store.record(1, 2, "share_history", consents.CURRENT_VERSION, NOW)
        store.record(1, 2, "share_history", consents.CURRENT_VERSION, LATER)
        store.record(1, 3, "share_history", consents.CURRENT_VERSION, NOW)
        dates = consents.latest_dates_for_patient(store, 1, "Asia/Manila")
        self.assertEqual(dates[2], LATER.date())
        self.assertEqual(dates[3], NOW.date())


if __name__ == "__main__":
    unittest.main()
