-- Migration 014: consent_records - an append-only record of every time a patient agreed to share their
-- assessment history with a professional. One row per agreement, never edited or deleted by the application
-- (only removed if the account itself is deleted). authorizations holds the CURRENT state of a share (pending,
-- accepted, revoked) and is overwritten as it changes, so it cannot answer "when did this person agree, and to
-- what?" - this table can. consent_version names the exact wording the person saw and agreed to (see
-- services/consents.py), so a later change to that wording never rewrites what an earlier agreement covered.
CREATE TABLE IF NOT EXISTS consent_records (
    consent_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    patient_user_id INT UNSIGNED NOT NULL,
    professional_user_id INT UNSIGNED NOT NULL,
    consent_type ENUM('share_history') NOT NULL,
    consent_version VARCHAR(30) NOT NULL,
    consented_at DATETIME NOT NULL,
    PRIMARY KEY (consent_id),
    KEY idx_consent_patient (patient_user_id, professional_user_id, consented_at),
    CONSTRAINT fk_consent_patient FOREIGN KEY (patient_user_id) REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_consent_professional FOREIGN KEY (professional_user_id) REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
