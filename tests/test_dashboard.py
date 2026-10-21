"""
Checks for the real dashboard (/dashboard). They prove the blueprint's dashboard rules:
  * every number, chart and list comes from the person's OWN saved assessments (nothing invented),
  * an empty account gets honest empty states, never placeholder numbers,
  * nobody sees anyone else's results,
  * every control either goes somewhere real or says it is not available yet.
They use in-memory stores, so no database is needed. Run everything with:  python -m unittest discover -s tests -v
"""
import os
import re
import sys
import unittest
from datetime import datetime, timedelta
from html.parser import HTMLParser
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import AppTestCase  # noqa: E402

import mysql.connector  # noqa: E402

from app import create_app  # noqa: E402
from services.assessment_store import MemoryAssessmentStore  # noqa: E402
from services.user_store import MemoryUserStore  # noqa: E402

NOON_IN_MANILA = datetime(2026, 9, 20, 4, 0, 0)      # 12:00 on 20 September in Manila (UTC+8)


def at(moment):
    return mock.patch("services.clock.now_utc", return_value=moment)


class Links(HTMLParser):
    """Collects every link, and every control that pretends to be one."""

    def __init__(self):
        super().__init__()
        self.hrefs, self.disabled = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and "href" in a:
            self.hrefs.append(a["href"])
        if a.get("aria-disabled") == "true":
            self.disabled.append((tag, "href" in a))


class EmptyDashboardTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.member = self.signed_in()
        self.page = self.text(self.member.get("/dashboard"))

    def test_every_card_is_an_honest_empty_state(self):
        for words in ("No assessments yet", "Chart appears when sufficient data exists", "No result yet",
                      "No activity yet", "No results to summarise yet"):
            self.assertIn(words, self.page)
        self.assertRegex(self.page, r'class="stat-value"\s*>0<')            # the honest count is zero

    def test_nothing_is_drawn_that_has_no_data_behind_it(self):
        # "Kidney health, by the numbers" always draws its own rings - real, sourced population statistics
        # (services/ckd_facts.py), never a claim about this person's data - so it is excluded here, not exempted
        # from the real check (test_ckd_facts.py checks every one of its figures carries a source).
        without_ckd_facts = re.sub(r'<section class="ckd-side[^>]*aria-labelledby="ckd-facts-heading".*?</section>', "", self.page, flags=re.S)
        self.assertIn("ckd-facts-heading", self.page)
        self.assertNotIn("ckd-facts-heading", without_ckd_facts)
        for drawn in ('class="chart-line"', 'class="ring-value"', "donut-segment", "timeline-item timeline-",
                      "activity-item", 'class="sparkline"', "risk-pill", "sample-tag", "Sample data"):
            self.assertNotIn(drawn, without_ckd_facts, drawn)
        self.assertNotIn("Preliminary Risk", self.page)                     # neither result is named without a result
        self.assertNotIn("Moderate", self.page)                             # the model has two classes only

    def test_no_notification_count_and_no_invented_statistics(self):
        # The bell is real now (services/notifications.py), so the word itself is expected here - what must never
        # appear is an unread-count badge with nothing real behind it.
        self.assertNotIn("notif-badge", self.page)
        without_axis = re.sub(r'<svg class="chart-svg".*?</svg>', "", self.page, flags=re.S)   # the empty chart's 0% to 100% scale is not data
        # "Kidney health, by the numbers" is real, sourced, population-level statistics (services/ckd_facts.py) -
        # not a claim about this person's own data, so it is excluded here, not exempted from the real check
        # elsewhere (test_ckd_facts.py checks every one of its figures carries a source).
        without_ckd_facts = re.sub(r'<section class="ckd-side[^>]*aria-labelledby="ckd-facts-heading".*?</section>', "", without_axis, flags=re.S)
        self.assertIn("ckd-facts-heading", without_axis)              # sanity: the section is really there to strip
        self.assertNotIn("ckd-facts-heading", without_ckd_facts)      # sanity: the strip actually worked
        self.assertNotRegex(without_ckd_facts, r"\b\d+(\.\d+)?\s*%")                # no OTHER percentage appears without a result

    def test_screening_is_honestly_not_available_yet(self):
        self.assertIn("Screening is not available yet", self.page)
        self.assertNotIn("Start Assessment</a>", self.page)                 # no working-looking button that leads nowhere
        self.assertIn("Not available yet", self.page)
        self.assertIn("Coming soon", self.page)

    def test_the_path_starts_at_screening(self):
        self.assertEqual(self.page.count('class="path-step is-current"'), 1)
        self.assertNotIn("is-done", self.page)

    def test_the_person_sees_their_own_name_and_role(self):
        self.assertRegex(self.page, r"<span data-greeting>Welcome</span>, Ana ")       # JavaScript turns "Welcome" into Good morning/afternoon
        self.assertIn("Ana Reyes", self.page)
        self.assertIn("General User", self.page)

    def test_every_link_goes_somewhere_real_and_every_unbuilt_control_is_marked_unavailable(self):
        links = Links()
        links.feed(self.page)
        self.assertTrue(links.hrefs)
        for href in links.hrefs:
            self.assertNotEqual(href, "#", "a link that goes nowhere")
            if href.startswith("/"):
                self.assertEqual(self.member.get(href).status_code, 200, f"{href} is not a real page")
        self.assertNotIn("data-preview-link", self.page)                    # that belongs to the design previews only
        # Only what really cannot work yet stays disabled here (screening itself, while the model is not ready);
        # "Tips for healthy kidneys" now links to the real kidney-health checklist, so it is no longer one of them,
        # and the quick-actions panel (which repeated the start button) has been replaced by the kidney facts.
        self.assertGreaterEqual(len(links.disabled), 2)
        for tag, has_href in links.disabled:
            self.assertFalse(has_href, "an unavailable control must not carry an address")


