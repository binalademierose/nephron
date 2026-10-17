"""
user_store.py - saving and finding user accounts.

This is the only place that knows the SQL for users, professionals and sign-in attempts.
There are two stores with the same methods:
  * MySQLUserStore  - the real one, used by the running application.
  * MemoryUserStore - keeps everything in Python lists. The automated tests use it, so most tests are fast and
                      need no database. tests/test_user_store.py runs the SAME checks against both stores, so
                      they cannot drift apart.

A user is a plain dictionary with these keys:
  user_id, email, password_hash, full_name, username, date_of_birth, address, avatar, role, created_at,
  last_login_at, password_changed_at, profession_title, institution, license_number
  (username, date_of_birth are None only for an account from before Migration 010; address and avatar are always
  optional. profession_title/institution/license_number are None unless the role is 'professional'.)
"""
import mysql.connector
from flask import current_app

import db


class DuplicateEmailError(Exception):
    """An account with this email address already exists."""


class DuplicateUsernameError(Exception):
    """This username is already taken."""


def get_user_store():
    return current_app.extensions["user_store"]


USER_COLUMNS = """
    u.user_id, u.email, u.password_hash, u.full_name, u.username, u.date_of_birth, u.address, u.avatar,
    u.role, u.is_patient_record, u.is_admin, u.is_active, u.must_change_password, u.country, u.province_code, u.municipality_code, u.barangay_code, u.created_at, u.last_login_at, u.password_changed_at,
    p.profession_title, p.institution, p.license_number, p.verification_status, p.verified_at
"""
USER_FROM = "FROM users AS u LEFT JOIN professionals AS p ON p.user_id = u.user_id"

MYSQL_DUPLICATE_ENTRY = 1062     # MySQL's error number for "this value already exists in a UNIQUE column"


class MySQLUserStore:
    def create_user(self, values, password_hash, now):
        """Save a new account (and the professional's details, if any) all together, or not at all."""
        try:
            with db.transaction() as cursor:
                cursor.execute(
                    "INSERT INTO users (email, password_hash, full_name, username, date_of_birth, address, avatar, role, country, "
                    "province_code, municipality_code, barangay_code, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (values["email"], password_hash, values["full_name"], values.get("username"), values.get("date_of_birth"),
                    values.get("address"), values.get("avatar"), values["role"], values.get("country"),
                    values.get("province_code"), values.get("municipality_code"), values.get("barangay_code"), now),
                )
                user_id = cursor.lastrowid
                if values["professional"]:
                    details = values["professional"]
                    cursor.execute(
                        "INSERT INTO professionals (user_id, profession_title, institution, license_number) "
                        "VALUES (%s, %s, %s, %s)",
                        (user_id, details["profession_title"], details["institution"], details["license_number"]),
                    )
        except mysql.connector.IntegrityError as error:
            if error.errno == MYSQL_DUPLICATE_ENTRY:
                if "username" in str(error).lower():
                    raise DuplicateUsernameError(values["username"]) from error
                raise DuplicateEmailError(values["email"]) from error
            raise
        return user_id

    def find_by_username(self, username):
        return db.query_one(f"SELECT {USER_COLUMNS} {USER_FROM} WHERE u.username = %s", (username,))

    def find_by_email(self, email):
        return db.query_one(f"SELECT {USER_COLUMNS} {USER_FROM} WHERE u.email = %s", (email,))

    def find_by_id(self, user_id):
        return db.query_one(f"SELECT {USER_COLUMNS} {USER_FROM} WHERE u.user_id = %s", (user_id,))

    def search_professionals(self, term, limit=10):
        """Professional accounts whose email exactly matches term, or whose full name contains it (letter case and
        extra spaces ignored either way), by full name. A blank or whitespace-only term matches nothing.
        (A literal % or _ the person types is matched as a SQL wildcard, the same as LIKE always does - this
        can only make a search return MORE names, never fewer, and never anyone's actual data, so it is left as
        plain LIKE '%term%' rather than adding an ESCAPE clause to work around it.)"""
        term = term.strip()
        if not term:
            return []
        return db.query_all(
            f"SELECT {USER_COLUMNS} {USER_FROM} WHERE u.role = 'professional' AND (u.email = %s OR u.full_name LIKE %s) "
            "ORDER BY u.full_name LIMIT %s",
            (term, f"%{term}%", limit),
        )

    def list_accounts(self):
        """Every real person's account (never a patient record's shadow account), newest first - for the admin side."""
        rows = db.query_all(f"SELECT {USER_COLUMNS} FROM users AS u LEFT JOIN professionals AS p ON p.user_id = u.user_id "
                            "WHERE u.is_patient_record = 0 ORDER BY u.created_at DESC, u.user_id DESC")
        return [dict(row) for row in rows]

    def set_active(self, user_id, is_active):
        db.execute("UPDATE users SET is_active = %s WHERE user_id = %s", (1 if is_active else 0, user_id))

    def delete_user(self, user_id):
        """Permanently remove this account. Every table that stores this person's own data has an ON DELETE CASCADE
        foreign key to users, so a single DELETE removes it all; references made BY others (clinical reviews a
        professional wrote, the activity log) are set to NULL and kept."""
        db.execute("DELETE FROM users WHERE user_id = %s", (user_id,))

    def set_must_change(self, user_id, must_change):
        db.execute("UPDATE users SET must_change_password = %s WHERE user_id = %s", (1 if must_change else 0, user_id))

    def set_admin(self, user_id, is_admin):
        db.execute("UPDATE users SET is_admin = %s WHERE user_id = %s", (1 if is_admin else 0, user_id))

    def set_location(self, user_id, location):
        """location: {province_code, municipality_code, barangay_code} - PSGC codes, or None for any not asked."""
        db.execute("UPDATE users SET province_code = %s, municipality_code = %s, barangay_code = %s WHERE user_id = %s",
                   (location.get("province_code"), location.get("municipality_code"), location.get("barangay_code"), user_id))

    def set_verification(self, user_id, status, now):
        db.execute("UPDATE professionals SET verification_status = %s, verified_at = %s WHERE user_id = %s",
                   (status, now if status == "verified" else None, user_id))

    def mark_login(self, user_id, now):
        db.execute("UPDATE users SET last_login_at = %s WHERE user_id = %s", (now, user_id))

    def update_password(self, user_id, password_hash, now):
        db.execute("UPDATE users SET password_hash = %s, password_changed_at = %s WHERE user_id = %s",
                   (password_hash, now, user_id))

    # ---- sign-in attempts ----
    def record_login_attempt(self, email, ip_address, was_successful, now):
        db.execute(
            "INSERT INTO login_attempts (email, ip_address, was_successful, attempted_at) VALUES (%s, %s, %s, %s)",
            (email, ip_address, 1 if was_successful else 0, now),
        )

    def count_failed_attempts(self, email, since):
        row = db.query_one(
            "SELECT COUNT(*) AS failures FROM login_attempts "
            "WHERE email = %s AND was_successful = 0 AND attempted_at >= %s",
            (email, since),
        )
        return int(row["failures"])

    def clear_failed_attempts(self, email):
        db.execute("DELETE FROM login_attempts WHERE email = %s AND was_successful = 0", (email,))

    def delete_old_login_attempts(self, before):
        db.execute("DELETE FROM login_attempts WHERE attempted_at < %s", (before,))


