"""
Checks the migration files themselves (database/migrations/*.sql) without needing MySQL.
The main danger is silent drift: a form that accepts 150 characters for a column that holds 120 would cut the
text off (or fail) in the database. So these checks compare the SQL with the validation rules and with the SQL
that services/user_store.py runs.
"""
import glob
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-only-secret-key")

import init_db  # noqa: E402
from services import assessments, security, validation  # noqa: E402

FILES = sorted(glob.glob(os.path.join(init_db.MIGRATIONS_DIR, "*.sql")))


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _columns_in(body):
    columns = {}
    for line in body.split("\n"):
        line = line.strip().rstrip(",")
        match = re.match(r"(\w+) ([A-Z]+(?:\(.*?\))?)", line)
        if match and match.group(1).upper() not in ("PRIMARY", "UNIQUE", "KEY", "CONSTRAINT", "FOREIGN", "INDEX"):
            columns[match.group(1)] = line
    return columns


def tables():
    """{table name: {column name: definition}} read from every migration file (CREATE TABLE, plus any later
    ALTER TABLE ... ADD COLUMN against a table already created)."""
    found = {}
    for path in FILES:
        for statement in init_db.split_sql_statements(read(path)):
            created = re.match(r"CREATE TABLE IF NOT EXISTS (\w+)", statement)
            if created:
                body = statement[statement.index("(") + 1: statement.rindex(")")]
                found[created.group(1)] = _columns_in(body)
                continue
            altered = re.match(r"ALTER TABLE (\w+)\s+(.*)$", statement, re.S)
            if altered:
                table, body = altered.group(1), altered.group(2)
                for clause in re.split(r",\s*(?=ADD\b)", body):
                    added = re.match(r"ADD(?:\s+COLUMN)?\s+(\w+.*?)(?:\s+AFTER\s+\w+)?$", clause.strip(), re.S)
                    if added:
                        found[table].update(_columns_in(added.group(1)))
                continue
            if re.match(r"CREATE (UNIQUE )?INDEX \w+ ON \w+", statement):
                continue          # an index on an existing column, not a new column - nothing for tables() to add
            raise AssertionError(f"tables() cannot read this statement in {path}: {statement[:80]}")
    return found


def size_of(definition):
    return int(re.search(r"VARCHAR\((\d+)\)", definition).group(1))


