"""
Checks for services/community_stats.py - Nephron's own anonymous counts of people living in the Philippines, and
the gender count plot - plus the store method behind them and where they appear (both dashboards and the admin).
Run everything with:   python -m unittest discover -s tests -v
"""
import json
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helpers import AppTestCase  # noqa: E402
from services import community_stats, screening_contract  # noqa: E402
from services.assessment_store import MemoryAssessmentStore, _profile_only  # noqa: E402
from services.user_store import MemoryUserStore  # noqa: E402

CATALOG = screening_contract.load_catalog()
NOW = datetime(2026, 10, 9, 2, 0, 0)


def person(level, gender="Female", country="Philippines", age=40):
    return {"level": level, "gender": gender, "country": country, "age": age}


class RiskSummaryTests(unittest.TestCase):
    def test_only_people_living_in_the_philippines_are_counted(self):
        profiles = [person("high"), person("low"), person("high", country="USA"), person("low", country=None)]
        summary = community_stats.philippines(profiles, CATALOG, min_people=1)["risk"]
        self.assertEqual((summary["people"], summary["high"], summary["low"], summary["high_percent"]), (2, 1, 1, 50))

    def test_nothing_is_shown_until_there_are_enough_people(self):
        few = community_stats.philippines([person("high")] * 4, CATALOG)
        self.assertFalse(few["risk"]["enough"])
        self.assertIsNone(few["gender"])
        self.assertTrue(community_stats.philippines([person("high")] * 5, CATALOG)["risk"]["enough"])

    def test_no_people_gives_zeroes_not_an_error(self):
        summary = community_stats.risk_summary([], min_people=1)
        self.assertEqual((summary["people"], summary["high_percent"], summary["enough"]), (0, 0, False))


class GenderCountPlotTests(unittest.TestCase):
    def test_groups_follow_the_forms_own_order_with_counts_and_shares(self):
        profiles = [person("high", "Gay man")] * 3 + [person("low", "Female")] * 4 + [person("high", "Female")] * 2
        rows = community_stats.by_gender(profiles, CATALOG)["rows"]
        self.assertEqual([r["label"] for r in rows], ["Female", "Gay man"])
        female, gay = rows
        self.assertEqual((female["people"], female["high"], female["high_percent"], female["bar"]), (6, 2, 33, 100))
        self.assertEqual((gay["people"], gay["high"], gay["high_percent"], gay["bar"]), (3, 3, 100, 50))

    def test_a_lone_small_group_is_left_out_and_counted_as_hidden(self):
        profiles = [person("low", "Female")] * 5 + [person("high", "Non-binary")]
        data = community_stats.by_gender(profiles, CATALOG)
        self.assertEqual([r["label"] for r in data["rows"]], ["Female"])
        self.assertEqual(data["hidden"], 1)                      # that one person's result is never shown

    def test_several_small_groups_are_combined_when_together_they_are_big_enough(self):
        profiles = [person("low", "Female")] * 5 + [person("high", "Non-binary")] * 2 + [person("low", "Lesbian woman")] * 2
        data = community_stats.by_gender(profiles, CATALOG)
        other = data["rows"][-1]
        self.assertEqual((other["label"], other["people"], other["high"], other["folded"]), ("Other answers", 4, 2, 2))
        self.assertEqual(data["hidden"], 0)

    def test_a_professionals_own_patients_are_shown_group_by_group(self):
        data = community_stats.by_gender([person("high", "Non-binary"), person("low", "Male")], CATALOG, min_group=None)
        self.assertEqual({r["label"] for r in data["rows"]}, {"Non-binary", "Male"})
        self.assertEqual(data["hidden"], 0)

    def test_a_screening_saved_before_gender_was_asked_counts_by_its_sex(self):
        self.assertEqual(_profile_only(json.dumps({"Sex": "Male", "Age": 50, "Country": "Philippines"}))["gender"], "Male")
        self.assertEqual(_profile_only(json.dumps({"Sex": "Male", "Gender": "Gay man"}))["gender"], "Gay man")
        self.assertEqual(_profile_only(None), {"age": None, "country": None, "gender": None})
        self.assertEqual(_profile_only("not json")["gender"], None)


