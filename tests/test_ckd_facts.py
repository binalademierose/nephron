"""
Checks for services/ckd_facts.py: every fact is present and carries a source - this is the one thing that must
never regress, since these are population statistics shown to real people, not something to state unsourced.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import ckd_facts  # noqa: E402


class CkdFactsTests(unittest.TestCase):
    def test_all_facts_returns_every_section(self):
        facts = ckd_facts.all_facts()
        self.assertEqual(set(facts), {"prevalence", "awareness", "kidney_failure", "cause_of_death", "sex_differences", "age_decline"})

    def test_every_section_carries_a_real_source(self):
        for name, fact in ckd_facts.all_facts().items():
            self.assertTrue(fact.get("source_label"), name)
            self.assertTrue(fact.get("source_url", "").startswith("https://"), name)

    def test_no_figure_about_us_adults_is_left(self):
        # the panel asked for these to go: Nephron's users are in the Philippines
        text = repr(ckd_facts.all_facts())
        for gone in ("US adults", "United States", "1 in 7", "CDC"):
            self.assertNotIn(gone, text)

    def test_the_philippine_figures_are_the_ones_their_sources_report(self):
        self.assertEqual(ckd_facts.PREVALENCE["value"], "7 million")
        self.assertEqual((ckd_facts.AWARENESS["value"], ckd_facts.AWARENESS["ring_percent"]), ("1 in 10", 10))
        self.assertIn("every hour", ckd_facts.KIDNEY_FAILURE["detail"])
        self.assertIn("2019", ckd_facts.CAUSE_OF_DEATH["short_caption"])

    def test_every_big_number_card_has_an_icon_and_a_ring_only_where_it_is_a_share(self):
        for fact in (ckd_facts.PREVALENCE, ckd_facts.KIDNEY_FAILURE, ckd_facts.CAUSE_OF_DEATH, ckd_facts.AGE_DECLINE):
            self.assertTrue(fact["icon"])
            self.assertNotIn("ring_percent", fact)
        self.assertTrue(0 < ckd_facts.AWARENESS["ring_percent"] <= 100)

    def test_sex_differences_does_not_oversimplify_to_a_single_cause(self):
        # guards against ever rewriting this into a bare "men progress faster because no estrogen" claim
        detail = ckd_facts.SEX_DIFFERENCES["stats"][0]["detail"]
        self.assertIn("several possible reasons", detail)
        self.assertIn("not a settled", detail)


if __name__ == "__main__":
    unittest.main()
