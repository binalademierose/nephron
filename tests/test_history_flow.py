"""
Phase 5 through the real website: the history page, the comparison of two assessments, and the one eligibility rule.
Every assessment is a permanent record that only its owner can see. Run everything with:   python -m unittest discover -s tests -v
"""
import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import model_fixtures  # noqa: E402
from helpers import AppTestCase  # noqa: E402

NEEDS_ML = unittest.skipUnless(model_fixtures.libraries_available(), "needs scikit-learn, pandas, numpy and joblib (see requirements.txt)")


def days_ago(days, hours=0):
    """A moment in the past as the store keeps it: UTC, without a time zone."""
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days, hours=hours)


def answers(**changes):
    values = {"Country": "Other", "Sex": "Female", "Ethnicity": "Asian", "Age": 48, "BMI": 27.3, "height_cm": 160.0, "weight_kg": 70.0,
              "Obesity": 0, "Diabetes": 1, "Hypertension": 0, "Smoking_Status": "Never"}
    values.update(changes)
    return values


@NEEDS_ML
class HistoryTestCase(AppTestCase):
    model = True

    def setUp(self):
        super().setUp()
        self.member = self.signed_in()

    def page(self, path="/history", client=None):
        return self.text((client or self.member).get(path))

    def rows(self, page):
        """The dates in the table, in the order shown."""
        return re.findall(r'<td data-label="Date"><a href="/results/\d+">(.*?)</a></td>', page)


