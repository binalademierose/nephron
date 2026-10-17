"""
Checks for services/eligibility.py: the one rule for "may this person start a screening now?".
No Flask and no database. Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import eligibility, visuals  # noqa: E402

LAST = date(2026, 9, 1)


class WaitStatusTests(unittest.TestCase):
    def test_a_person_who_was_never_screened_may_screen(self):
        status = eligibility.wait_status(None, date(2026, 9, 20), 30)
        self.assertEqual((status["state"], status["date"], status["days_left"]), ("available", None, 0))

    def test_with_no_waiting_period_set_anyone_may_screen_again_at_once(self):
        for days in (None, 0):
            self.assertEqual(eligibility.wait_status(LAST, LAST, days)["state"], "available")

    def test_inside_the_waiting_period_the_day_it_opens_and_the_days_left_are_given(self):
        status = eligibility.wait_status(LAST, date(2026, 9, 5), 30)
        self.assertEqual((status["state"], status["date"], status["days_left"]), ("waiting", date(2026, 10, 1), 26))
        self.assertAlmostEqual(status["elapsed_share"], 4 / 30)

    def test_the_last_day_of_waiting_and_the_day_it_opens(self):
        self.assertEqual(eligibility.wait_status(LAST, date(2026, 9, 30), 30)["days_left"], 1)          # one day still to wait
        opens = eligibility.wait_status(LAST, date(2026, 10, 1), 30)                                     # the day it opens
        self.assertEqual((opens["state"], opens["days_left"], opens["elapsed_share"]), ("available", 0, 1.0))
        self.assertEqual(eligibility.wait_status(LAST, date(2027, 1, 1), 30)["state"], "available")      # long after

    def test_the_same_day_is_the_start_of_the_wait(self):
        status = eligibility.wait_status(LAST, LAST, 30)
        self.assertEqual((status["state"], status["days_left"], status["elapsed_share"]), ("waiting", 30, 0.0))

    def test_a_one_day_wait(self):
        self.assertEqual(eligibility.wait_status(LAST, LAST, 1)["state"], "waiting")
        self.assertEqual(eligibility.wait_status(LAST, date(2026, 9, 2), 1)["state"], "available")

    def test_an_open_follow_up_request_lets_a_person_screen_again_right_away(self):
        status = eligibility.wait_status(LAST, LAST, 30, follow_up_open=True)                          # the very first day of a 30-day wait
        self.assertEqual((status["state"], status["date"], status["days_left"]), ("available", None, 0))

    def test_a_follow_up_request_that_is_not_open_changes_nothing(self):
        status = eligibility.wait_status(LAST, LAST, 30, follow_up_open=False)
        self.assertEqual(status["state"], "waiting")


class ScreeningStatusTests(unittest.TestCase):
    def test_no_verified_model_beats_every_other_answer(self):
        for last, days in ((None, None), (LAST, 30), (LAST, None)):
            self.assertEqual(eligibility.screening_status(last, date(2026, 9, 5), days, model_ready=False)["state"], "unavailable")

    def test_no_verified_model_beats_even_an_open_follow_up_request(self):
        status = eligibility.screening_status(LAST, LAST, 30, model_ready=False, follow_up_open=True)
        self.assertEqual(status["state"], "unavailable")

    def test_a_ready_model_and_an_open_follow_up_request_together_are_available(self):
        status = eligibility.screening_status(LAST, LAST, 30, model_ready=True, follow_up_open=True)
        self.assertEqual(status["state"], "available")

    def test_with_a_model_the_waiting_rule_decides(self):
        self.assertEqual(eligibility.screening_status(None, date(2026, 9, 5), 30, True)["state"], "available")
        self.assertEqual(eligibility.screening_status(LAST, date(2026, 9, 5), 30, True)["state"], "waiting")
        self.assertEqual(eligibility.screening_status(LAST, date(2026, 10, 1), 30, True)["state"], "available")

    def test_the_dates_are_still_given_when_the_model_is_unavailable(self):
        status = eligibility.screening_status(LAST, date(2026, 9, 5), 30, False)
        self.assertEqual((status["state"], status["date"], status["days_left"]), ("unavailable", date(2026, 10, 1), 26))


class OneRuleEverywhereTests(unittest.TestCase):
    def test_the_dashboard_summary_gives_exactly_the_same_answer_as_this_module(self):
        records = [{"date": LAST, "type": "Preliminary screening", "probability": 20.0, "level": "low"}]
        for days in (None, 1, 7, 30, 90):
            for offset in (0, 1, 6, 7, 29, 30, 31, 200):
                today = date.fromordinal(LAST.toordinal() + offset)
                self.assertEqual(visuals.summarize_assessments(records, today=today, reassessment_days=days)["next_screening"],
                                 eligibility.wait_status(LAST, today, days), (days, offset))
        self.assertEqual(visuals.summarize_assessments([], today=LAST, reassessment_days=30)["next_screening"],
                         eligibility.wait_status(None, LAST, 30))


if __name__ == "__main__":
    unittest.main()
