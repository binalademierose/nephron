CREATE TABLE IF NOT EXISTS screening_drafts (
    draft_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    assessment_type ENUM('preliminary', 'enhanced') NOT NULL,
    answers_json TEXT NOT NULL,
    current_step VARCHAR(40) NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (draft_id),
    UNIQUE KEY uq_screening_drafts_user_type (user_id, assessment_type),
    CONSTRAINT fk_screening_drafts_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