@NEEDS_ML
class HistoryPageTests(HistoryTestCase):
    def test_a_visitor_is_sent_to_sign_in_and_a_professional_is_refused(self):
        self.assertEqual(self.client.get("/history").status_code, 302)
        doctor = self.signed_in(**self.professional_details())
        self.assertEqual(doctor.get("/history").status_code, 403)

    def test_with_no_assessments_it_says_so_and_offers_to_start(self):
        page = self.page()
        self.assertIn("No assessments yet", page)
        self.assertIn("Start assessment", page)
        self.assertNotIn("<table", page)
        self.assertNotIn("chart-line", page)                                        # no line is drawn for no data
        self.assertIn("Chart appears when sufficient data exists", page)

    def test_the_assessments_are_listed_newest_first_with_their_result_in_the_agreed_words(self):
        self.add_assessment(probability=0.30, classification="low", assessed_at=days_ago(40))
        self.add_assessment(probability=0.55, classification="high", assessed_at=days_ago(2))
        self.add_assessment(probability=0.40, classification="low", assessed_at=days_ago(20))
        page = self.page()
        self.assertEqual(len(self.rows(page)), 3)
        self.assertEqual(re.findall(r'data-label="Predicted Risk Probability">([\d.]+)%', page), ["55", "40", "30"])         # newest first
        self.assertIn("High Preliminary Risk", page)
        self.assertIn("Low Preliminary Risk", page)
        self.assertIn("Preliminary screening", page)
        self.assertIn("Showing 1 to 3 of 3", page)

    def test_every_row_opens_its_own_real_result(self):
        first = self.add_assessment(assessed_at=days_ago(10))
        second = self.add_assessment(assessed_at=days_ago(3))
        page = self.page()
        for assessment_id in (first, second):
            self.assertIn(f'href="/results/{assessment_id}"', page)
            self.assertEqual(self.member.get(f"/results/{assessment_id}").status_code, 200)

    def test_a_person_only_ever_sees_their_own_assessments(self):
        self.add_assessment(probability=0.31, assessed_at=days_ago(5))
        other = self.signed_in(email="ben@example.com", full_name="Ben Cruz")
        self.add_assessment(email="ben@example.com", probability=0.87, assessed_at=days_ago(4))
        self.add_assessment(email="ben@example.com", probability=0.66, assessed_at=days_ago(1))
        mine, theirs = self.page(), self.page(client=other)
        self.assertIn("Showing 1 to 1 of 1", mine)
        self.assertNotIn("87%", mine)
        self.assertNotIn("66%", mine)
        self.assertIn("Showing 1 to 2 of 2", theirs)
        self.assertNotIn("31%", theirs)

    def test_a_long_history_is_split_into_pages_of_ten(self):
        for index in range(23):
            self.add_assessment(probability=0.10 + index / 100, assessed_at=days_ago(100 - index))
        one = self.page()
        self.assertEqual(len(self.rows(one)), 10)
        self.assertIn("Showing 1 to 10 of 23", one)
        self.assertIn("Page 1 of 3", one)
        self.assertIn('rel="next"', one)
        self.assertNotIn('rel="prev"', one)
        three = self.page("/history?page=3")
        self.assertEqual(len(self.rows(three)), 3)
        self.assertIn("Showing 21 to 23 of 23", three)
        self.assertIn('rel="prev"', three)
        self.assertNotIn('rel="next"', three)
        self.assertNotEqual(self.rows(one), self.rows(three))

    def test_an_odd_page_number_never_breaks_the_page(self):
        for index in range(12):
            self.add_assessment(assessed_at=days_ago(50 - index))
        for value in ("0", "-3", "abc", "", "99", "1e9", "2.5"):
            response = self.member.get(f"/history?page={value}")
            self.assertEqual(response.status_code, 200, value)
        self.assertIn("Page 2 of 2", self.page("/history?page=99"))                 # too high goes to the last page
        self.assertIn("Page 1 of 2", self.page("/history?page=abc"))

    def test_a_trend_chart_and_a_first_to_latest_link_only_appear_when_there_are_two_or_more(self):
        first = self.add_assessment(assessed_at=days_ago(30))
        alone = self.page()
        self.assertNotIn("chart-line", alone)
        self.assertNotIn("Compare first and latest", alone)
        latest = self.add_assessment(assessed_at=days_ago(2))
        both = self.page()
        self.assertIn("chart-line", both)
        self.assertIn(f"/history/compare?id={first}&amp;id={latest}", both)

    def test_compare_with_previous_is_offered_on_every_row_except_the_oldest(self):
        self.add_assessment(assessed_at=days_ago(30))
        self.add_assessment(assessed_at=days_ago(20))
        self.add_assessment(assessed_at=days_ago(10))
        self.assertEqual(self.page().count("Compare with previous"), 2)

    def test_the_selection_boxes_and_the_table_are_labelled_for_a_screen_reader(self):
        self.add_assessment(assessed_at=days_ago(30))
        page = self.page()
        self.assertIn("<caption class=\"visually-hidden\">", page)
        self.assertEqual(page.count('<th scope="col"'), 6)
        self.assertRegex(page, r'aria-label="Select the assessment of [A-Z][a-z]{2} \d{1,2}, \d{4}"')
        self.assertIn('aria-live="polite"', page)

    def test_the_page_can_only_read_never_change_a_record(self):
        assessment_id = self.add_assessment(assessed_at=days_ago(30))
        before = self.app.extensions["assessment_store"].list_assessments(self.store.find_by_email("ana@example.com")["user_id"])
        for method in ("post", "put", "delete", "patch"):
            self.assertEqual(getattr(self.member, method)("/history").status_code, 405)
        self.assertEqual(self.member.post("/history/compare").status_code, 405)
        self.assertEqual(self.app.extensions["assessment_store"].list_assessments(self.store.find_by_email("ana@example.com")["user_id"]), before)
        self.assertEqual(self.member.get(f"/results/{assessment_id}").status_code, 200)

    def test_the_rail_and_the_dashboard_lead_to_the_history(self):
        self.add_assessment(assessed_at=days_ago(3))
        dashboard = self.page("/dashboard")
        self.assertIn('href="/history"', dashboard)
        self.assertRegex(self.page(), r'<a[^>]*aria-current="page"[^>]*href="/history"|<a[^>]*href="/history"[^>]*aria-current="page"')
        self.assertEqual(self.member.get("/history").status_code, 200)

    def test_the_result_page_links_to_the_history_and_to_a_detailed_comparison(self):
        self.add_assessment(assessed_at=days_ago(30))
        latest = self.add_assessment(assessed_at=days_ago(2))
        page = self.page(f"/results/{latest}")
        self.assertIn('href="/history"', page)
        self.assertIn("Compare in detail", page)
        link = re.search(r'href="(/history/compare\?[^"]+)"[^>]*>Compare in detail', page).group(1).replace("&amp;", "&")
        self.assertEqual(self.member.get(link).status_code, 200)