class MemoryUserStore:
    """The same methods, kept in memory. For automated tests only."""

    def __init__(self):
        self._users = {}
        self._attempts = []
        self._next_id = 1

    def create_user(self, values, password_hash, now):
        if any(user["email"].lower() == values["email"].lower() for user in self._users.values()):
            raise DuplicateEmailError(values["email"])
        username = values.get("username")
        if username and any((user.get("username") or "").lower() == username.lower() for user in self._users.values()):
            raise DuplicateUsernameError(username)
        details = values["professional"] or {}
        user_id = self._next_id
        self._next_id += 1
        self._users[user_id] = {
            "user_id": user_id, "email": values["email"], "password_hash": password_hash,
            "full_name": values["full_name"], "username": username, "date_of_birth": values.get("date_of_birth"),
            "address": values.get("address"), "avatar": values.get("avatar"), "country": values.get("country"),
            "province_code": values.get("province_code"), "municipality_code": values.get("municipality_code"),
            "barangay_code": values.get("barangay_code"),
            "role": values["role"], "is_patient_record": bool(values.get("is_patient_record")), "created_at": now,
            "is_admin": bool(values.get("is_admin")), "is_active": True, "must_change_password": False,
            "last_login_at": None, "password_changed_at": None,
            "profession_title": details.get("profession_title"), "institution": details.get("institution"),
            "license_number": details.get("license_number"),
            "verification_status": "pending" if values["role"] == "professional" else None, "verified_at": None,
        }
        return user_id

    def find_by_email(self, email):
        for user in self._users.values():
            if user["email"].lower() == email.lower():          # MySQL compares emails without regard to case
                return dict(user)
        return None

    def find_by_id(self, user_id):
        user = self._users.get(user_id)
        return dict(user) if user else None

    def find_by_username(self, username):
        for user in self._users.values():
            if (user.get("username") or "").lower() == username.lower():
                return dict(user)
        return None

    def search_professionals(self, term, limit=10):
        term = term.strip()
        if not term:
            return []
        lowered = term.lower()
        matches = [dict(user) for user in self._users.values()
                  if user["role"] == "professional" and (user["email"].lower() == lowered or lowered in user["full_name"].lower())]
        matches.sort(key=lambda user: user["full_name"])
        return matches[:limit]

    def list_accounts(self):
        people = [dict(u) for u in self._users.values() if not u.get("is_patient_record")]
        people.sort(key=lambda u: (u["created_at"], u["user_id"]), reverse=True)
        return people

    def set_active(self, user_id, is_active):
        self._users[user_id]["is_active"] = bool(is_active)

    def delete_user(self, user_id):
        self._users.pop(user_id, None)

    def set_must_change(self, user_id, must_change):
        self._users[user_id]["must_change_password"] = bool(must_change)

    def set_admin(self, user_id, is_admin):
        self._users[user_id]["is_admin"] = bool(is_admin)

    def set_location(self, user_id, location):
        for field in ("province_code", "municipality_code", "barangay_code"):
            self._users[user_id][field] = location.get(field)

    def set_verification(self, user_id, status, now):
        self._users[user_id]["verification_status"] = status
        self._users[user_id]["verified_at"] = now if status == "verified" else None

    def mark_login(self, user_id, now):
        self._users[user_id]["last_login_at"] = now

    def update_password(self, user_id, password_hash, now):
        self._users[user_id]["password_hash"] = password_hash
        self._users[user_id]["password_changed_at"] = now

    def record_login_attempt(self, email, ip_address, was_successful, now):
        self._attempts.append({"email": email, "ip_address": ip_address, "was_successful": was_successful, "attempted_at": now})

    def count_failed_attempts(self, email, since):
        return sum(1 for a in self._attempts if a["email"].lower() == email.lower() and not a["was_successful"] and a["attempted_at"] >= since)

    def clear_failed_attempts(self, email):
        self._attempts = [a for a in self._attempts if not (a["email"].lower() == email.lower() and not a["was_successful"])]

    def delete_old_login_attempts(self, before):
        self._attempts = [a for a in self._attempts if a["attempted_at"] >= before]
