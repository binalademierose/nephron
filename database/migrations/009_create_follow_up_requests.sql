CREATE TABLE IF NOT EXISTS follow_up_requests (
    follow_up_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    patient_user_id INT UNSIGNED NOT NULL,
    professional_user_id INT UNSIGNED NULL,
    professional_name VARCHAR(120) NOT NULL,
    profession_title VARCHAR(80) NULL,
    message VARCHAR(500) NULL,
    requested_at DATETIME NOT NULL,
    fulfilled_at DATETIME NULL,
    PRIMARY KEY (follow_up_id),
    KEY idx_follow_up_patient (patient_user_id, fulfilled_at),
    CONSTRAINT fk_follow_up_patient FOREIGN KEY (patient_user_id) REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_follow_up_professional FOREIGN KEY (professional_user_id) REFERENCES users (user_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
