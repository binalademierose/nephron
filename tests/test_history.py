"""
Checks for services/history.py: pagination and the comparison of two assessments. No Flask and no database.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import history, screening_contract  # noqa: E402

CATALOG = screening_contract.load_catalog()


class PaginateTests(unittest.TestCase):
    def test_pages_of_ten_with_the_numbers_shown_to_the_reader(self):
        items = list(range(25))
        first = history.paginate(items, 1)
        self.assertEqual((first["items"], first["pages"], first["total"], first["first_number"], first["last_number"]),
                         (list(range(10)), 3, 25, 1, 10))
        self.assertEqual((first["has_previous"], first["has_next"]), (False, True))
        last = history.paginate(items, 3)
        self.assertEqual((last["items"], last["first_number"], last["last_number"], last["has_next"]), (list(range(20, 25)), 21, 25, False))

    def test_a_page_number_that_is_too_low_or_too_high_moves_to_the_nearest_real_page(self):
        items = list(range(25))
        self.assertEqual(history.paginate(items, 0)["page"], 1)
        self.assertEqual(history.paginate(items, -4)["page"], 1)
        self.assertEqual(history.paginate(items, 99)["page"], 3)

    def test_an_empty_list_is_one_empty_page(self):
        empty = history.paginate([], 1)
        self.assertEqual((empty["items"], empty["pages"], empty["total"], empty["first_number"], empty["last_number"]), ([], 1, 0, 0, 0))

    def test_exactly_one_full_page_has_no_second_page(self):
        self.assertEqual(history.paginate(list(range(10)), 1)["pages"], 1)
        self.assertEqual(history.paginate(list(range(11)), 1)["pages"], 2)


def inputs(**changes):
    values = {"Country": "Other", "Sex": "Female", "Ethnicity": "Asian", "Age": 48, "BMI": 27.3, "height_cm": 160.0, "weight_kg": 70.0,
              "Obesity": 0, "Diabetes": 1, "Hypertension": 0, "Smoking_Status": "Never"}
    values.update(changes)
    return values


def row(assessment_id, moment, probability, classification, threshold=0.5, version="model-1", saved=None):
    return {"assessment_id": assessment_id, "assessment_type": "preliminary", "probability": probability, "classification": classification,
            "threshold_used": threshold, "model_version": version, "assessed_at": moment, "inputs": saved}


EARLY = datetime(2026, 3, 1, 4, 0, 0)
LATE = datetime(2026, 9, 1, 4, 0, 0)


class CompareTests(unittest.TestCase):
    def compare(self, first, second):
        return history.compare(CATALOG, first, second, "Asia/Manila")

    def test_the_older_one_is_always_the_earlier_whichever_order_they_are_given_in(self):
        old, new = row(1, EARLY, 0.30, "low", saved=inputs()), row(2, LATE, 0.55, "high", saved=inputs())
        for a, b in ((old, new), (new, old)):
            result = self.compare(a, b)
            self.assertEqual((result["earlier"]["assessment_id"], result["later"]["assessment_id"]), (1, 2))

    def test_the_difference_in_points_and_a_change_of_classification(self):
        result = self.compare(row(1, EARLY, 0.30, "low", saved=inputs()), row(2, LATE, 0.5525, "high", saved=inputs()))
        self.assertEqual((result["points"], result["direction"], result["level_changed"]), (25.2, "higher", True))
        down = self.compare(row(1, EARLY, 0.60, "high", saved=inputs()), row(2, LATE, 0.40, "low", saved=inputs()))
        self.assertEqual((down["points"], down["direction"]), (20.0, "lower"))
        same = self.compare(row(1, EARLY, 0.30, "low", saved=inputs()), row(2, LATE, 0.30, "low", saved=inputs()))
        self.assertEqual((same["points"], same["direction"], same["level_changed"]), (0.0, "same", False))

    def test_only_the_answers_that_changed_are_listed_in_words_and_the_rest_are_counted(self):
        result = self.compare(row(1, EARLY, 0.3, "low", saved=inputs()),
                              row(2, LATE, 0.4, "low", saved=inputs(Age=49, Smoking_Status="Former", Diabetes=0)))
        changed = {c["label"]: (c["earlier"], c["later"]) for c in result["changes"]}
        self.assertEqual(changed, {"Age": ("48 years", "49 years"), "Smoking": ("Never", "Used to"), "Diabetes": ("Yes", "No")})
        self.assertEqual(result["unchanged"], 5)                    # Country, Sex, Ethnicity, BMI and Hypertension
        self.assertTrue(result["answers_available"])

    def test_a_derived_answer_is_not_listed_twice_and_a_new_bmi_shows_its_height_and_weight(self):
        result = self.compare(row(1, EARLY, 0.3, "low", saved=inputs()),
                              row(2, LATE, 0.4, "low", saved=inputs(BMI=30.5, Obesity=1, weight_kg=78.1)))
        labels = [c["label"] for c in result["changes"]]
        self.assertEqual(labels, ["Body mass index"])                                # Obesity follows the BMI; it is not a separate answer
        self.assertEqual(result["changes"][0]["later"], "30.5 (height 160 cm, weight 78.1 kg)")

    def test_when_no_answer_changed_it_says_so_with_an_empty_list(self):
        result = self.compare(row(1, EARLY, 0.3, "low", saved=inputs()), row(2, LATE, 0.4, "low", saved=inputs()))
        self.assertEqual(result["changes"], [])
        self.assertGreater(result["unchanged"], 0)

    def test_answers_are_only_compared_when_both_assessments_saved_them(self):
        for first, second in ((None, inputs()), (inputs(), None), (None, None), ({}, inputs())):
            result = self.compare(row(1, EARLY, 0.3, "low", saved=first), row(2, LATE, 0.4, "low", saved=second))
            self.assertFalse(result["answers_available"])
            self.assertEqual((result["changes"], result["unchanged"]), ([], 0))            # nothing is guessed

    def test_a_question_only_one_of_them_answered_is_not_compared(self):
        partial = {k: v for k, v in inputs().items() if k != "Smoking_Status"}
        result = self.compare(row(1, EARLY, 0.3, "low", saved=partial), row(2, LATE, 0.4, "low", saved=inputs()))
        self.assertNotIn("Smoking", [c["label"] for c in result["changes"]])

    def test_the_versions_of_the_model_are_compared_before_the_probabilities_can_be_trusted(self):
        self.assertEqual(self.compare(row(1, EARLY, 0.3, "low", version="a"), row(2, LATE, 0.4, "low", version="a"))["model"], "same")
        self.assertEqual(self.compare(row(1, EARLY, 0.3, "low", version="a"), row(2, LATE, 0.4, "low", version="b"))["model"], "different")
        self.assertEqual(self.compare(row(1, EARLY, 0.3, "low", version=None), row(2, LATE, 0.4, "low", version="b"))["model"], "unknown")
        self.assertEqual(self.compare(row(1, EARLY, 0.3, "low", version=None), row(2, LATE, 0.4, "low", version=None))["model"], "unknown")

    def test_different_thresholds_are_noticed(self):
        self.assertTrue(self.compare(row(1, EARLY, 0.3, "low", 0.5), row(2, LATE, 0.4, "low", 0.5))["same_threshold"])
        self.assertFalse(self.compare(row(1, EARLY, 0.3, "low", 0.5), row(2, LATE, 0.4, "low", 0.4))["same_threshold"])

    def test_two_results_on_the_same_day_are_ordered_by_the_time_and_then_by_number(self):
        a, b = row(5, LATE, 0.3, "low"), row(4, LATE, 0.4, "low")
        self.assertEqual(self.compare(a, b)["earlier"]["assessment_id"], 4)
        c = row(6, datetime(2026, 9, 1, 9, 0, 0), 0.3, "low")
        self.assertEqual(self.compare(c, a)["earlier"]["assessment_id"], 5)


if __name__ == "__main__":
    unittest.main()
