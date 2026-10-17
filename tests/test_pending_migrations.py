"""Checks for db.pending_migrations() and the page shown while the database is older than the code - the case that
otherwise surfaces only as a bare "Error 500" when new code reads a column a migration has not added yet."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402
from helpers import AppTestCase  # noqa: E402

MIGRATIONS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database", "migrations")


class PendingMigrationTests(unittest.TestCase):
    def test_nothing_is_pending_once_every_file_has_been_applied(self):
        self.assertEqual(db.pending_migrations(db.migration_files(MIGRATIONS), MIGRATIONS), [])

    def test_the_newest_files_are_reported_in_order_when_missing(self):
        applied = [name for name in db.migration_files(MIGRATIONS) if not name.startswith(("016", "017", "018"))]
        self.assertEqual([name[:3] for name in db.pending_migrations(applied, MIGRATIONS)], ["016", "017", "018"])

    def test_only_sql_files_count(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ("001_a.sql", "002_b.sql", "README.md"):
                open(os.path.join(folder, name), "w").close()
            self.assertEqual(db.pending_migrations(["001_a.sql"], folder), ["002_b.sql"])


class DatabaseUpdatePageTests(AppTestCase):
    def test_every_page_explains_the_fix_while_migrations_are_pending(self):
        self.app.extensions["pending_migrations"] = ["016_add_country.sql", "017_create_checklist_daily.sql"]
        for path in ("/", "/login", "/dashboard"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 503, path)
            page = self.text(response)
            self.assertIn("python init_db.py", page)
            self.assertIn("017_create_checklist_daily.sql", page)
        self.assertEqual(self.client.get("/static/css/base.css").status_code, 200)      # still styled

    def test_pages_work_normally_once_nothing_is_pending(self):
        self.app.extensions["pending_migrations"] = []
        self.assertEqual(self.client.get("/login").status_code, 200)
