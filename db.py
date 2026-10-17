"""
db.py - the only file that talks to MySQL directly.

Rules used everywhere in Nephron:
  * SQL values are always passed as parameters (%s), never pasted into the text.
  * One database connection per web request, closed automatically afterwards.
"""
from contextlib import contextmanager

import mysql.connector
from flask import current_app, g


def _connection_settings():
    config = current_app.config
    return {
        "host": config["DB_HOST"],
        "port": config["DB_PORT"],
        "user": config["DB_USER"],
        "password": config["DB_PASSWORD"],
        "database": config["DB_NAME"],
        "charset": "utf8mb4",
        "collation": "utf8mb4_unicode_ci",
        "connection_timeout": 5,
    }


def get_db():
    """Return this request's connection, creating it the first time."""
    if "db" not in g:
        g.db = mysql.connector.connect(**_connection_settings())
    return g.db


def close_db(error=None):
    """Registered in app.py so the connection closes when the request ends."""
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def query_all(sql, params=None):
    """Run a SELECT and return every row as a dictionary."""
    cursor = get_db().cursor(dictionary=True)
    try:
        cursor.execute(sql, params or ())
        return cursor.fetchall()
    finally:
        cursor.close()


def query_one(sql, params=None):
    """Run a SELECT and return the first row (or None)."""
    cursor = get_db().cursor(dictionary=True)
    try:
        cursor.execute(sql, params or ())
        return cursor.fetchone()
    finally:
        cursor.close()


def execute(sql, params=None):
    """Run an INSERT/UPDATE/DELETE, save it, and return the new row id."""
    connection = get_db()
    cursor = connection.cursor()
    try:
        cursor.execute(sql, params or ())
        connection.commit()
        return cursor.lastrowid
    except mysql.connector.Error:
        connection.rollback()
        raise
    finally:
        cursor.close()


@contextmanager
def transaction():
    """
    Run several statements so that ALL of them are saved, or NONE are.

        with db.transaction() as cursor:
            cursor.execute("INSERT INTO users ...", (...))
            cursor.execute("INSERT INTO professionals ...", (...))

    If anything inside the block raises an error, everything done inside it is undone.
    """
    connection = get_db()
    cursor = connection.cursor()
    try:
        yield cursor
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def check_database_connection():
    """
    Try to reach MySQL. Returns (True, "connected") or (False, "reason").
    The technical reason is logged; callers must never show it to users.
    """
    try:
        connection = mysql.connector.connect(**_connection_settings())
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
        finally:
            connection.close()
        return True, "connected"
    except mysql.connector.Error as error:
        current_app.logger.error("MySQL connection check failed: %s", error)
        return False, str(error)


def migration_files(migrations_dir):
    """Every migration file in database/migrations, in the order init_db.py applies them."""
    import os
    return sorted(name for name in os.listdir(migrations_dir) if name.endswith(".sql"))


def pending_migrations(applied, migrations_dir):
    """The migration files the code ships with that this database has NOT had applied yet - each one a table or
    column the code reads that would otherwise fail with a bare 500 error. Pure: easy to test without a database."""
    return [name for name in migration_files(migrations_dir) if name not in set(applied)]


def applied_migrations():
    """The filenames init_db.py has recorded in schema_migrations, or None when that table cannot be read (a
    database init_db.py has never run against)."""
    try:
        connection = mysql.connector.connect(**_connection_settings())
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT filename FROM schema_migrations")
            applied = [row[0] for row in cursor.fetchall()]
            cursor.close()
            return applied
        finally:
            connection.close()
    except mysql.connector.Error as error:
        current_app.logger.error("Could not read schema_migrations: %s", error)
        return None