@NEEDS_ML
class EligibilityOnTheHistoryTests(HistoryTestCase):
    def test_without_a_waiting_period_a_new_screening_is_available_now(self):
        self.add_assessment(assessed_at=days_ago(0, hours=1))
        page = self.page()
        self.assertIn("Available now", page)
        self.assertIn("Start assessment", page)

    def test_inside_the_waiting_period_the_date_and_the_days_left_are_shown_and_nothing_can_be_started(self):
        self.app.config["REASSESSMENT_DAYS"] = 30
        self.add_assessment(assessed_at=days_ago(5))
        page = self.page()
        self.assertIn("Opens on", page)
        self.assertIn("25 days left", page)
        self.assertNotIn(">Start assessment<", page.split("Your assessments")[0])
        self.assertIn('role="progressbar"', page)
        self.assertIn('aria-valuenow="17"', page)                                    # 5 of 30 days passed

    def test_the_history_and_the_screening_page_always_agree(self):
        self.app.config["REASSESSMENT_DAYS"] = 30
        self.add_assessment(assessed_at=days_ago(5))
        self.assertIn("Opens on", self.page())
        self.assertIn("Your next screening is not open yet", self.page("/screening"))
        self.app.config["REASSESSMENT_DAYS"] = 3
        self.assertIn("Available now", self.page())
        self.assertEqual(self.member.get("/screening").status_code, 200)
        self.assertNotIn("not open yet", self.page("/screening"))

    def test_one_day_before_it_opens_and_the_day_it_opens(self):
        self.app.config["REASSESSMENT_DAYS"] = 30
        self.add_assessment(assessed_at=days_ago(29))
        self.assertIn("1 day left", self.page())
        self.add_assessment(assessed_at=days_ago(0))                                 # a newer assessment restarts the wait
        self.assertIn("30 days left", self.page())

    def test_the_waiting_period_counts_from_the_newest_assessment_not_the_oldest(self):
        self.app.config["REASSESSMENT_DAYS"] = 30
        self.add_assessment(assessed_at=days_ago(90))
        self.add_assessment(assessed_at=days_ago(10))
        self.assertIn("20 days left", self.page())

    def test_the_waiting_page_offers_the_history(self):
        self.app.config["REASSESSMENT_DAYS"] = 30
        self.add_assessment(assessed_at=days_ago(5))
        self.assertIn("View your history", self.page("/screening"))


class HistoryWithoutAModelTests(AppTestCase):
    model = None

    def test_the_saved_assessments_stay_readable_and_screening_is_honestly_not_available(self):
        member = self.signed_in()
        self.add_assessment(assessed_at=days_ago(3))
        page = self.text(member.get("/history"))
        self.assertIn("Showing 1 to 1 of 1", page)
        self.assertIn("Not available yet", page)
        self.assertNotIn(">Start assessment<", page)