class PopulatedDashboardTests(AppTestCase):
    """A person with three saved results: high (latest), low, low. Every number below is worked out from them."""

    def setUp(self):
        super().setUp()
        self.member = self.signed_in()
        first = self.add_assessment(probability=0.15, classification="low", assessed_at=datetime(2026, 6, 12, 4, 0, 0))
        self.add_assessment(probability=0.18, classification="low", assessed_at=datetime(2026, 8, 10, 4, 0, 0),
                            assessment_type="enhanced", source_assessment_id=first)
        self.add_assessment(probability=0.31, classification="high", assessed_at=datetime(2026, 9, 18, 4, 0, 0), threshold_used=0.21)
        with at(NOON_IN_MANILA):
            self.page = self.text(self.member.get("/dashboard"))

    def test_the_counts_come_from_the_saved_records(self):
        self.assertRegex(self.page, r'class="stat-value" data-count-to="3">3<')
        self.assertIn("2 low-risk and 1 high-risk results", self.page)           # the donut
        self.assertIn("Most of your results are in the lower-risk group.", self.page)
        self.assertEqual(len(re.findall(r'activity-title[^>]*>Assessment completed<', self.page)), 3)

    def test_the_latest_result_is_the_newest_one_with_its_own_threshold(self):
        self.assertIn("stat-value-high", self.page)
        self.assertIn(">High Preliminary Risk<", self.page)
        self.assertIn("Predicted Risk Probability: 31 percent", self.page)
        self.assertIn("Threshold: 21%", self.page)
        self.assertIn("Assessed on Sep 18, 2026", self.page)

    def test_the_chart_draws_one_point_per_record_on_a_zero_to_one_hundred_scale(self):
        self.assertEqual(self.page.count('class="chart-point"'), 3)
        self.assertIn(">100%<", self.page)
        self.assertIn(">0%<", self.page)
        self.assertIn('class="sparkline"', self.page)

    def test_this_month_is_worked_out_from_the_dates(self):
        self.assertIn("1 this month", self.page)                             # only the 18 Sep result is in September

    def test_the_path_moves_on_once_there_is_a_result(self):
        self.assertEqual(self.page.count("path-step is-done"), 3)
        self.assertEqual(self.page.count('class="path-step is-current"'), 1)

    def test_nothing_is_labelled_as_sample_data(self):
        self.assertNotIn("sample-tag", self.page)
        self.assertNotIn("Sample data", self.page)

    def test_screening_is_still_honestly_unavailable(self):
        self.assertIn("Screening is not available yet", self.page)
        self.assertNotIn("Available now", self.page)

    def test_one_result_draws_the_ring_but_not_a_trend(self):
        second = self.signed_in(email="ben@example.com", full_name="Ben Lim")
        self.add_assessment("ben@example.com", probability=0.05, classification="low")
        page = self.text(second.get("/dashboard"))
        self.assertIn("Predicted Risk Probability: 5 percent", page)
        self.assertIn("A trend needs at least two saved assessments.", page)
        self.assertEqual(page.count('class="chart-point"'), 0)

    def test_a_result_saved_without_a_threshold_shows_no_threshold(self):
        third = self.signed_in(email="cara@example.com", full_name="Cara Diaz")
        self.add_assessment("cara@example.com", threshold_used=None, model_version=None)
        self.assertNotIn("Threshold:", self.text(third.get("/dashboard")))


