"""
mysql_support.py - creates (and afterwards deletes) the separate MySQL database the store tests use.

The database is called <DB_NAME>_test (for example nephron_test). It is built from the real migration files and
dropped at the end, so your own data is never touched. If MySQL is not running, or the MySQL user may not create
databases, `problem` holds a sentence saying so and the tests that need MySQL are skipped.
"""
import contextlib
import io
import os
import sys

os.environ.setdefault("SECRET_KEY", "test-only-secret-key")
os.environ["FLASK_DEBUG"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mysql.connector  # noqa: E402

import init_db  # noqa: E402
from app import create_app  # noqa: E402
from config import Config  # noqa: E402
from services.user_store import MemoryUserStore  # noqa: E402

TEST_DATABASE = Config.DB_NAME + "_test"
problem = None


def _quietly(function, *args):
    with contextlib.redirect_stdout(io.StringIO()):
        function(*args)


def prepare():
    """Call from setUpModule. Builds the test database from the migration files."""
    global problem
    try:
        _quietly(init_db.create_database_if_missing, TEST_DATABASE)
        _quietly(init_db.apply_migrations, TEST_DATABASE)
    except mysql.connector.Error as error:
        problem = f"MySQL test database '{TEST_DATABASE}' is not available ({error})"


def drop():
    """Call from tearDownModule."""
    if problem is None:
        connection = mysql.connector.connect(**init_db.connection_settings(include_database=False))
        cursor = connection.cursor()
        cursor.execute(f"DROP DATABASE IF EXISTS `{TEST_DATABASE}`")
        cursor.close()
        connection.close()


def rerun_migrations():
    _quietly(init_db.apply_migrations, TEST_DATABASE)


def push_app_context(test_case):
    """The MySQL stores use 'the current app's' database settings, so give them an app that points at the test database."""
    app = create_app({"DB_NAME": TEST_DATABASE}, user_store=MemoryUserStore())
    context = app.app_context()
    context.push()
    test_case.addCleanup(context.pop)
