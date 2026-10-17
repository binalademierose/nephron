"""
Checks for services/lab_contract.py: validating a Stage 2 lab submission where almost everything is optional, but
anything given is still range-checked, plus the eGFR computation glue. No Flask and no database.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import lab_contract  # noqa: E402

CATALOG = lab_contract.load_lab_catalog()


class CatalogTests(unittest.TestCase):
    def test_the_catalog_loads_and_has_twenty_fields_serum_creatinine_the_only_required_one(self):
        names = lab_contract.field_names(CATALOG)
        self.assertEqual(len(names), 20)
        required = [f["name"] for f in CATALOG["fields"] if f["required"]]
        self.assertEqual(required, ["Serum_Creatinine"])

    def test_a_malformed_catalog_is_refused_in_plain_words(self):
        base = {"groups": [{"key": "kidney", "title": "Kidney"}],
                "fields": [{"name": "Serum_Creatinine", "short": "Creatinine", "group": "kidney", "unit": "mg/dL", "min": 0.1, "max": 20, "required": True}]}
        lab_contract.check_lab_catalog(base)  # a valid minimal catalog does not raise
        with self.assertRaisesRegex(ValueError, "no groups"):
            lab_contract.check_lab_catalog({"groups": [], "fields": base["fields"]})
        with self.assertRaisesRegex(ValueError, "listed twice"):
            lab_contract.check_lab_catalog({**base, "fields": base["fields"] * 2})
        with self.assertRaisesRegex(ValueError, "unknown group"):
            lab_contract.check_lab_catalog({**base, "fields": [{**base["fields"][0], "group": "nope"}]})
        with self.assertRaisesRegex(ValueError, "min below its max"):
            lab_contract.check_lab_catalog({**base, "fields": [{**base["fields"][0], "min": 5, "max": 1}]})
        with self.assertRaisesRegex(ValueError, "no field is marked required"):
            lab_contract.check_lab_catalog({**base, "fields": [{**base["fields"][0], "required": False}]})


class ValidateLabValuesTests(unittest.TestCase):
    def test_an_empty_submission_only_complains_about_the_required_field(self):
        values, errors = lab_contract.validate_lab_values(CATALOG, {})
        self.assertEqual(values, {})
        self.assertEqual(set(errors), {"Serum_Creatinine"})

    def test_only_creatinine_is_enough_to_pass(self):
        values, errors = lab_contract.validate_lab_values(CATALOG, {"Serum_Creatinine": "1.1"})
        self.assertEqual(values, {"Serum_Creatinine": 1.1})
        self.assertEqual(errors, {})

    def test_a_blank_string_is_the_same_as_not_given(self):
        values, errors = lab_contract.validate_lab_values(CATALOG, {"Serum_Creatinine": "1.0", "HbA1c": "  ", "Sodium": ""})
        self.assertEqual(set(values), {"Serum_Creatinine"})
        self.assertEqual(errors, {})

    def test_everything_given_is_kept_when_all_valid(self):
        form = {"Serum_Creatinine": "1.0", "eGFR_ignored_if_sent": "999", "HbA1c": "5.4", "Sodium": "140", "Systolic_BP": "120", "Diastolic_BP": "80"}
        values, errors = lab_contract.validate_lab_values(CATALOG, form)
        self.assertEqual(errors, {})
        self.assertEqual(values, {"Serum_Creatinine": 1.0, "HbA1c": 5.4, "Sodium": 140.0, "Systolic_BP": 120.0, "Diastolic_BP": 80.0})

    def test_a_value_outside_the_plausible_range_is_refused_not_clamped(self):
        values, errors = lab_contract.validate_lab_values(CATALOG, {"Serum_Creatinine": "1.0", "Sodium": "999"})
        self.assertIn("Sodium", errors)
        self.assertNotIn("Sodium", values)
        self.assertIn("Serum_Creatinine", values)

    def test_text_that_is_not_a_number_is_refused_with_a_clear_reason_not_guessed(self):
        values, errors = lab_contract.validate_lab_values(CATALOG, {"Serum_Creatinine": "1.0", "HbA1c": "high"})
        self.assertIn("must be a number", errors["HbA1c"])
        self.assertNotIn("HbA1c", values)

    def test_numbers_given_as_actual_numbers_not_strings_also_work(self):
        values, errors = lab_contract.validate_lab_values(CATALOG, {"Serum_Creatinine": 1.2, "Potassium": 4.1})
        self.assertEqual(values, {"Serum_Creatinine": 1.2, "Potassium": 4.1})
        self.assertEqual(errors, {})

    def test_an_unknown_field_in_the_form_is_ignored_not_an_error(self):
        values, errors = lab_contract.validate_lab_values(CATALOG, {"Serum_Creatinine": "1.0", "Something_Else": "5"})
        self.assertEqual(errors, {})
        self.assertNotIn("Something_Else", values)

    def test_boundary_values_are_accepted(self):
        field = lab_contract.field_for(CATALOG, "Serum_Creatinine")
        values, errors = lab_contract.validate_lab_values(CATALOG, {"Serum_Creatinine": field["min"]})
        self.assertEqual(errors, {})
        values, errors = lab_contract.validate_lab_values(CATALOG, {"Serum_Creatinine": field["max"]})
        self.assertEqual(errors, {})


class WithEgfrTests(unittest.TestCase):
    def test_egfr_is_added_when_creatinine_is_present(self):
        result = lab_contract.with_egfr({"Serum_Creatinine": 0.9}, age=45, sex="Male")
        self.assertIn("eGFR", result)
        self.assertGreater(result["eGFR"], 0)
        self.assertEqual(result["Serum_Creatinine"], 0.9)

    def test_egfr_is_never_guessed_when_creatinine_is_missing(self):
        result = lab_contract.with_egfr({"Sodium": 140}, age=45, sex="Male")
        self.assertNotIn("eGFR", result)
        self.assertEqual(result, {"Sodium": 140})

    def test_the_original_dict_is_not_mutated(self):
        original = {"Serum_Creatinine": 1.0}
        lab_contract.with_egfr(original, age=30, sex="Female")
        self.assertEqual(original, {"Serum_Creatinine": 1.0})


class DescribeLabValuesTests(unittest.TestCase):
    def test_only_given_values_are_described_grouped_by_panel(self):
        groups = lab_contract.describe_lab_values(CATALOG, {"Serum_Creatinine": 1.1, "Sodium": 140.0})
        titles = [title for title, _ in groups]
        self.assertIn("Kidney function", titles)
        self.assertIn("Electrolytes and minerals", titles)
        self.assertNotIn("Cholesterol panel", titles)
        kidney = next(rows for title, rows in groups if title == "Kidney function")
        self.assertIn(("Serum creatinine", "1.1 mg/dL"), kidney)

    def test_nothing_given_means_no_groups_at_all(self):
        self.assertEqual(lab_contract.describe_lab_values(CATALOG, {}), [])


if __name__ == "__main__":
    unittest.main()