class PrivacyTests(AppTestCase):
    def test_one_person_never_sees_another_persons_results(self):
        ana = self.signed_in()
        ben = self.signed_in(email="ben@example.com", full_name="Ben Lim")
        self.add_assessment("ana@example.com", probability=0.3141, classification="high")
        ben_page = self.text(ben.get("/dashboard"))
        self.assertIn("No assessments yet", ben_page)
        self.assertNotIn("31.4", ben_page)
        self.assertNotIn("High Preliminary Risk", ben_page)
        self.assertIn("31.4", self.text(ana.get("/dashboard")))                 # the ring shows one decimal

    def test_a_professional_cannot_open_the_general_dashboard(self):
        doctor = self.signed_in(**self.professional_details())
        self.assertEqual(doctor.get("/dashboard").status_code, 403)

    def test_a_visitor_is_sent_to_sign_in(self):
        self.assertEqual(self.client.get("/dashboard").status_code, 302)


class TimeAndConfigTests(AppTestCase):
    def test_dates_are_shown_in_the_configured_time_zone(self):
        # 23:30 UTC on 19 Sep is 07:30 on 20 Sep in Manila, but still the 19th in UTC.
        self.register()
        self.add_assessment(assessed_at=datetime(2026, 9, 19, 23, 30, 0))
        with at(NOON_IN_MANILA):
            self.assertIn("Sep 20, 2026", self.text(self.client.get("/dashboard")))
        utc_app = create_app({"APP_TIMEZONE": "UTC"}, user_store=self.store, assessment_store=self.app.extensions["assessment_store"])
        browser = utc_app.test_client()
        self.login(browser)
        with at(NOON_IN_MANILA):
            self.assertIn("Sep 19, 2026", self.text(browser.get("/dashboard")))

    def test_impossible_settings_stop_the_app_with_a_plain_message(self):
        for overrides, words in (({"REASSESSMENT_DAYS": 0}, "REASSESSMENT_DAYS"), ({"REASSESSMENT_DAYS": "abc"}, "REASSESSMENT_DAYS"),
                                 ({"REASSESSMENT_DAYS": -3}, "REASSESSMENT_DAYS"), ({"APP_TIMEZONE": "Nowhere/City"}, "APP_TIMEZONE")):
            with self.assertRaises(RuntimeError) as caught:
                create_app(overrides, user_store=MemoryUserStore())
            self.assertIn(words, str(caught.exception))

    def test_sensible_settings_are_accepted(self):
        create_app({"REASSESSMENT_DAYS": 30, "APP_TIMEZONE": "Asia/Manila"}, user_store=MemoryUserStore())
        create_app({"REASSESSMENT_DAYS": None}, user_store=MemoryUserStore())

    def test_the_waiting_period_starts_empty_because_the_team_has_not_decided_one(self):
        from config import Config
        self.assertIsNone(Config.REASSESSMENT_DAYS)


class BrokenAssessments(MemoryAssessmentStore):
    def list_assessments(self, user_id):
        raise mysql.connector.OperationalError("SELECT secret FROM hidden failed")


class DatabaseDownTests(unittest.TestCase):
    def test_the_dashboard_shows_the_friendly_unavailable_page_and_no_technical_detail(self):
        users = MemoryUserStore()
        app = create_app(user_store=users, assessment_store=BrokenAssessments(users))
        client = app.test_client()
        token = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/register").get_data(as_text=True)).group(1)
        client.post("/register", data={"csrf_token": token, "role": "general", "full_name": "Ana Reyes",
                                       "email": "ana@example.com", "password": "a-long-enough-phrase",
                                       "confirm_password": "a-long-enough-phrase", "username": "ana_r_debug",
                                       "date_of_birth": "1990-05-14", "avatar": "avatar-1", "country": "Other",
                                       "agree_terms": "agree"})
        response = client.get("/dashboard")
        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 503)
        self.assertIn("temporarily unavailable", page)
        self.assertNotIn("secret", page)


if __name__ == "__main__":
    unittest.main()
