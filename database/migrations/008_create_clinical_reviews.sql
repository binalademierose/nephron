CREATE TABLE IF NOT EXISTS clinical_reviews (
    review_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    assessment_id INT UNSIGNED NOT NULL,
    professional_user_id INT UNSIGNED NULL,
    professional_name VARCHAR(120) NOT NULL,
    profession_title VARCHAR(80) NULL,
    note TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (review_id),
    KEY idx_clinical_reviews_assessment (assessment_id, created_at),
    CONSTRAINT fk_clinical_reviews_assessment FOREIGN KEY (assessment_id) REFERENCES assessments (assessment_id) ON DELETE CASCADE,
    CONSTRAINT fk_clinical_reviews_professional FOREIGN KEY (professional_user_id) REFERENCES users (user_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
