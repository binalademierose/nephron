"""
Checks for the re-assessment rule (services/reassessment.py): the administrator's waiting period in calendar months,
and the two ways to screen again early - a healthcare professional the person shares with, or the administrator
approving the person's own request. Each opens ONE screening; after it the waiting period applies again.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import AppTestCase  # noqa: E402
from test_screening_flow import NEEDS_ML, NOW, answers, at  # noqa: E402
from services import eligibility, reassessment  # noqa: E402
from services.reassessment_store import MemoryReassessmentStore  # noqa: E402


class PeriodTests(unittest.TestCase):
    def test_months_are_calendar_months_and_the_day_is_kept_or_clamped(self):
        three = eligibility.Period(months=3)
        self.assertEqual(three.opens_on(date(2026, 10, 17)), date(2027, 1, 17))
        self.assertEqual(three.opens_on(date(2026, 11, 30)), date(2027, 2, 28))       # no 30 February
        self.assertEqual(eligibility.Period(months=12).opens_on(date(2024, 2, 29)), date(2025, 2, 28))
        self.assertEqual((three.label, eligibility.Period(months=1).label, eligibility.Period(days=30).label),
                         ("3 months", "1 month", "30 days"))

    def test_the_wait_counts_down_to_the_opening_day(self):
        status = eligibility.wait_status(date(2026, 10, 17), date(2026, 12, 17), eligibility.Period(months=3))
        self.assertEqual((status["state"], status["date"], status["days_left"]), ("waiting", date(2027, 1, 17), 31))
        self.assertAlmostEqual(status["elapsed_share"], 61 / 92)
        self.assertEqual(eligibility.wait_status(date(2026, 10, 17), date(2027, 1, 17), eligibility.Period(months=3))["state"], "available")
        self.assertEqual(eligibility.wait_status(date(2026, 10, 17), date(2026, 10, 18), eligibility.Period(months=3), True)["state"], "available")
        self.assertEqual(eligibility.wait_status(date(2026, 10, 17), date(2026, 10, 18), 30)["days_left"], 29)   # the old .env days still work

    def test_the_administrator_setting_wins_over_the_env_value(self):
        self.assertEqual(reassessment.period_from(3, 30), eligibility.Period(months=3))
        self.assertIsNone(reassessment.period_from(0, 30))                          # 0 = no waiting period, on purpose
        self.assertEqual(reassessment.period_from(None, 30), eligibility.Period(days=30))
        self.assertIsNone(reassessment.period_from(None, None))
        with self.assertRaises(ValueError):
            eligibility.Period()

    def test_only_listed_month_values_can_be_saved(self):
        store = MemoryReassessmentStore()
        self.assertEqual(reassessment.set_months(store, "6", 1, NOW), 6)
        self.assertEqual(reassessment.set_months(store, "0", 1, NOW), 0)
        for bad in ("13", "-1", "abc", None, "2.5"):
            with self.assertRaises(reassessment.RequestError):
                reassessment.set_months(store, bad, 1, NOW)
        self.assertEqual(store.get_months(), 0)

    def test_a_request_needs_the_person_to_be_waiting_and_only_one_is_pending(self):
        store = MemoryReassessmentStore()
        with self.assertRaises(reassessment.RequestError):
            reassessment.ask_admin(store, 7, "", waiting=False, now=NOW)
        with self.assertRaises(reassessment.RequestError):
            reassessment.ask_admin(store, 7, "x" * 301, waiting=True, now=NOW)
        reassessment.ask_admin(store, 7, "  ", waiting=True, now=NOW)
        self.assertIsNone(store.latest_for(7)["reason"])                                # a blank reason is fine
        with self.assertRaises(reassessment.RequestError):
            reassessment.ask_admin(store, 7, "again", waiting=True, now=NOW)
        self.assertEqual(store.close_pending(7, NOW), 1)
        self.assertEqual(store.latest_for(7)["status"], "closed")


class _RuleCase(AppTestCase):
    model = True

    def setUp(self):
        super().setUp()
        self.member = self.signed_in()                                                   # ana@example.com
        self.user_id = self.store.find_by_email("ana@example.com")["user_id"]
        self.admin = self.signed_in(email="admin@example.com", full_name="Site Admin")
        self.admin_id = self.store.find_by_email("admin@example.com")["user_id"]
        self.store.set_admin(self.admin_id, True)
        self.rules = self.app.extensions["reassessment_store"]
        self.assessments = self.app.extensions["assessment_store"]
        self.rules.set_months(3, self.admin_id, NOW)

    def submit(self, **changes):
        return self.post("/screening", answers(**changes), client=self.member, token_from="/screening")

    def count(self):
        return len(self.assessments.list_assessments(self.user_id))


@NEEDS_ML
class WaitingPeriodTests(_RuleCase):
    def test_three_months_block_a_new_screening_until_the_same_day_three_months_later(self):
        with at(NOW):                                                                  # 20 September 2026
            self.submit()
        with at(NOW + timedelta(days=40)):
            page = self.text(self.member.get("/screening"))
            self.submit(Age="70")
        self.assertIn("is not open yet", page)
        self.assertIn("waiting period of 3 months", page)
        self.assertIn("Ask the administrator", page)
        self.assertEqual(self.count(), 1)
        with at(datetime(2026, 12, 20, 4, 0)):
            self.assertIn('name="Age"', self.text(self.member.get("/screening")))

    def test_the_dashboard_and_history_show_the_same_opening_day(self):
        with at(NOW):
            self.submit()
        with at(NOW + timedelta(days=10)):
            dashboard = self.text(self.member.get("/dashboard"))
            history = self.text(self.member.get("/history"))
        self.assertIn("81 days left", dashboard)                                        # 20 Dec - 30 Sep
        self.assertIn("need it sooner?", dashboard)
        self.assertIn("81 days left", history)

    def test_no_waiting_period_lets_people_screen_whenever(self):
        self.rules.set_months(0, self.admin_id, NOW)
        with at(NOW):
            self.submit()
        with at(NOW + timedelta(days=1)):
            self.submit(Age="49")
        self.assertEqual(self.count(), 2)


@NEEDS_ML
class AdministratorOpeningTests(_RuleCase):
    def ask(self, reason="My doctor asked for a new check"):
        return self.post("/screening/ask-admin", {"reason": reason}, client=self.member, token_from="/screening")

    def pending_id(self):
        return self.rules.list("pending")[0]["request_id"]

    def test_approving_a_request_opens_one_screening_then_the_rule_applies_again(self):
        with at(NOW):
            self.submit()
        with at(NOW + timedelta(days=10)):
            self.assertEqual(self.ask().status_code, 302)
            self.assertIn("waiting for a decision", self.text(self.member.get("/screening")))
            admin_page = self.text(self.admin.get("/admin/reassessment"))
            self.assertIn("Ana", admin_page)
            self.assertIn("My doctor asked for a new check", admin_page)
            self.assertIn("next one opens", admin_page)
            self.post(f"/admin/reassessment/{self.pending_id()}/approve", {}, client=self.admin, token_from="/admin/reassessment")
            self.assertIn("The administrator approved your request", self.text(self.member.get("/dashboard")))
            self.submit(Age="49")                                                       # the one early screening
            self.assertEqual(self.count(), 2)
        with at(NOW + timedelta(days=11)):
            page = self.text(self.member.get("/screening"))
            self.submit(Age="50")
        self.assertIn("is not open yet", page)                                          # back to 3 months, from day 10
        self.assertEqual(self.count(), 2)
        self.assertEqual(self.rules.latest_for(self.user_id)["status"], "approved")
        notes = self.app.extensions["notification_store"].list_for_user(self.user_id)
        self.assertTrue(any("was approved" in n["title"] for n in notes))

    def test_declining_keeps_the_wait_and_tells_the_person(self):
        with at(NOW):
            self.submit()
        with at(NOW + timedelta(days=10)):
            self.ask()
            self.post(f"/admin/reassessment/{self.pending_id()}/decline", {}, client=self.admin, token_from="/admin/reassessment")
            page = self.text(self.member.get("/screening"))
            self.submit(Age="49")
        self.assertIn("was not approved", page)
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.rules.latest_for(self.user_id)["status"], "declined")

    def test_a_request_cannot_be_decided_twice_or_made_when_not_waiting(self):
        with at(NOW):
            self.ask()                                                                  # never screened: nothing to ask
            self.assertEqual(self.rules.list(), [])
            self.submit()
        with at(NOW + timedelta(days=1)):
            self.ask()
            request_id = self.pending_id()
            self.post(f"/admin/reassessment/{request_id}/decline", {}, client=self.admin, token_from="/admin/reassessment")
            response = self.post(f"/admin/reassessment/{request_id}/approve", {}, client=self.admin, token_from="/admin/reassessment")
        self.assertIn("already decided", self.text(self.admin.get(response.headers["Location"])))
        self.assertIsNone(self.app.extensions["followup_store"].get_open(self.user_id))

    def test_screening_another_way_closes_a_request_still_waiting(self):
        with at(NOW):
            self.submit()
        with at(NOW + timedelta(days=10)):
            self.ask()
        self.rules.set_months(0, self.admin_id, NOW)
        with at(NOW + timedelta(days=11)):
            self.submit(Age="49")
        self.assertEqual(self.rules.latest_for(self.user_id)["status"], "closed")
        self.assertIn("Screened before a decision", self.text(self.admin.get("/admin/reassessment")))

    def test_an_over_long_reason_is_refused_with_the_form_kept(self):
        with at(NOW):
            self.submit()
        with at(NOW + timedelta(days=10)):
            page = self.text(self.ask("x" * 301))
        self.assertIn("keep the reason to 300 characters", page)
        self.assertEqual(self.rules.list(), [])


@NEEDS_ML
class ProfessionalOpeningTests(_RuleCase):
    def test_any_authorized_professional_can_open_one_early_screening(self):
        pro = self.signed_in(**self.professional_details(profession_title="Nurse"))
        pro_id = self.store.find_by_email("dr.cruz@example.com")["user_id"]
        self.post("/share/request", {"consent": "1", "professional_user_id": str(pro_id)}, client=self.member, token_from="/share")
        self.post(f"/patients/respond/{self.user_id}", {"action": "accept"}, client=pro, token_from="/patients")
        with at(NOW):
            self.submit()
        with at(NOW + timedelta(days=10)):
            self.post(f"/patients/{self.user_id}/follow-up", {"message": "Please re-check"}, client=pro, token_from=f"/patients/{self.user_id}")
            self.submit(Age="49")
        with at(NOW + timedelta(days=12)):
            self.submit(Age="50")
        self.assertEqual(self.count(), 2)                                               # one early screening, then the wait again


class AdminPageTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.signed_in()
        self.admin = self.signed_in(email="admin@example.com", full_name="Site Admin")
        self.admin_id = self.store.find_by_email("admin@example.com")["user_id"]
        self.store.set_admin(self.admin_id, True)

    def test_only_the_administrator_opens_the_page_and_changes_are_logged(self):
        self.assertEqual(self.member.get("/admin/reassessment").status_code, 403)
        page = self.text(self.admin.get("/admin/reassessment"))
        self.assertIn("Re-assessment rule", page)
        self.assertIn("No waiting period", page)                                       # nothing set in the tests' store
        self.post("/admin/reassessment/rule", {"months": "3"}, client=self.admin, token_from="/admin/reassessment")
        self.assertEqual(self.app.extensions["reassessment_store"].get_months(), 3)
        self.assertIn("Every 3 months", self.text(self.admin.get("/admin/reassessment")))
        response = self.post("/admin/reassessment/rule", {"months": "99"}, client=self.admin, token_from="/admin/reassessment")
        self.assertIn("Choose a waiting period", self.text(self.admin.get(response.headers["Location"])))
        self.assertEqual(self.app.extensions["reassessment_store"].get_months(), 3)
        self.assertIn("Changed the waiting period", self.text(self.admin.get("/admin/activity")))

    def test_the_rail_links_the_page_and_the_tree_drawing_is_gone(self):
        page = self.text(self.admin.get("/admin"))
        self.assertIn("/admin/reassessment", page)
        self.assertEqual(self.post("/admin/reassessment/1/maybe", {}, client=self.admin, token_from="/admin/reassessment").status_code, 404)

    def test_the_real_database_uses_three_months_until_the_administrator_saves_a_rule(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database", "migrations", "023_create_reassessment_rule.sql")
        with open(path, encoding="utf-8") as handle:
            sql = handle.read()
        self.assertIn("CREATE TABLE IF NOT EXISTS app_settings", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS reassessment_requests", sql)
        self.assertNotIn("ALTER TABLE", sql)                                             # adds, never modifies
        from services.reassessment_store import MySQLReassessmentStore
        self.assertEqual(MySQLReassessmentStore.default_months, 3)                       # the real site's rule until changed
        self.assertEqual(reassessment.period_from(None, None, 3), eligibility.Period(months=3))
        self.assertEqual(reassessment.period_from(None, 30, 3), eligibility.Period(days=30))   # an .env value still wins over the default


if __name__ == "__main__":
    unittest.main()
