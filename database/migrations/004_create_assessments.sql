-- Migration 004: saved assessments. One permanent row for every screening a person completes.
-- A row is never edited or replaced. A new screening is a new row, so history and comparisons stay true.
-- probability is the model's predicted probability as a fraction from 0 to 1 (0.31 means 31 percent).
-- classification is the model's own low or high result, decided with the threshold it was validated with.
-- threshold_used and model_version record which cut-off and which model produced the result, when they are known.
-- assessed_at is stored in UTC like every other time. Deleting a user deletes their assessments (ON DELETE CASCADE).
CREATE TABLE IF NOT EXISTS assessments (
    assessment_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    assessment_type ENUM('preliminary', 'enhanced') NOT NULL,
    probability DECIMAL(7, 6) NOT NULL,
    classification ENUM('low', 'high') NOT NULL,
    threshold_used DECIMAL(7, 6) NULL,
    model_version VARCHAR(100) NULL,
    assessed_at DATETIME NOT NULL,
    PRIMARY KEY (assessment_id),
    KEY idx_assessments_user_time (user_id, assessed_at),
    CONSTRAINT fk_assessments_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT chk_assessments_probability CHECK (probability >= 0 AND probability <= 1),
    CONSTRAINT chk_assessments_threshold CHECK (threshold_used IS NULL OR (threshold_used >= 0 AND threshold_used <= 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
