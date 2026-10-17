"""
followup_appointment_store.py - a professional's scheduled visit for their patient: create, list, get, update
(reschedule/change purpose or notes), change status (complete/cancel), and delete.

Same MySQL + Memory pattern as the other stores. Every write here is scoped to the professional who owns the row
(only they may edit or delete their own appointment) - services/followup_appointments.py checks CURRENT
authorization on top of that before any write reaches here.
"""
import mysql.connector
from flask import current_app

import db


def get_followup_appointment_store():
    return current_app.extensions["followup_appointment_store"]


class MySQLFollowUpAppointmentStore:
    def create(self, patient_user_id, professional_user_id, professional_name, profession_title, scheduled_at, purpose, notes, now):
        return db.execute(
            "INSERT INTO follow_up_appointments (patient_user_id, professional_user_id, professional_name, profession_title, "
            "scheduled_at, purpose, notes, status, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, 'scheduled', %s, %s)",
            (patient_user_id, professional_user_id, professional_name, profession_title, scheduled_at, purpose, notes, now, now),
        )

    def get(self, appointment_id):
        return db.query_one(
            "SELECT appointment_id, patient_user_id, professional_user_id, professional_name, profession_title, "
            "scheduled_at, purpose, notes, status, created_at, updated_at FROM follow_up_appointments WHERE appointment_id = %s",
            (appointment_id,),
        )

    def list_for_patient(self, patient_user_id):
        return db.query_all(
            "SELECT appointment_id, patient_user_id, professional_user_id, professional_name, profession_title, "
            "scheduled_at, purpose, notes, status, created_at, updated_at FROM follow_up_appointments "
            "WHERE patient_user_id = %s ORDER BY scheduled_at ASC", (patient_user_id,),
        )

    def list_for_professional_patient(self, professional_user_id, patient_user_id):
        return db.query_all(
            "SELECT appointment_id, patient_user_id, professional_user_id, professional_name, profession_title, "
            "scheduled_at, purpose, notes, status, created_at, updated_at FROM follow_up_appointments "
            "WHERE professional_user_id = %s AND patient_user_id = %s ORDER BY scheduled_at ASC", (professional_user_id, patient_user_id),
        )

    def list_for_professional(self, professional_user_id):
        """Every appointment this professional has scheduled, across every patient - soonest first."""
        return db.query_all(
            "SELECT appointment_id, patient_user_id, professional_user_id, professional_name, profession_title, "
            "scheduled_at, purpose, notes, status, created_at, updated_at FROM follow_up_appointments "
            "WHERE professional_user_id = %s ORDER BY scheduled_at ASC", (professional_user_id,),
        )

    def update(self, appointment_id, professional_user_id, scheduled_at, purpose, notes, now):
        """Only the professional who created it may edit it. True if a row was really changed."""
        with db.transaction() as cursor:
            cursor.execute(
                "UPDATE follow_up_appointments SET scheduled_at = %s, purpose = %s, notes = %s, updated_at = %s "
                "WHERE appointment_id = %s AND professional_user_id = %s",
                (scheduled_at, purpose, notes, now, appointment_id, professional_user_id),
            )
            return cursor.rowcount > 0

    def set_status(self, appointment_id, professional_user_id, status, now):
        with db.transaction() as cursor:
            cursor.execute(
                "UPDATE follow_up_appointments SET status = %s, updated_at = %s WHERE appointment_id = %s AND professional_user_id = %s",
                (status, now, appointment_id, professional_user_id),
            )
            return cursor.rowcount > 0

    def delete(self, appointment_id, professional_user_id):
        with db.transaction() as cursor:
            cursor.execute("DELETE FROM follow_up_appointments WHERE appointment_id = %s AND professional_user_id = %s",
                           (appointment_id, professional_user_id))
            return cursor.rowcount > 0


class MemoryFollowUpAppointmentStore:
    def __init__(self):
        self._rows = {}
        self._next_id = 1

    def create(self, patient_user_id, professional_user_id, professional_name, profession_title, scheduled_at, purpose, notes, now):
        appointment_id = self._next_id
        self._next_id += 1
        self._rows[appointment_id] = {
            "appointment_id": appointment_id, "patient_user_id": patient_user_id, "professional_user_id": professional_user_id,
            "professional_name": professional_name, "profession_title": profession_title, "scheduled_at": scheduled_at,
            "purpose": purpose, "notes": notes, "status": "scheduled", "created_at": now, "updated_at": now,
        }
        return appointment_id

    def get(self, appointment_id):
        row = self._rows.get(appointment_id)
        return dict(row) if row else None

    def list_for_patient(self, patient_user_id):
        mine = [dict(row) for row in self._rows.values() if row["patient_user_id"] == patient_user_id]
        mine.sort(key=lambda row: row["scheduled_at"])
        return mine

    def list_for_professional_patient(self, professional_user_id, patient_user_id):
        mine = [dict(row) for row in self._rows.values()
               if row["professional_user_id"] == professional_user_id and row["patient_user_id"] == patient_user_id]
        mine.sort(key=lambda row: row["scheduled_at"])
        return mine

    def list_for_professional(self, professional_user_id):
        mine = [dict(row) for row in self._rows.values() if row["professional_user_id"] == professional_user_id]
        mine.sort(key=lambda row: row["scheduled_at"])
        return mine

    def update(self, appointment_id, professional_user_id, scheduled_at, purpose, notes, now):
        row = self._rows.get(appointment_id)
        if row is None or row["professional_user_id"] != professional_user_id:
            return False
        row.update(scheduled_at=scheduled_at, purpose=purpose, notes=notes, updated_at=now)
        return True

    def set_status(self, appointment_id, professional_user_id, status, now):
        row = self._rows.get(appointment_id)
        if row is None or row["professional_user_id"] != professional_user_id:
            return False
        row.update(status=status, updated_at=now)
        return True

    def delete(self, appointment_id, professional_user_id):
        row = self._rows.get(appointment_id)
        if row is None or row["professional_user_id"] != professional_user_id:
            return False
        del self._rows[appointment_id]
        return True
