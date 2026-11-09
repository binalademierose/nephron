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
