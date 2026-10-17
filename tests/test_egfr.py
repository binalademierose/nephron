"""
Checks for services/egfr.py: the CKD-EPI 2021 creatinine equation. The expected values below are worked out from the
published formula independently of the implementation, so this catches a transcription mistake in the constants,
not just a mistake this module would repeat against itself. Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.egfr import estimate_gfr  # noqa: E402


def reference(scr, age, sex):
    """The same published formula, computed independently (kept deliberately separate from egfr.py's own code)."""
    kappa, alpha, sex_factor = (0.7, -0.241, 1.012) if sex == "Female" else (0.9, -0.302, 1.0)
    ratio = scr / kappa
    return 142 * min(ratio, 1) ** alpha * max(ratio, 1) ** -1.2 * 0.9938 ** age * sex_factor


class EstimateGfrTests(unittest.TestCase):
    def test_matches_the_published_formula_computed_independently(self):
        for scr, age, sex in [(0.9, 45, "Male"), (0.7, 45, "Female"), (1.4, 68, "Male"), (0.5, 30, "Female"),
                              (2.3, 72, "Male"), (0.6, 22, "Female"), (5.0, 55, "Male"), (0.9, 90, "Female")]:
            self.assertAlmostEqual(estimate_gfr(scr, age, sex, round_to=None), reference(scr, age, sex), places=9)

    def test_a_lower_creatinine_gives_a_higher_egfr_all_else_equal(self):
        self.assertGreater(estimate_gfr(0.7, 50, "Male"), estimate_gfr(1.4, 50, "Male"))

    def test_an_older_age_gives_a_lower_egfr_all_else_equal(self):
        self.assertGreater(estimate_gfr(0.9, 30, "Female"), estimate_gfr(0.9, 80, "Female"))

    def test_known_reference_values_are_in_the_expected_clinical_range(self):
        # A healthy young adult should land in the normal range; a raised creatinine in an older adult should not.
        self.assertGreater(estimate_gfr(0.8, 25, "Male"), 90)
        self.assertLess(estimate_gfr(2.5, 75, "Female"), 30)

    def test_rounding_defaults_to_one_decimal_and_can_be_turned_off(self):
        value = estimate_gfr(1.1, 60, "Male")
        self.assertEqual(value, round(value, 1))
        self.assertNotEqual(estimate_gfr(1.1, 60, "Male", round_to=None) % 1, 0)

    def test_it_never_guesses_a_sex_it_does_not_know_or_a_non_positive_value(self):
        with self.assertRaisesRegex(ValueError, "Female.*Male"):
            estimate_gfr(1.0, 50, "Unknown")
        for bad_scr in (0, -1, "1.0", None):
            with self.assertRaises(ValueError):
                estimate_gfr(bad_scr, 50, "Male")
        for bad_age in (0, -5, None):
            with self.assertRaises(ValueError):
                estimate_gfr(1.0, bad_age, "Male")


if __name__ == "__main__":
    unittest.main()
