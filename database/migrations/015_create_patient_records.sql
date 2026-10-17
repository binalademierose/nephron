-- Migration 015: patient_records - a patient a professional is managing directly (a walk-in, or anyone without
-- their own Nephron account), as opposed to a General User who registered and shared their own history.
--
-- Each one wraps its own row in `users` (role 'patient_record'): no email a person actually owns, no working
-- password, and role_required() throughout this app already only ever allows 'general' or 'professional' - so a
-- patient_record account can never sign in or reach any page meant for a person. Wrapping a real users row like
-- this, rather than inventing a second "who does this assessment belong to" column, is deliberate: every table
-- built around assessments.user_id (assessment_inputs, clinical_reviews, follow_up_appointments,
-- checklist_completions, notifications) keeps working for a patient_record with no change at all.
--
-- patient_code is the human-facing id ("NPH-0001", assigned in order across every professional, never reused).
CREATE TABLE IF NOT EXISTS patient_records (
    patient_record_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    professional_user_id INT UNSIGNED NOT NULL,
    patient_code VARCHAR(20) NOT NULL,
    age TINYINT UNSIGNED NOT NULL,
    sex VARCHAR(20) NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (patient_record_id),
    UNIQUE KEY uq_patient_records_user (user_id),
    UNIQUE KEY uq_patient_records_code (patient_code),
    KEY idx_patient_records_professional (professional_user_id, created_at),
    CONSTRAINT fk_patient_records_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_patient_records_professional FOREIGN KEY (professional_user_id) REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- A patient_record's own shadow account is not really a person's own account: this flag marks it so, wherever
-- a users row is read. Its role stays a real, existing value ('general') rather than widening that ENUM - this
-- project's migrations only ever ADD a column, never MODIFY one (see tests/test_migrations.py) - and the flag is
-- the one thing that actually needs checking: routes/auth_hooks.py refuses to sign one in as anybody at all, and
-- services/auth_service.py refuses it at the password check too, so this is checked twice, not just once.
ALTER TABLE users ADD COLUMN is_patient_record TINYINT(1) NOT NULL DEFAULT 0;
