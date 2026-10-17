"""
Checks for services/assessments.py: what may be saved as an assessment, and how saved rows become what the dashboard draws.
No database needed. Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from datetime import datetime

os.environ.setdefault("SECRET_KEY", "test-only-secret-key")
os.environ["FLASK_DEBUG"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import assessments, visuals  # noqa: E402
from services.assessment_store import MemoryAssessmentStore  # noqa: E402
from services.user_store import MemoryUserStore  # noqa: E402

MANILA = "Asia/Manila"


def good(**changes):
    values = {"assessment_type": "preliminary", "probability": 0.31, "classification": "high", "threshold_used": 0.21,
              "model_version": "xgboost-2026-09", "assessed_at": datetime(2026, 9, 20, 3, 0, 0)}
    values.update(changes)
    return values


class ValidationTests(unittest.TestCase):
    def test_a_normal_result_is_accepted(self):
        assessments.validate_assessment(good())
        assessments.validate_assessment(good(threshold_used=None, model_version=None))     # both are optional

    def test_impossible_results_are_refused(self):
        bad = [good(assessment_type="lab"), good(classification="moderate"), good(probability=1.2), good(probability=-0.01),
               good(probability=31), good(probability="0.3"), good(probability=True), good(probability=None),
               good(threshold_used=2), good(threshold_used="x"), good(model_version=""), good(model_version="x" * 101),
               good(assessed_at="2026-09-20"), good(assessed_at=None)]
        for values in bad:
            with self.assertRaises(ValueError, msg=str(values)):
                assessments.validate_assessment(values)

    def test_the_two_ends_of_the_probability_range_are_allowed(self):
        assessments.validate_assessment(good(probability=0.0))
        assessments.validate_assessment(good(probability=1.0))

    def test_only_the_two_known_words_exist(self):
        self.assertEqual(assessments.CLASSIFICATIONS, visuals.LEVELS)         # the model and the charts agree on the words


class InputsValidationTests(unittest.TestCase):
    def test_a_normal_snapshot_is_accepted(self):
        assessments.validate_inputs({"Age": 48, "Sex": "Female", "BMI": 27.4, "Diabetes": 1})

    def test_anything_else_is_refused(self):
        for bad in (None, {}, [], "text", {"Age": None}, {"Age": True}, {"Age": float("nan")}, {"Age": [1]}, {1: 2}, {"Age": {"x": 1}},
                    {"Age": "x" * 30000}):
            with self.assertRaises(ValueError, msg=str(bad)[:40]):
                assessments.validate_inputs(bad)

    def test_a_bad_snapshot_means_nothing_is_saved(self):
        users = MemoryUserStore()
        store = MemoryAssessmentStore(users)
        user = users.create_user({"email": "a@example.com", "full_name": "Ana Reyes", "role": "general", "professional": None}, "h", datetime(2026, 1, 1))
        with self.assertRaises(ValueError):
            assessments.record_assessment(store, user, good(), {"Age": None})
        self.assertEqual(store.list_assessments(user), [])


class SavingAndLoadingTests(unittest.TestCase):
    def setUp(self):
        self.users = MemoryUserStore()
        self.store = MemoryAssessmentStore(self.users)
        values = {"email": "ana@example.com", "full_name": "Ana Reyes", "role": "general", "professional": None}
        self.ana = self.users.create_user(values, "h", datetime(2026, 1, 1))
        self.ben = self.users.create_user({**values, "email": "ben@example.com", "full_name": "Ben Lim"}, "h", datetime(2026, 1, 1))

    def test_a_result_that_makes_no_sense_is_never_saved(self):
        with self.assertRaises(ValueError):
            assessments.record_assessment(self.store, self.ana, good(probability=4))
        self.assertEqual(self.store.list_assessments(self.ana), [])

    def test_saved_rows_come_back_as_percentages_words_and_local_dates(self):
        assessments.record_assessment(self.store, self.ana, good())
        record = assessments.load_records(self.store, self.ana, MANILA)[0]
        self.assertEqual((record["probability"], record["threshold"], record["level"], record["type"]),
                         (31.0, 21.0, "high", "Preliminary screening"))
        self.assertEqual(record["model_version"], "xgboost-2026-09")
        visuals.summarize_assessments([record])                              # and the charts accept it as it is

    def test_a_missing_threshold_stays_missing(self):
        assessments.record_assessment(self.store, self.ana, good(threshold_used=None, model_version=None))
        record = assessments.load_records(self.store, self.ana, MANILA)[0]
        self.assertIsNone(record["threshold"])
        self.assertIsNone(record["model_version"])

    def test_the_date_is_the_day_where_the_person_lives_not_the_day_in_utc(self):
        # 23:30 UTC on the 19th is already 7:30 the next morning in Manila (UTC+8).
        assessments.record_assessment(self.store, self.ana, good(assessed_at=datetime(2026, 9, 19, 23, 30, 0)))
        self.assertEqual(str(assessments.load_records(self.store, self.ana, MANILA)[0]["date"]), "2026-09-20")
        self.assertEqual(str(assessments.load_records(self.store, self.ana, "UTC")[0]["date"]), "2026-09-19")
        # 15:59 UTC is 23:59 in Manila (same day); 16:00 UTC is midnight, the next day.
        self.store._rows.clear()
        assessments.record_assessment(self.store, self.ana, good(assessed_at=datetime(2026, 9, 20, 15, 59, 0)))
        assessments.record_assessment(self.store, self.ana, good(assessed_at=datetime(2026, 9, 20, 16, 0, 0)))
        dates = [str(r["date"]) for r in assessments.load_records(self.store, self.ana, MANILA)]
        self.assertEqual(dates, ["2026-09-21", "2026-09-20"])                # newest first

    def test_each_person_only_ever_gets_their_own_records(self):
        assessments.record_assessment(self.store, self.ana, good(probability=0.31))
        assessments.record_assessment(self.store, self.ben, good(probability=0.05, classification="low"))
        ana = assessments.load_records(self.store, self.ana, MANILA)
        ben = assessments.load_records(self.store, self.ben, MANILA)
        self.assertEqual([r["probability"] for r in ana], [31.0])
        self.assertEqual([r["probability"] for r in ben], [5.0])
        self.assertEqual(assessments.load_records(self.store, 987654, MANILA), [])

    def test_labels_for_both_kinds(self):
        pre = assessments.record_assessment(self.store, self.ana, good())
        assessments.record_assessment(self.store, self.ana, good(assessment_type="enhanced", source_assessment_id=pre))
        self.assertEqual(assessments.load_records(self.store, self.ana, MANILA)[0]["type"], "Enhanced screening")

    def test_an_enhanced_assessment_must_record_which_preliminary_one_it_extends(self):
        with self.assertRaisesRegex(ValueError, "source_assessment_id"):
            assessments.record_assessment(self.store, self.ana, good(assessment_type="enhanced"))


if __name__ == "__main__":
    unittest.main()
