CREATE TABLE IF NOT EXISTS assessment_inputs (
    assessment_id INT UNSIGNED NOT NULL,
    inputs TEXT NOT NULL,
    PRIMARY KEY (assessment_id),
    CONSTRAINT fk_assessment_inputs_assessment FOREIGN KEY (assessment_id) REFERENCES assessments (assessment_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
