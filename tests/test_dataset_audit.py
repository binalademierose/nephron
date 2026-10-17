"""
Keeps ml/DATASET_AUDIT_CKD_400k.md and ml/feature_catalog.json in step. If the questions of the form change, this test fails
until the audit is brought up to date, so the document can never quietly describe a form that no longer exists.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import screening_contract  # noqa: E402

AUDIT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ml", "DATASET_AUDIT_CKD_400k.md")


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(AUDIT, encoding="utf-8") as handle:
            cls.text = handle.read()
        cls.sections = {}
        current = None
        for line in cls.text.splitlines():
            if line.startswith("### "):
                current = line[4:]
                cls.sections[current] = []
            elif current and line.startswith("| `"):
                cls.sections[current].append(re.match(r"\| `(.+?)` \|", line).group(1))

    def in_section(self, prefix):
        return next(columns for name, columns in self.sections.items() if name.startswith(prefix))

    def test_every_question_of_the_form_is_listed_as_in_use(self):
        in_use = set(self.in_section("1. Stage 1: in use"))
        for name in screening_contract.feature_names(screening_contract.load_catalog()):
            self.assertIn(name, in_use, f"{name} is asked by the form but the audit does not list it as in use")

    def test_nothing_is_in_use_that_the_form_does_not_ask_except_height_and_weight(self):
        asked = set(screening_contract.feature_names(screening_contract.load_catalog()))
        for name in self.in_section("1. Stage 1: in use"):
            self.assertTrue(name in asked or name in ("Height_cm", "Weight_kg"), f"{name} is marked in use but the form does not ask it")

    def test_every_column_is_listed_exactly_once_and_the_counts_add_up(self):
        listed = [column for columns in self.sections.values() for column in columns]
        self.assertEqual(len(listed), 92)
        self.assertEqual(len(set(listed)), 92)
        summary = {int(n) for n in re.findall(r"^\| .*? \| (\d+) \|$", self.text, re.M)}
        self.assertEqual(sum(len(columns) for columns in self.sections.values()), 92)
        self.assertTrue(summary)

    def test_the_columns_that_must_never_be_asked_are_marked_do_not_use(self):
        do_not_use = set(self.in_section("3. Do NOT use"))
        for name in ("Gluta drip", "Gender Affirming Hormone Theraphy(hormonal pills)", "PreviousAcuteKidneyInjury", "HeavyMetalsExposure",
                     "FamilyHistoryKidneyDisease", "ClinicianImposedFluidRestriction", "DietQuality"):
            self.assertIn(name, do_not_use)
        self.assertNotIn("eGFR", do_not_use)                                       # eGFR belongs to Stage 2 (with a warning), not to the form
        self.assertIn("eGFR", self.in_section("4. Stage 2"))

    def test_the_target_and_its_consequences_are_never_predictors(self):
        outcomes = set(self.in_section("5. Outcome"))
        for name in ("CKD", "CKD_Stage", "Kidney_Failure_Risk", "Dialysis_Required", "Hospitalization_Risk", "Frailty_Index", "Patient_ID"):
            self.assertIn(name, outcomes)


if __name__ == "__main__":
    unittest.main()
