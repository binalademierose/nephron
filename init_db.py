"""
init_db.py - creates the database and applies the SQL migration files.

Run it with:   python init_db.py
It is safe to run again: files that were already applied are skipped.

How migrations work
  * Each change to the database is a numbered file in database/migrations/
    (001_..., 002_..., ...). Files run in number order.
  * A table called schema_migrations remembers which files already ran.
  * Rules for migration files: plain SQL, every statement ends with ";",
    and no ";" inside text values. Use "--" for comments.
  * MySQL cannot undo a half-finished CREATE TABLE. If a file fails, fix the
    file and run again; write "CREATE TABLE IF NOT EXISTS" so a re-run is safe.
  * Never turn off foreign-key checks to make a migration pass.
"""
import glob
import os
import sys

import mysql.connector

from config import BASE_DIR, Config, validate_config

MIGRATIONS_DIR = os.path.join(BASE_DIR, "database", "migrations")

CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_id INT AUTO_INCREMENT PRIMARY KEY,
    filename VARCHAR(255) NOT NULL UNIQUE,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB
"""


def list_migration_files():
    """Return the .sql files in database/migrations/, in number order."""
    return sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql")))


def split_sql_statements(sql_text):
    """Split a migration file into single statements (see the rules above)."""
    lines = [line for line in sql_text.splitlines() if not line.strip().startswith("--")]
    statements = "\n".join(lines).split(";")
    return [statement.strip() for statement in statements if statement.strip()]


def connection_settings(include_database, database=None):
    """`database` lets the automated tests use a separate database; normally it is DB_NAME from .env."""
    settings = {
        "host": Config.DB_HOST,
        "port": Config.DB_PORT,
        "user": Config.DB_USER,
        "password": Config.DB_PASSWORD,
        "charset": "utf8mb4",
        "connection_timeout": 5,
    }
    if include_database:
        settings["database"] = database or Config.DB_NAME
    return settings


def create_database_if_missing(database=None):
    database = database or Config.DB_NAME
    connection = mysql.connector.connect(**connection_settings(include_database=False))
    cursor = connection.cursor()
    # The name was checked (letters, digits, underscores only), because a database name cannot be a %s parameter.
    cursor.execute(
        f"CREATE DATABASE IF NOT EXISTS `{database}` "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    cursor.close()
    connection.close()
    print(f"Database '{database}' is ready.")


def apply_migrations(database=None):
    connection = mysql.connector.connect(**connection_settings(include_database=True, database=database))
    cursor = connection.cursor()
    cursor.execute(CREATE_MIGRATIONS_TABLE)

    cursor.execute("SELECT filename FROM schema_migrations")
    already_applied = {row[0] for row in cursor.fetchall()}

    applied_now = 0
    for file_path in list_migration_files():
        filename = os.path.basename(file_path)
        if filename in already_applied:
            continue
        print(f"Applying {filename} ...")
        with open(file_path, "r", encoding="utf-8") as sql_file:
            statements = split_sql_statements(sql_file.read())
        for statement in statements:
            cursor.execute(statement)
        cursor.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (filename,))
        connection.commit()
        applied_now += 1

    cursor.close()
    connection.close()
    if applied_now == 0:
        print("No new migrations. The database is up to date.")
    else:
        print(f"Applied {applied_now} migration(s).")


def main():
    validate_config({"SECRET_KEY": Config.SECRET_KEY, "DB_NAME": Config.DB_NAME})
    try:
        create_database_if_missing()
        apply_migrations()
    except mysql.connector.Error as error:
        print(f"\nCould not finish: {error}")
        if error.errno == 1932:                                   # "Table '...' doesn't exist in engine"
            # Not a connection problem: MySQL's own records say a table exists here, but its storage engine (InnoDB)
            # has no matching data for it - a leftover, inconsistent data folder, most often left behind by
            # reinstalling MySQL/XAMPP without removing the OLD data directory first.
            print(f"MySQL's own records say a table exists, but its storage engine cannot find it - this is not a "
                 f"connection problem. It usually means the '{Config.DB_NAME}' folder in MySQL's data directory is "
                 f"left over from a previous install (common after reinstalling XAMPP without removing the old data "
                 f"first). With MySQL stopped, delete that database's folder from MySQL's data directory (XAMPP: "
                 rf"mysql\data\{Config.DB_NAME}, and mysql\data\{Config.DB_NAME}_test if it exists), start "
                 f"MySQL again, then run this script again - it will create the database fresh. Any data already in "
                 f"it cannot be recovered, since the folder is already unreadable to MySQL.")
        else:
            print("Check that MySQL is running and that DB_HOST, DB_USER and DB_PASSWORD in .env are correct.")
        sys.exit(1)


if __name__ == "__main__":
    main()
