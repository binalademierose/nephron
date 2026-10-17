"""
consent_store.py - the append-only record of a patient agreeing to share their assessment history.

Same MySQL + Memory pattern as the other stores. There is deliberately no update and no delete here: an
agreement that happened stays on record (the row only goes if the account itself is deleted).
"""
import mysql.connector
from flask import current_app

import db


def get_consent_store():
    return current_app.extensions["consent_store"]


class MySQLConsentStore:
    def record(self, patient_user_id, professional_user_id, consent_type, consent_version, now):
        return db.execute(
            "INSERT INTO consent_records (patient_user_id, professional_user_id, consent_type, consent_version, consented_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (patient_user_id, professional_user_id, consent_type, consent_version, now),
        )

    def list_for_patient(self, patient_user_id):
        """Every agreement this patient has given, newest first."""
        return db.query_all(
            "SELECT consent_id, patient_user_id, professional_user_id, consent_type, consent_version, consented_at "
            "FROM consent_records WHERE patient_user_id = %s ORDER BY consented_at DESC, consent_id DESC",
            (patient_user_id,),
        )


class MemoryConsentStore:
    def __init__(self):
        self._rows = []
        self._next_id = 1

    def record(self, patient_user_id, professional_user_id, consent_type, consent_version, now):
        consent_id = self._next_id
        self._next_id += 1
        self._rows.append({"consent_id": consent_id, "patient_user_id": patient_user_id, "professional_user_id": professional_user_id,
                           "consent_type": consent_type, "consent_version": consent_version, "consented_at": now})
        return consent_id

    def list_for_patient(self, patient_user_id):
        mine = [dict(row) for row in self._rows if row["patient_user_id"] == patient_user_id]
        mine.sort(key=lambda row: (row["consented_at"], row["consent_id"]), reverse=True)
        return mine
