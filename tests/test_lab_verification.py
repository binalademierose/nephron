"""Checks for services/lab_verification.py - signs, read from a lab report's own text, that it is real and about
the right person. Signs only: nothing here ever blocks or changes a value."""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import lab_verification as v  # noqa: E402

TODAY = date(2026, 10, 3)
SIGNED = ("St. Luke's Medical Center Laboratory\nPatient Name: Juan Dela Cruz   Age: 58\nDate Released: Sept 28, 2026\n"
          "Serum Creatinine: 1.2 mg/dL\nVerified by: Maria Santos, RMT  Lic. No. 012345\nPathologist: Jose Reyes, MD")


class LabVerificationTests(unittest.TestCase):
    def test_a_signed_recent_report_for_the_right_person_passes_every_check(self):
        result = v.check(SIGNED, "Juan Dela Cruz", TODAY)
        self.assertEqual([result[k]["status"] for k in ("name", "date", "signature", "facility")], ["match", "recent", "found", "found"])
        self.assertEqual(result["date"]["found"], "2026-09-28")
        self.assertEqual(v.concerns(result), 0)

    def test_someone_elses_name_is_a_mismatch_and_says_whose_it_is(self):
        result = v.check(SIGNED, "Ana Reyes", TODAY)
        self.assertEqual(result["name"], {"status": "mismatch", "found": "Juan Dela Cruz"})

    def test_a_name_in_a_different_order_or_with_a_middle_name_still_matches(self):
        self.assertEqual(v.check("Patient: Dela Cruz, Juan P.", "Juan Dela Cruz", TODAY)["name"]["status"], "match")

    def test_an_old_and_a_future_date_are_flagged(self):
        self.assertEqual(v.check("Date: 2025-01-10", "x", TODAY)["date"]["status"], "old")
        self.assertEqual(v.check("Date: 2027-01-10", "x", TODAY)["date"]["status"], "future")
        self.assertEqual(v.check("Date: 10/01/2026", "x", TODAY)["date"]["found"], "2026-10-01")    # month/day/year

    def test_an_unsigned_report_and_an_empty_text_report_missing_signs(self):
        unsigned = v.check("LAB\nPatient: Juan Dela Cruz\nDate: 2026-09-20\nCreatinine 1.1", "Juan Dela Cruz", TODAY)
        self.assertEqual(unsigned["signature"]["status"], "missing")
        empty = v.check("", "Juan Dela Cruz", TODAY)
        self.assertEqual([empty[k]["status"] for k in ("name", "date", "signature", "facility")], ["missing"] * 4)
        self.assertEqual(v.concerns(empty), 4)


if __name__ == "__main__":
    unittest.main()
