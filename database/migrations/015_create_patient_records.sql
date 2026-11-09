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

ALTER TABLE users ADD COLUMN is_patient_record TINYINT(1) NOT NULL DEFAULT 0;
