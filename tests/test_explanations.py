"""
Checks for services/explanations.py: which factors are shown for one person's result, and the words used for them.
No model and no database are needed: the effects are made up here, the rules are what is tested.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import explanations, screening_contract  # noqa: E402

CATALOG = screening_contract.load_catalog()
ANSWERS = {"Diabetes": 1, "Age": 78, "Hypertension": 1, "Physical_Activity_Level": "Active", "Smoking_Status": "Never", "BMI": 27.3,
           "height_cm": 160.0, "weight_kg": 70.0, "Obesity": 0, "Country": "Other"}


def effects(**values):
    return [{"name": name, "effect": value} for name, value in values.items()]


class BuildTests(unittest.TestCase):
    def names(self, items):
        return [(i["label"], i["answer"]) for i in items]

    def test_answers_that_raised_and_lowered_the_estimate_go_to_separate_lists_strongest_first(self):
        result = explanations.build(CATALOG, effects(Diabetes=1.9, Age=1.1, Hypertension=0.6, Physical_Activity_Level=-0.4), ANSWERS)
        self.assertEqual(self.names(result["raises"]), [("Diabetes", "Yes"), ("Age", "78 years"), ("High blood pressure", "Yes")])
        self.assertEqual(self.names(result["lowers"]), [("Physical activity", "Active")])
        self.assertTrue(all(i["direction"] == "raises" for i in result["raises"]))
        self.assertTrue(all(i["direction"] == "lowers" for i in result["lowers"]))

    def test_both_lists_share_one_scale_so_a_bar_means_the_same_thing_in_each_card(self):
        result = explanations.build(CATALOG, effects(Diabetes=1.9, Age=1.1, Hypertension=0.6, Physical_Activity_Level=-0.4), ANSWERS)
        self.assertEqual([i["share"] for i in result["raises"]], [100, 58, 32])
        self.assertEqual([i["share"] for i in result["lowers"]], [21])                      # 0.4 of the overall biggest (1.9), not of its own card
        bigger_below = explanations.build(CATALOG, effects(Physical_Activity_Level=-2.0, Diabetes=1.0), ANSWERS)
        self.assertEqual((bigger_below["lowers"][0]["share"], bigger_below["raises"][0]["share"]), (100, 50))

    def test_each_card_shows_at_most_five_on_its_own(self):
        many = effects(Diabetes=2.0, Age=1.5, Hypertension=1.0, Smoking_Status=0.9, Country=0.8, BMI=0.7,
                       Physical_Activity_Level=-1.9, Obesity=-1.4, Sex=-1.0, Statin=-0.9, ARB=-0.8, Diuretic=-0.7)
        every = {**ANSWERS, "Sex": "Female", "Statin": 0, "ARB": 0, "Diuretic": 0}
        result = explanations.build(CATALOG, many, every)
        self.assertEqual(len(result["raises"]), 5)
        self.assertEqual(len(result["lowers"]), 5)

    def test_tiny_effects_are_left_out_measured_against_the_biggest_effect_of_either_kind(self):
        result = explanations.build(CATALOG, effects(Diabetes=2.0, Age=0.5, Hypertension=-0.05, Smoking_Status=-0.01), ANSWERS)
        self.assertEqual([i["name"] for i in result["raises"]], ["Diabetes", "Age"])
        self.assertEqual([i["name"] for i in result["lowers"]], [])                         # 2.5% and 0.5% of the biggest

    def test_a_factor_whose_answer_was_not_saved_is_never_shown_or_guessed(self):
        result = explanations.build(CATALOG, effects(Diabetes=2.0, Statin=1.5, Age=-1.0, Diuretic=-0.9), ANSWERS)    # Statin, Diuretic not saved
        shown = [i["name"] for i in result["raises"] + result["lowers"]]
        self.assertEqual(shown, ["Diabetes", "Age"])

    def test_nothing_honest_to_show_gives_none(self):
        self.assertIsNone(explanations.build(CATALOG, [], ANSWERS))
        self.assertIsNone(explanations.build(CATALOG, effects(Diabetes=0.0, Age=0.0), ANSWERS))
        self.assertIsNone(explanations.build(CATALOG, effects(Statin=1.0), ANSWERS))

    def test_when_only_one_kind_exists_the_other_card_is_empty_and_says_so(self):
        result = explanations.build(CATALOG, effects(Diabetes=1.0, Age=0.6), ANSWERS)
        self.assertEqual(result["lowers"], [])
        self.assertEqual(result["summary"]["lowers"], [])
        self.assertIn("None of your answers lowered the estimate", result["empty"]["lowers"])
        self.assertIn("None of your answers raised the estimate", result["empty"]["raises"])
        only_lowering = explanations.build(CATALOG, effects(Physical_Activity_Level=-1.0), ANSWERS)
        self.assertEqual(only_lowering["raises"], [])

    def test_each_card_has_its_own_short_explanation(self):
        result = explanations.build(CATALOG, effects(Diabetes=1.9, Age=1.1, Hypertension=0.6, Physical_Activity_Level=-0.4, Smoking_Status=-0.3), ANSWERS)
        self.assertEqual(result["summary"]["raises"], ["Diabetes raised the estimate the most: your answer was Yes.",
                                                         "Next came Age (78 years) and High blood pressure (Yes)."])
        self.assertEqual(result["summary"]["lowers"], ["Physical activity lowered the estimate the most: your answer was Active.",
                                                         "Next came Smoking (Never)."])

    def test_one_factor_in_a_card_gives_one_sentence(self):
        result = explanations.build(CATALOG, effects(Diabetes=1.0), ANSWERS)
        self.assertEqual(len(result["summary"]["raises"]), 1)

    def test_the_caveat_is_shared_and_always_there(self):
        result = explanations.build(CATALOG, effects(Diabetes=1.0), ANSWERS)
        self.assertIn("not medical advice", result["caveat"])
        self.assertIn("does not show what caused", result["caveat"])
        self.assertIn("in either direction", result["caveat"])                               # one scale for both cards

    def test_the_words_never_claim_a_diagnosis_a_cause_or_a_confidence(self):
        result = explanations.build(CATALOG, effects(Diabetes=1.9, Age=1.1, Physical_Activity_Level=-0.5), ANSWERS)
        text = " ".join(result["summary"]["raises"] + result["summary"]["lowers"] + [result["caveat"], explanations.UNAVAILABLE, *result["empty"].values()]).lower()
        for banned in ("you have ckd", "diagnos" + "ed with", "confidence", "because you have", "you should", "cures", "causes your"):
            self.assertNotIn(banned, text)

    def test_bmi_and_the_derived_obesity_read_naturally(self):
        result = explanations.build(CATALOG, effects(BMI=1.0, Obesity=-0.5), ANSWERS)
        self.assertEqual(self.names(result["raises"]), [("Body mass index", "27.3 (height 160 cm, weight 70 kg)")])
        self.assertEqual(self.names(result["lowers"]), [("Obesity (from BMI)", "No")])
        self.assertEqual(result["summary"]["raises"], ["Body mass index raised the estimate the most: your answer was 27.3."])   # brief in a sentence


class Model:
    """Just enough of a model for explain_saved_result()."""

    def __init__(self, ready=True, can_explain=True, version="v1", effects_=None, probability=0.6, raises=None):
        self.ready, self.can_explain, self.version = ready, can_explain, version
        self.metadata = {"features": ["Diabetes", "Age"]}
        self._effects, self._probability, self._raises = effects_ or effects(Diabetes=1.0, Age=0.5), probability, raises
        self.asked = []

    def explain(self, values):
        self.asked.append(values)
        if self._raises:
            raise self._raises
        if any(value is None for value in values.values()):        # a real model refuses a gap; this stub does too
            raise ValueError("a required value is missing")
        return {"probability": self._probability, "effects": self._effects}


def saved(**changes):
    row = {"model_version": "v1", "probability": 0.6, "inputs": {"Diabetes": 1, "Age": 78, "height_cm": 160.0}}
    row.update(changes)
    return row


class SavedResultTests(unittest.TestCase):
    def test_a_saved_result_is_explained_from_its_own_saved_answers(self):
        model = Model()
        result = explanations.explain_saved_result(model, CATALOG, saved())
        self.assertEqual([i["name"] for i in result["raises"]], ["Diabetes", "Age"])
        self.assertEqual(model.asked, [{"Diabetes": 1, "Age": 78}])                 # only the model's inputs are passed on

    def test_every_case_where_it_would_not_be_honest_gives_nothing(self):
        cases = {
            "the model is not ready": (Model(ready=False), saved()),
            "the model cannot explain": (Model(can_explain=False), saved()),
            "another model version made the result": (Model(), saved(model_version="v0")),
            "the result has no model version": (Model(), saved(model_version=None)),
            "no answers were saved": (Model(), saved(inputs=None)),
            "an answer the model needs is missing": (Model(), saved(inputs={"Diabetes": 1})),
            "the explanation fails": (Model(raises=RuntimeError("boom")), saved()),
            "the model refuses the answers": (Model(raises=ValueError("bad answer")), saved()),
            "the probability now is not the one saved": (Model(probability=0.7), saved(probability=0.6)),
        }
        for reason, (model, row) in cases.items():
            self.assertIsNone(explanations.explain_saved_result(model, CATALOG, row), reason)

    def test_a_tiny_rounding_difference_in_the_saved_probability_is_allowed(self):
        self.assertIsNotNone(explanations.explain_saved_result(Model(probability=0.6000004), CATALOG, saved(probability=0.6)))


if __name__ == "__main__":
    unittest.main()