class StoreTests(unittest.TestCase):
    def test_latest_profiles_keeps_only_the_latest_result_and_three_answers(self):
        users = MemoryUserStore()
        store = MemoryAssessmentStore(users)
        user_id = users.create_user({"email": "a@example.com", "full_name": "A", "role": "general", "professional": None}, "h", NOW)
        result = {"assessment_type": "preliminary", "probability": 0.2, "threshold_used": 0.5, "model_version": "v1", "assessed_at": NOW}
        store.add_assessment(user_id, {**result, "classification": "low"}, {"Age": 40, "Country": "USA", "Gender": "Female", "Sex": "Female"})
        store.add_assessment(user_id, {**result, "classification": "high"},
                             {"Age": 41, "Country": "Philippines", "Gender": "Lesbian woman", "Sex": "Female", "Diabetes": 1})
        self.assertEqual(store.latest_profiles(), [{"level": "high", "age": 41, "country": "Philippines", "gender": "Lesbian woman"}])
        self.assertEqual(store.latest_per_person(), [("high", 41)])          # the admin's age view is unchanged


class OnTheDashboardsTests(AppTestCase):
    """The community cards appear for a General User, a professional and the administrator."""
    model = True

    def _screen_people(self, genders):
        store = self.app.extensions["assessment_store"]
        for index, (gender, level) in enumerate(genders):
            user_id = self.store.create_user({"email": f"p{index}@example.com", "full_name": f"Person {index}", "role": "general",
                                              "professional": None}, "h", NOW)
            store.add_assessment(user_id, {"assessment_type": "preliminary", "probability": 0.8 if level == "high" else 0.2,
                                           "classification": level, "threshold_used": 0.5, "model_version": "v1", "assessed_at": NOW},
                                 {"Age": 40, "Country": "Philippines", "Gender": gender, "Sex": "Male"})

    def test_the_general_users_dashboard_shows_the_philippines_and_no_us_figures(self):
        browser = self.signed_in()
        self._screen_people([("Male", "high"), ("Male", "low"), ("Male", "low"), ("Gay man", "high"), ("Gay man", "high"), ("Gay man", "low")])
        page = self.text(browser.get("/dashboard"))
        self.assertIn("Kidney health in the Philippines", page)
        self.assertIn("Nephron users in the Philippines", page)
        self.assertIn("<strong>3 of 6</strong> people screened who live in the Philippines are at higher risk", page)
        self.assertIn('aria-label="Gay man: 3 people, 2 at higher risk"', page)
        self.assertIn("7 million", page)
        for gone in ("US adults", "1 in 7", "All US adults"):
            self.assertNotIn(gone, page)

    def test_with_too_few_people_the_community_cards_wait_honestly(self):
        browser = self.signed_in()
        self._screen_people([("Male", "high")])
        page = self.text(browser.get("/dashboard"))
        self.assertIn("Shown once 5 people living in the Philippines have a screening result.", page)
        self.assertNotIn("Male: 1 people", page)

    def test_the_professional_dashboard_shows_the_same_community_picture(self):
        professional = self.signed_in(**self.professional_details())
        self._screen_people([("Female", "high")] * 3 + [("Male", "low")] * 3)
        page = self.text(professional.get("/professional"))
        self.assertIn("Kidney risk in the Philippines, on Nephron", page)
        self.assertIn('aria-label="Female: 3 people, 3 at higher risk"', page)

    def test_the_administrator_sees_the_philippines_totals_by_gender(self):
        admin = self.signed_in(email="admin@example.com", full_name="Site Admin")
        self.store.set_admin(self.store.find_by_email("admin@example.com")["user_id"], True)
        self._screen_people([("Female", "high")] * 3 + [("Non-binary", "low")])
        page = self.text(admin.get("/admin"))
        self.assertIn("People living in the Philippines", page)
        self.assertIn('aria-label="Female: 3 people, 3 at higher risk"', page)
        self.assertNotIn("Non-binary", page.split("People living in the Philippines")[1].split("</section>")[0])   # 1 person: left out
        self.assertIn("1 person in smaller groups not shown", page)


if __name__ == "__main__":
    unittest.main()
