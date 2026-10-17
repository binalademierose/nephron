-- Migration 019: the administrator side.
-- is_admin marks an administrator account. The role column keeps its existing values (migrations only ADD, never
-- MODIFY), and the app reads an administrator as role "admin" (services/auth_service.py describe). Administrators
-- are created only with create_admin.py, never through public registration.
ALTER TABLE users ADD COLUMN is_admin TINYINT(1) NOT NULL DEFAULT 0;
-- is_active lets an administrator switch an account off without deleting anyone's records.
ALTER TABLE users ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 1;
-- A healthcare professional's licence check by an administrator: pending, verified or rejected.
ALTER TABLE professionals ADD COLUMN verification_status VARCHAR(20) NOT NULL DEFAULT 'pending';
ALTER TABLE professionals ADD COLUMN verified_at DATETIME NULL;
