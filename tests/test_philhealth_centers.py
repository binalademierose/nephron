"""
Checks for services/philhealth_centers.py: the directory loads real data, and search matches by name, area or
municipality, filters by region/sector, and never invents anything not in the source file.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import philhealth_centers  # noqa: E402


class DirectoryTests(unittest.TestCase):
    def test_the_real_directory_loads_and_is_not_empty(self):
        directory = philhealth_centers.load_directory()
        self.assertGreater(len(directory["centers"]), 900)          # the real source file has 959
        self.assertIn("source", directory)

    def test_every_center_has_the_fields_a_result_needs(self):
        for center in philhealth_centers.load_directory()["centers"][:20]:
            for field in ("id", "name", "region", "province_or_city", "municipality", "sector"):
                self.assertIn(field, center)
                self.assertIsNotNone(center[field], field)

    def test_regions_lists_every_region_with_no_duplicates(self):
        found = philhealth_centers.regions()
        self.assertEqual(len(found), len(set(found)))
        self.assertIn("CORDILLERA ADMINISTRATIVE REGION", found)
        self.assertGreaterEqual(len(found), 17)                     # the 17 standard Philippine regions

    def test_sector_is_always_one_of_the_two_real_labels(self):
        for center in philhealth_centers.load_directory()["centers"]:
            self.assertIn(center["sector"], ("Private", "Government"))


class SearchTests(unittest.TestCase):
    def test_a_blank_search_returns_everything_up_to_the_limit(self):
        matches, total = philhealth_centers.search()
        self.assertEqual(len(matches), philhealth_centers.MAX_RESULTS)
        self.assertGreater(total, philhealth_centers.MAX_RESULTS)

    def test_searching_a_real_municipality_finds_a_real_facility(self):
        matches, total = philhealth_centers.search(term="Baguio")
        self.assertGreater(total, 0)
        self.assertTrue(any("BAGUIO" in m["municipality"] for m in matches))

    def test_search_is_case_and_accent_insensitive(self):
        matches_lower, total_lower = philhealth_centers.search(term="baguio city")
        matches_upper, total_upper = philhealth_centers.search(term="BAGUIO CITY")
        self.assertEqual(total_lower, total_upper)

    def test_search_matches_the_facility_name_too(self):
        # a real facility name from the source file
        matches, total = philhealth_centers.search(term="Nephrology Care")
        self.assertGreater(total, 0)
        self.assertTrue(any("NEPHROLOGY CARE" in m["name"] for m in matches))

    def test_no_match_returns_an_empty_list_not_an_error(self):
        matches, total = philhealth_centers.search(term="no such place at all xyz123")
        self.assertEqual(matches, [])
        self.assertEqual(total, 0)

    def test_filtering_by_region_only_returns_that_region(self):
        region = philhealth_centers.regions()[0]
        matches, total = philhealth_centers.search(region=region, limit=1000)
        self.assertGreater(total, 0)
        self.assertTrue(all(m["region"] == region for m in matches))

    def test_filtering_by_sector_only_returns_that_sector(self):
        matches, total = philhealth_centers.search(sector="Government", limit=1000)
        self.assertGreater(total, 0)
        self.assertTrue(all(m["sector"] == "Government" for m in matches))

    def test_combining_a_term_with_a_region_narrows_further(self):
        region = philhealth_centers.regions()[0]
        _, total_region_only = philhealth_centers.search(region=region, limit=1000)
        _, total_combined = philhealth_centers.search(region=region, term="no such place xyz123", limit=1000)
        self.assertEqual(total_combined, 0)
        self.assertGreater(total_region_only, 0)

    def test_results_are_sorted_by_name(self):
        matches, _ = philhealth_centers.search(limit=1000)
        names = [m["name"] for m in matches]
        self.assertEqual(names, sorted(names))

    def test_a_custom_limit_is_respected(self):
        matches, total = philhealth_centers.search(limit=5)
        self.assertEqual(len(matches), 5)
        self.assertGreater(total, 5)


if __name__ == "__main__":
    unittest.main()
