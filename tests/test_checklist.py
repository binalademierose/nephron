"""Checks for services/checklist.py: merges services/kidney_tips.py's own matching with a real completion state."""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import checklist  # noqa: E402
from services.checklist_store import MemoryChecklistStore  # noqa: E402

NOW = datetime(2026, 9, 20, 10, 0, 0)


class ChecklistTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryChecklistStore()

    def test_everything_starts_incomplete(self):
        grouped = checklist.for_user(self.store, {}, "low", 1)
        for group in grouped:
            for tip in group["tips"]:
                self.assertFalse(tip["is_complete"])
            self.assertEqual(group["done_count"], 0)

    def test_toggling_complete_shows_up_on_the_matching_tip_only(self):
        grouped = checklist.for_user(self.store, {"Diabetes": 1}, "low", 1)
        some_id = grouped[0]["tips"][0]["id"]
        checklist.toggle(self.store, 1, some_id, True, NOW)
        grouped_again = checklist.for_user(self.store, {"Diabetes": 1}, "low", 1)
        flat = {tip["id"]: tip["is_complete"] for group in grouped_again for tip in group["tips"]}
        self.assertTrue(flat[some_id])
        self.assertEqual(sum(1 for v in flat.values() if v), 1)

    def test_toggling_incomplete_again_reverses_it(self):
        grouped = checklist.for_user(self.store, {}, "low", 1)
        some_id = grouped[0]["tips"][0]["id"]
        checklist.toggle(self.store, 1, some_id, True, NOW)
        checklist.toggle(self.store, 1, some_id, False, NOW)
        grouped_again = checklist.for_user(self.store, {}, "low", 1)
        flat = {tip["id"]: tip["is_complete"] for group in grouped_again for tip in group["tips"]}
        self.assertFalse(flat[some_id])

    def test_done_and_total_counts_are_accurate_per_group(self):
        grouped = checklist.for_user(self.store, {"Hypertension": 1}, "high", 1)
        diet_group = next(g for g in grouped if g["category"] == "diet")
        checklist.toggle(self.store, 1, diet_group["tips"][0]["id"], True, NOW)
        grouped_again = checklist.for_user(self.store, {"Hypertension": 1}, "high", 1)
        diet_group_again = next(g for g in grouped_again if g["category"] == "diet")
        self.assertEqual(diet_group_again["done_count"], 1)
        self.assertEqual(diet_group_again["total_count"], len(diet_group_again["tips"]))

    def test_progress_sums_across_every_group(self):
        grouped = checklist.for_user(self.store, {}, "low", 1)
        total_tips = sum(len(g["tips"]) for g in grouped)
        checklist.toggle(self.store, 1, grouped[0]["tips"][0]["id"], True, NOW)
        grouped_again = checklist.for_user(self.store, {}, "low", 1)
        done, total = checklist.progress(grouped_again)
        self.assertEqual(done, 1)
        self.assertEqual(total, total_tips)

    def test_one_persons_completions_do_not_affect_another(self):
        grouped = checklist.for_user(self.store, {}, "low", 1)
        some_id = grouped[0]["tips"][0]["id"]
        checklist.toggle(self.store, 1, some_id, True, NOW)
        other_grouped = checklist.for_user(self.store, {}, "low", 2)
        flat = {tip["id"]: tip["is_complete"] for group in other_grouped for tip in group["tips"]}
        self.assertFalse(flat[some_id])


if __name__ == "__main__":
    unittest.main()
