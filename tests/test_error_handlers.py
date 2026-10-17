"""
Checks for routes/error_handlers.py's database-error handling: a genuine connectivity problem (the server is down,
the connection dropped) is the only thing that gets the honest "can't reach the database" 503 page. Any OTHER
mysql.connector.Error (a bad query, a driver misuse, anything that is a bug in Nephron itself) gets the general
"something went wrong" 500 page instead - never told, wrongly, that the database is unreachable.
Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import AppTestCase  # noqa: E402

import mysql.connector  # noqa: E402


class DatabaseErrorClassificationTests(AppTestCase):
    def setUp(self):
        super().setUp()

        @self.app.route("/__raise/<kind>")
        def _raise(kind):
            raise getattr(mysql.connector, kind)("simulated for this test")

    def raised(self, kind):
        return self.new_browser().get(f"/__raise/{kind}")

    def test_a_real_connectivity_problem_is_told_honestly(self):
        for kind in ("OperationalError", "InterfaceError"):
            response = self.raised(kind)
            self.assertEqual(response.status_code, 503, kind)
            self.assertIn("Nephron is temporarily unavailable", self.text(response), kind)

    def test_a_bad_query_or_any_other_database_error_is_not_called_unreachable(self):
        for kind in ("ProgrammingError", "IntegrityError", "DatabaseError", "Error"):
            response = self.raised(kind)
            self.assertEqual(response.status_code, 500, kind)
            page = self.text(response)
            self.assertIn("Something went wrong", page, kind)
            self.assertNotIn("can&#39;t reach the database", page, kind)
            self.assertNotIn("reach the database", page, kind)


if __name__ == "__main__":
    unittest.main()