@NEEDS_ML
class ComparePageTests(HistoryTestCase):
    def two(self, first=None, second=None, **later):
        a = self.add_assessment(probability=0.30, classification="low", threshold_used=0.5, assessed_at=days_ago(60),
                                inputs=answers() if first is None else first)
        values = {"probability": 0.5525, "classification": "high", "threshold_used": 0.5, "assessed_at": days_ago(2),
                  "inputs": answers(Age=49, Smoking_Status="Former", Diabetes=0) if second is None else second}
        values.update(later)
        b = self.add_assessment(**values)
        return a, b

    def compare(self, a, b, client=None):
        return self.text((client or self.member).get(f"/history/compare?id={a}&id={b}"))

    def test_it_shows_both_assessments_and_what_changed_in_neutral_words(self):
        a, b = self.two()
        page = self.compare(a, b)
        self.assertIn("Earlier:", page)
        self.assertIn("Later:", page)
        self.assertIn("The Predicted Risk Probability went from 30% to 55.2%: 25.2 points higher.", page)
        self.assertIn("The classification changed from Low Preliminary Risk to High Preliminary Risk.", page)
        for gone in ("improved", "worsened", "deteriorat", "getting worse", "getting better", "you have ckd"):
            self.assertNotIn(gone, page.lower())

    def test_the_answers_that_changed_are_listed_and_the_rest_counted(self):
        a, b = self.two()
        page = self.compare(a, b)
        table = page.split("The answers that changed")[1].split("</table>")[0]
        for label, before, after in (("Age", "48 years", "49 years"), ("Smoking", "Never", "Used to"), ("Diabetes", "Yes", "No")):
            self.assertRegex(table, rf"{label}</td>\s*<td[^>]*>{before}</td>\s*<td[^>]*>{after}</td>")
        self.assertEqual(table.split("<tbody>")[1].count("<tr>"), 3)                    # only the three that changed
        self.assertIn("5 other answers did not change.", page)

    def test_the_order_of_the_two_ids_does_not_matter(self):
        a, b = self.two()
        self.member.get("/dashboard")                                                # a waiting flash message is shown once; use it up first
        self.assertEqual(self.compare(a, b), self.compare(b, a))
        page = self.compare(b, a)
        self.assertLess(page.index("Earlier:"), page.index("Later:"))

    def test_when_nothing_changed_it_says_so(self):
        a, b = self.two(second=answers(), probability=0.31, classification="low")
        page = self.compare(a, b)
        self.assertIn("None of the answers changed. All 8 stayed the same.", page)
        self.assertIn("The classification stayed Low Preliminary Risk.", page)
        self.assertIn("went from 30% to 31%: 1 point higher.", page)                    # one point, not "1 points"

    def test_when_the_answers_were_not_saved_nothing_is_guessed(self):
        a = self.add_assessment(assessed_at=days_ago(30))
        b = self.add_assessment(assessed_at=days_ago(3), inputs=answers())
        page = self.compare(a, b)
        self.assertIn("The answers were not saved for one or both of these assessments", page)
        self.assertNotIn("The answers that changed", page)

    def test_results_from_different_versions_of_the_model_carry_a_warning(self):
        a, b = self.two()
        self.assertNotIn("Different model versions", self.compare(a, b))            # both are "test-model"
        c, d = self.two(model_version="another-model")
        page = self.compare(c, d)
        self.assertIn("Different model versions", page)
        self.assertIn("not directly comparable", page)
        self.assertIn("test-model", page)
        self.assertIn("another-model", page)

    def test_an_unrecorded_model_version_is_said_not_hidden(self):
        a = self.add_assessment(assessed_at=days_ago(30), model_version=None, inputs=answers())
        b = self.add_assessment(assessed_at=days_ago(3), inputs=answers())
        page = self.compare(a, b)
        self.assertIn("Model version not recorded", page)
        self.assertIn("Not recorded", page)

    def test_each_side_opens_its_own_full_result(self):
        a, b = self.two()
        page = self.compare(a, b)
        for assessment_id in (a, b):
            self.assertIn(f'href="/results/{assessment_id}"', page)

    def test_the_choice_must_be_exactly_two_different_assessments(self):
        a, b = self.two()
        bad = ["/history/compare", f"/history/compare?id={a}", f"/history/compare?id={a}&id={a}", f"/history/compare?id={a}&id={b}&id={a}",
               "/history/compare?id=x&id=y", f"/history/compare?id={a}&id=", "/history/compare?id=-1&id=2", "/history/compare?id=%20&id=1"]
        for path in bad:
            response = self.member.get(path)
            self.assertEqual(response.status_code, 302, path)
            self.assertEqual(response.headers["Location"], "/history", path)
        self.assertIn("Choose exactly two different assessments to compare.", self.page())

    def test_someone_elses_assessment_gets_the_same_answer_as_one_that_does_not_exist(self):
        mine, _ = self.two()
        other = self.signed_in(email="ben@example.com", full_name="Ben Cruz")
        theirs = self.add_assessment(email="ben@example.com", assessed_at=days_ago(9), inputs=answers(Age=70))
        self.member.get("/dashboard")                                                # use up any waiting flash message so the bodies can be compared
        stranger = self.member.get(f"/history/compare?id={mine}&id={theirs}")
        missing = self.member.get(f"/history/compare?id={mine}&id=99999")
        self.assertEqual((stranger.status_code, missing.status_code), (404, 404))
        self.assertEqual(stranger.get_data(as_text=True), missing.get_data(as_text=True))
        self.assertNotIn("70 years", stranger.get_data(as_text=True))
        # and the other person cannot compare mine either
        self.assertEqual(other.get(f"/history/compare?id={mine}&id={theirs}").status_code, 404)

    def test_a_visitor_and_a_professional_cannot_compare(self):
        a, b = self.two()
        self.assertEqual(self.client.get(f"/history/compare?id={a}&id={b}").status_code, 302)
        doctor = self.signed_in(**self.professional_details())
        self.assertEqual(doctor.get(f"/history/compare?id={a}&id={b}").status_code, 403)

    def test_the_page_carries_the_reminder_that_this_is_not_a_diagnosis(self):
        a, b = self.two()
        page = self.compare(a, b)
        self.assertIn("not a diagnosis", page)
        self.assertIn("different answers", page)
        self.assertIn("different version of the model", page)


if __name__ == "__main__":
    unittest.main()
