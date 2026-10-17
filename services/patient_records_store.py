"""
patient_records_store.py - the patient_records table (each row wraps its own shadow `users` row - see the
migration's own comment for why). Creating one writes both rows together; everything else reads through the join.

Same MySQL + Memory pattern as the other stores.
"""
import mysql.connector
from flask import current_app

import db

PATIENT_COLUMNS = ("pr.patient_record_id, pr.user_id, pr.professional_user_id, pr.patient_code, pr.age, pr.sex, "
                   "pr.date_of_birth, pr.country, pr.gender, pr.province_code, pr.municipality_code, pr.barangay_code, pr.created_at, u.full_name")
PATIENT_FROM = "FROM patient_records AS pr JOIN users AS u ON u.user_id = pr.user_id"


def get_patient_records_store():
    return current_app.extensions["patient_records_store"]


class MySQLPatientRecordsStore:
    def locations(self):
        """[(user_id, province_code, municipality_code, barangay_code)] for every patient record - the heatmap's input."""
        rows = db.query_all("SELECT user_id, province_code, municipality_code, barangay_code FROM patient_records")
        return [(r["user_id"], r["province_code"], r["municipality_code"], r["barangay_code"]) for r in rows]

    def create(self, professional_user_id, full_name, age, sex, shadow_email, password_hash, now, date_of_birth=None, country=None, gender=None, location=None):
        """Creates the shadow user and the patient_records row together, then assigns the code ("NPH-0001") from
        the new row's own id - the code can only be known once the insert has happened, so this is two statements
        in the one transaction, not one."""
        with db.transaction() as cursor:
            cursor.execute(
                "INSERT INTO users (email, password_hash, full_name, role, is_patient_record, created_at) "
                "VALUES (%s, %s, %s, 'general', 1, %s)",
                (shadow_email, password_hash, full_name, now),
            )
            user_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO patient_records (user_id, professional_user_id, patient_code, age, sex, gender, date_of_birth, country, "
                "province_code, municipality_code, barangay_code, created_at) VALUES (%s, %s, '', %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (user_id, professional_user_id, age, sex, gender, date_of_birth, country,
                 (location or {}).get("province_code"), (location or {}).get("municipality_code"), (location or {}).get("barangay_code"), now),
            )
            patient_record_id = cursor.lastrowid
            code = f"NPH-{patient_record_id:04d}"
            cursor.execute("UPDATE patient_records SET patient_code = %s WHERE patient_record_id = %s", (code, patient_record_id))
        return user_id, code

    def get_by_user_id(self, user_id):
        row = db.query_one(f"SELECT {PATIENT_COLUMNS} {PATIENT_FROM} WHERE pr.user_id = %s", (user_id,))
        return dict(row) if row else None

    def get_by_code(self, patient_code):
        row = db.query_one(f"SELECT {PATIENT_COLUMNS} {PATIENT_FROM} WHERE pr.patient_code = %s", (patient_code,))
        return dict(row) if row else None

    def list_for_professional(self, professional_user_id):
        """This professional's own patient records, newest first."""
        rows = db.query_all(f"SELECT {PATIENT_COLUMNS} {PATIENT_FROM} WHERE pr.professional_user_id = %s "
                            "ORDER BY pr.created_at DESC, pr.patient_record_id DESC", (professional_user_id,))
        return [dict(row) for row in rows]

    def owned_by(self, user_id, professional_user_id):
        """True only if this patient record exists AND belongs to this professional - the one check every route
        that acts on a patient record makes first."""
        return db.query_one("SELECT 1 AS one FROM patient_records WHERE user_id = %s AND professional_user_id = %s",
                            (user_id, professional_user_id)) is not None


class MemoryPatientRecordsStore:
    def locations(self):
        """[(user_id, province_code, municipality_code, barangay_code)] for every patient record - the heatmap's input."""
        return [(r["user_id"], r.get("province_code"), r.get("municipality_code"), r.get("barangay_code")) for r in self._records.values()]

    def __init__(self, user_store):
        self._user_store = user_store
        self._records = {}          # user_id -> record dict
        self._next_id = 1

    def create(self, professional_user_id, full_name, age, sex, shadow_email, password_hash, now, date_of_birth=None, country=None, gender=None, location=None):
        user_id = self._user_store.create_user(
            {"email": shadow_email, "full_name": full_name, "role": "general", "is_patient_record": True, "professional": None}, password_hash, now)
        patient_record_id = self._next_id
        self._next_id += 1
        code = f"NPH-{patient_record_id:04d}"
        self._records[user_id] = {"patient_record_id": patient_record_id, "user_id": user_id, "professional_user_id": professional_user_id,
                                  "patient_code": code, "age": age, "sex": sex, "gender": gender, "date_of_birth": date_of_birth, "country": country,
                                  "province_code": (location or {}).get("province_code"), "municipality_code": (location or {}).get("municipality_code"),
                                  "barangay_code": (location or {}).get("barangay_code"),
                                  "created_at": now}
        return user_id, code

    def _described(self, record):
        user = self._user_store.find_by_id(record["user_id"])
        return {**record, "full_name": user["full_name"]}

    def get_by_user_id(self, user_id):
        record = self._records.get(user_id)
        return self._described(record) if record else None

    def get_by_code(self, patient_code):
        for record in self._records.values():
            if record["patient_code"] == patient_code:
                return self._described(record)
        return None

    def list_for_professional(self, professional_user_id):
        mine = [self._described(r) for r in self._records.values() if r["professional_user_id"] == professional_user_id]
        mine.sort(key=lambda r: (r["created_at"], r["patient_record_id"]), reverse=True)
        return mine

    def owned_by(self, user_id, professional_user_id):
        record = self._records.get(user_id)
        return record is not None and record["professional_user_id"] == professional_user_id