class MigrationFileTests(unittest.TestCase):
    def test_files_are_numbered_without_gaps(self):
        names = [os.path.basename(p) for p in FILES]
        self.assertTrue(names)
        for position, name in enumerate(names, start=1):
            self.assertRegex(name, r"^\d{3}_[a-z0-9_]+\.sql$")
            self.assertEqual(int(name[:3]), position, f"{name} is out of order or a number is missing")

    def test_every_statement_is_safe_to_run_again_and_uses_the_agreed_engine(self):
        for path in FILES:
            statements = init_db.split_sql_statements(read(path))
            self.assertGreaterEqual(len(statements), 1, path)
            for statement in statements:
                self.assertNotIn("--", statement, f"{path}: a trailing comment would be sent to MySQL")
                if statement.startswith("ALTER TABLE"):
                    self.assertIn("ADD ", statement, path)                   # the only ALTER shape a migration here may use
                    continue
                if statement.startswith("CREATE UNIQUE INDEX") or statement.startswith("CREATE INDEX"):
                    continue                                                 # an index on a column ADD COLUMN already added
                self.assertTrue(statement.startswith("CREATE TABLE IF NOT EXISTS"), path)
                self.assertIn("ENGINE=InnoDB", statement, path)              # InnoDB is what enforces foreign keys
                self.assertIn("utf8mb4", statement, path)                    # names and text in any language

    def test_an_alter_table_only_ever_targets_a_table_from_an_earlier_file(self):
        created = set()
        for path in FILES:
            for statement in init_db.split_sql_statements(read(path)):
                match = re.match(r"ALTER TABLE (\w+)", statement)
                if match:
                    self.assertIn(match.group(1), created, f"{path} alters {match.group(1)} before it exists")
            created.update(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", "\n".join(init_db.split_sql_statements(read(path)))))

    def test_nothing_dangerous_is_in_a_migration(self):
        for path in FILES:
            text = read(path).upper()
            for banned in ("FOREIGN_KEY_CHECKS", "DROP TABLE", "DROP DATABASE", "TRUNCATE", "DELETE FROM"):
                self.assertNotIn(banned, text, f"{path} contains {banned}")

    def test_comments_are_whole_lines_and_contain_no_semicolon(self):
        # The runner cuts a file into statements at every ";", so a ";" inside a comment line would be harmless
        # only if the whole line is a comment. Check that comment lines never carry code.
        for path in FILES:
            for line in read(path).splitlines():
                if "--" in line:
                    self.assertTrue(line.strip().startswith("--"), f"{path}: comment after code: {line}")
                    self.assertNotIn(";", line, f"{path}: ';' inside a comment")

    def test_foreign_keys_point_at_tables_from_earlier_files(self):
        created = set()
        for path in FILES:
            text = "\n".join(init_db.split_sql_statements(read(path)))
            for referenced in re.findall(r"REFERENCES (\w+)", text):
                self.assertIn(referenced, created, f"{path} references {referenced} before it exists")
            created.update(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", text))


class SchemaMatchesTheCodeTests(unittest.TestCase):
    def setUp(self):
        self.schema = tables()

    def test_the_tables_and_columns_the_store_uses_exist(self):
        self.assertEqual(set(self.schema), {"users", "professionals", "login_attempts", "assessments", "assessment_inputs", "lab_documents", "authorizations", "clinical_reviews", "follow_up_requests", "screening_drafts", "notifications", "follow_up_appointments", "checklist_completions", "consent_records", "patient_records", "checklist_daily", "activity_log", "app_settings", "reassessment_requests"})
        self.assertGreaterEqual(set(self.schema["users"]), {"user_id", "email", "password_hash", "full_name", "role", "created_at", "last_login_at", "password_changed_at"})
        self.assertGreaterEqual(set(self.schema["professionals"]), {"user_id", "profession_title", "institution", "license_number"})
        self.assertGreaterEqual(set(self.schema["login_attempts"]), {"email", "ip_address", "was_successful", "attempted_at"})
        self.assertGreaterEqual(set(self.schema["assessments"]), {"assessment_id", "user_id", "assessment_type", "probability", "classification",
                                                                 "threshold_used", "model_version", "assessed_at"})

    def test_the_reassessment_tables_fit_what_the_code_saves(self):
        from services import reassessment
        from services.reassessment_store import MONTHS_KEY, STATUSES
        requests, settings = self.schema["reassessment_requests"], self.schema["app_settings"]
        self.assertGreaterEqual(set(requests), {"request_id", "user_id", "reason", "status", "requested_at", "decided_at", "decided_by"})
        self.assertGreaterEqual(size_of(requests["reason"]), reassessment.MAX_REASON_LENGTH)
        self.assertGreaterEqual(size_of(requests["status"]), max(len(s) for s in STATUSES))
        self.assertGreaterEqual(size_of(settings["setting_key"]), len(MONTHS_KEY))

    def test_the_users_role_column_allows_exactly_the_roles_the_code_knows(self):
        listed = re.findall(r"'(\w+)'", self.schema["users"]["role"])
        self.assertEqual(tuple(listed), validation.ROLES)

    def test_no_column_is_narrower_than_what_the_forms_accept(self):
        users, professionals, attempts = self.schema["users"], self.schema["professionals"], self.schema["login_attempts"]
        self.assertGreaterEqual(size_of(users["email"]), 254)                # the longest email check_email allows
        self.assertGreaterEqual(size_of(attempts["email"]), 254)
        self.assertGreaterEqual(size_of(users["full_name"]), 120)
        self.assertGreaterEqual(size_of(professionals["institution"]), 120)
        self.assertGreaterEqual(size_of(professionals["license_number"]), 50)
        self.assertGreaterEqual(size_of(professionals["profession_title"]), max(len(p) for p in validation.PROFESSIONS))
        self.assertGreaterEqual(size_of(attempts["ip_address"]), 45)         # the longest IPv6 text

    def test_a_password_hash_fits_its_column(self):
        self.assertGreaterEqual(size_of(self.schema["users"]["password_hash"]), len(security.hash_password("x" * 128)))
        self.assertGreaterEqual(size_of(self.schema["users"]["password_hash"]), len(security.hash_password("a")))

    def test_the_assessment_lists_match_the_words_the_code_uses(self):
        cols = self.schema["assessments"]
        self.assertEqual(tuple(re.findall(r"'(\w+)'", cols["assessment_type"])), assessments.ASSESSMENT_TYPES)
        self.assertEqual(tuple(re.findall(r"'(\w+)'", cols["classification"])), assessments.CLASSIFICATIONS)

    def test_an_assessment_keeps_enough_precision_and_cannot_hold_nonsense(self):
        text = read(os.path.join(init_db.MIGRATIONS_DIR, "004_create_assessments.sql"))
        # the store rounds to six decimals, so the column must hold exactly that, and a fraction from 0 to 1
        self.assertIn("probability DECIMAL(7, 6) NOT NULL", text)
        self.assertIn("threshold_used DECIMAL(7, 6) NULL", text)
        self.assertRegex(text, r"CHECK \(probability >= 0 AND probability <= 1\)")
        self.assertGreaterEqual(size_of(self.schema["assessments"]["model_version"]), 100)
        from services import assessment_store
        self.assertEqual(assessment_store.PRECISION, 6)

    def test_the_answers_snapshot_is_one_row_per_assessment_and_goes_with_it(self):
        text = read(os.path.join(init_db.MIGRATIONS_DIR, "005_create_assessment_inputs.sql"))
        self.assertGreaterEqual(set(self.schema["assessment_inputs"]), {"assessment_id", "inputs"})
        self.assertIn("PRIMARY KEY (assessment_id)", text)                             # one snapshot per assessment
        self.assertIn("REFERENCES assessments (assessment_id) ON DELETE CASCADE", text)
        self.assertIn("inputs TEXT NOT NULL", text)                                   # room for the 30 or so saved answers
        self.assertGreater(assessments.MAX_INPUTS_BYTES, 1000)
        self.assertLess(assessments.MAX_INPUTS_BYTES, 65535)                          # never more than a TEXT column holds

    def test_an_assessment_belongs_to_a_user_and_is_removed_with_them(self):
        text = read(os.path.join(init_db.MIGRATIONS_DIR, "004_create_assessments.sql"))
        self.assertIn("FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE", text)
        self.assertIn("KEY idx_assessments_user_time (user_id, assessed_at)", text)   # the dashboard's query is by user and time

    def test_the_email_is_unique_and_the_professional_row_belongs_to_a_user(self):
        users = read(os.path.join(init_db.MIGRATIONS_DIR, "001_create_users.sql"))
        self.assertRegex(users, r"UNIQUE KEY \w+ \(email\)")
        # "_ci" means case-insensitive: Ana@Mail.com and ana@mail.com count as the same address in the unique key.
        self.assertIn("COLLATE=utf8mb4_unicode_ci", users)
        professionals = read(os.path.join(init_db.MIGRATIONS_DIR, "002_create_professionals.sql"))
        self.assertIn("FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE", professionals)


if __name__ == "__main__":
    unittest.main()
