"""
test_local_times.py - every time is STORED in UTC and must be SHOWN in the app's own timezone (Asia/Manila, UTC+8).
The admin activity log once printed the stored UTC time directly, so everything looked 8 hours early (6:15 AM in
Manila showed as 10:15 PM the day before), and several admin dates were a day early before 8 in the morning.
"""
import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from test_admin_flow import AdminTestCase  # noqa: E402
from services import activity, admin_overview  # noqa: E402

EARLY_MORNING_UTC = datetime(2026, 10, 27, 22, 15)       # = Oct 28, 2026, 6:15 AM in Manila


class AdminTimesTests(AdminTestCase):
    def test_the_activity_log_shows_philippine_time(self):
        with self.app.test_request_context(), mock.patch("services.clock.now_utc", return_value=EARLY_MORNING_UTC):
            activity.record("password_reset", self.admin_id, self.patient_id)
        page = self.text(self.admin.get("/admin/activity"))
        self.assertIn("Oct 28, 2026, 6:15 AM", page)
        self.assertNotIn("10:15 PM", page)

    def test_admin_dates_are_the_philippine_calendar_day(self):
        self.store._users[self.patient_id]["created_at"] = EARLY_MORNING_UTC
        self.store._users[self.patient_id]["last_login_at"] = EARLY_MORNING_UTC
        dashboard = self.text(self.admin.get("/admin"))
        users = self.text(self.admin.get("/admin/users"))
        for page in (dashboard, users):
            self.assertIn("Oct 28, 2026", page)
            self.assertNotIn("Oct 27, 2026", page)


class MonthStartTests(unittest.TestCase):
    def test_this_month_starts_at_midnight_in_the_philippines_not_at_8_am(self):
        joined_just_after_midnight_oct_1_manila = datetime(2026, 9, 30, 17, 0)        # 1:00 AM Oct 1 in Manila
        joined_late_sep_30_manila = datetime(2026, 9, 30, 15, 0)                       # 11:00 PM Sep 30 in Manila
        accounts = [{"created_at": joined_just_after_midnight_oct_1_manila, "role": "general"},
                    {"created_at": joined_late_sep_30_manila, "role": "general"}]
        kpis = admin_overview.user_kpis(accounts, datetime(2026, 10, 15, 4, 0), timezone_name="Asia/Manila")
        self.assertEqual(kpis["new_this_month"], 1)


if __name__ == "__main__":
    unittest.main()
