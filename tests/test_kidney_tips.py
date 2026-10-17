"""
Checks for services/kidney_tips.py: tips match the real conditions they claim to, never invent a claim, and
every one carries a real source. Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import kidney_tips  # noqa: E402


def all_tip_texts(grouped):
    return [tip["text"] for group in grouped for tip in group["tips"]]


class StructureTests(unittest.TestCase):
    def test_every_tip_has_a_real_source(self):
        for tip in kidney_tips.TIPS:
            self.assertTrue(tip.get("source"), tip["id"])

    def test_every_tip_is_always_shown_or_has_a_condition_not_both_missing(self):
        for tip in kidney_tips.TIPS:
            self.assertTrue(tip.get("always") or callable(tip.get("condition")), tip["id"])

    def test_no_tip_ever_instructs_stopping_a_medication(self):
        for tip in kidney_tips.TIPS:
            lowered = tip["text"].lower()
            self.assertNotIn("stop taking", lowered, tip["id"])
            self.assertNotIn("stop your", lowered, tip["id"])

    def test_hydration_never_states_a_single_universal_target(self):
        # guards against ever rewriting this into an unqualified "drink 8 glasses a day" style claim
        hydration = [tip for tip in kidney_tips.TIPS if tip["category"] == "hydration" and tip.get("always")]
        self.assertTrue(any("no one safe number" in tip["text"] or "varies" in tip["text"] for tip in hydration))


class MatchingTests(unittest.TestCase):
    def test_always_tips_appear_for_a_blank_preliminary_result(self):
        grouped = kidney_tips.personalized_tips({}, "low")
        texts = all_tip_texts(grouped)
        self.assertTrue(any("Never stop, start, or change" in t for t in texts))
        self.assertTrue(any("150 minutes" in t for t in texts))

    def test_diabetes_triggers_the_sugar_tip(self):
        grouped = kidney_tips.personalized_tips({"Diabetes": 1}, "low")
        self.assertTrue(any("sugar" in t.lower() for t in all_tip_texts(grouped)))

    def test_diabetes_medication_triggers_its_own_adherence_tip_but_only_then(self):
        with_med = all_tip_texts(kidney_tips.personalized_tips({"Diabetes_Medication": 1}, "low"))
        without_med = all_tip_texts(kidney_tips.personalized_tips({}, "low"))
        self.assertTrue(any("diabetes medication" in t.lower() for t in with_med))
        self.assertFalse(any("diabetes medication" in t.lower() for t in without_med))

    def test_hypertension_triggers_the_sodium_tip(self):
        grouped = kidney_tips.personalized_tips({"Hypertension": 1}, "low")
        self.assertTrue(any("sodium" in t.lower() for t in all_tip_texts(grouped)))

    def test_high_classification_alone_also_triggers_the_sodium_tip(self):
        grouped = kidney_tips.personalized_tips({}, "high")
        self.assertTrue(any("sodium" in t.lower() for t in all_tip_texts(grouped)))

    def test_a_lab_only_tip_never_appears_for_a_preliminary_only_assessment(self):
        # Potassium is never present in a Preliminary assessment's own inputs
        grouped = kidney_tips.personalized_tips({"Diabetes": 1}, "low")
        self.assertFalse(any("potassium" in t.lower() for t in all_tip_texts(grouped)))

    def test_high_potassium_triggers_its_tip_but_normal_potassium_does_not(self):
        high = all_tip_texts(kidney_tips.personalized_tips({"Potassium": 5.6}, "low"))
        normal = all_tip_texts(kidney_tips.personalized_tips({"Potassium": 4.2}, "low"))
        self.assertTrue(any("potassium" in t.lower() for t in high))
        self.assertFalse(any("potassium" in t.lower() for t in normal))

    def test_low_egfr_triggers_both_a_diet_and_a_follow_up_tip(self):
        grouped = kidney_tips.personalized_tips({"eGFR": 45.0}, "low")
        categories = {g["category"] for g in grouped}
        self.assertIn("diet", categories)
        self.assertIn("follow_up", categories)

    def test_normal_egfr_does_not_trigger_the_low_egfr_tips(self):
        grouped = kidney_tips.personalized_tips({"eGFR": 95.0}, "low")
        texts = all_tip_texts(grouped)
        self.assertFalse(any("filtration rate" in t for t in texts))

    def test_nsaid_usage_triggers_its_own_medication_tip(self):
        grouped = kidney_tips.personalized_tips({"NSAID_Usage": 1}, "low")
        self.assertTrue(any("nsaid" in t.lower() for t in all_tip_texts(grouped)))

    def test_ace_and_arb_together_triggers_the_combination_caution(self):
        both = all_tip_texts(kidney_tips.personalized_tips({"ACE_Inhibitor": 1, "ARB": 1}, "low"))
        just_one = all_tip_texts(kidney_tips.personalized_tips({"ACE_Inhibitor": 1}, "low"))
        self.assertTrue(any("combining these two" in t for t in both))
        self.assertFalse(any("combining these two" in t for t in just_one))

    def test_current_smoker_gets_the_smoking_tip_former_smoker_does_not(self):
        current = all_tip_texts(kidney_tips.personalized_tips({"Smoking_Status": "Current"}, "low"))
        former = all_tip_texts(kidney_tips.personalized_tips({"Smoking_Status": "Former"}, "low"))
        self.assertTrue(any("stopping smoking" in t.lower() for t in current))
        self.assertFalse(any("stopping smoking" in t.lower() for t in former))

    def test_heart_failure_overrides_general_hydration_with_its_own_caution(self):
        grouped = kidney_tips.personalized_tips({"Heart_Failure": 1}, "low")
        texts = all_tip_texts(grouped)
        self.assertTrue(any("fluid limit" in t for t in texts))

    def test_empty_categories_are_left_out_not_padded(self):
        grouped = kidney_tips.personalized_tips({}, "low")
        for group in grouped:
            self.assertGreater(len(group["tips"]), 0)

    def test_a_missing_inputs_dict_does_not_crash(self):
        grouped = kidney_tips.personalized_tips(None, "low")
        self.assertTrue(len(grouped) > 0)   # the "always" tips still show


if __name__ == "__main__":
    unittest.main()
