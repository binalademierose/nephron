CREATE TABLE IF NOT EXISTS follow_up_appointments (
    appointment_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    patient_user_id INT UNSIGNED NOT NULL,
    professional_user_id INT UNSIGNED NOT NULL,
    professional_name VARCHAR(120) NOT NULL,
    profession_title VARCHAR(120) NULL,
    scheduled_at DATETIME NOT NULL,
    purpose VARCHAR(200) NOT NULL,
    notes VARCHAR(1000) NULL,
    status ENUM('scheduled', 'completed', 'cancelled') NOT NULL DEFAULT 'scheduled',
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (appointment_id),
    KEY idx_followup_appt_patient (patient_user_id, scheduled_at),
    KEY idx_followup_appt_professional (professional_user_id, scheduled_at),
    CONSTRAINT fk_followup_appt_patient FOREIGN KEY (patient_user_id) REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_followup_appt_professional FOREIGN KEY (professional_user_id) REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS checklist_completions (
    completion_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    tip_id VARCHAR(60) NOT NULL,
    completed_at DATETIME NOT NULL,
    PRIMARY KEY (completion_id),
    UNIQUE KEY uq_checklist_user_tip (user_id, tip_id),
    CONSTRAINT fk_checklist_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
