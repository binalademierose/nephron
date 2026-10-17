-- Migration 005: the answers behind each assessment.
-- One row per assessment, saved at the same moment, holding the exact inputs the model was given (as JSON text).
-- It is a permanent snapshot: it is never edited, so a result can always be traced back to what produced it.
-- It also keeps the height and weight that were typed, because the model itself only uses the BMI worked out from them.
-- Deleting an assessment deletes its snapshot (ON DELETE CASCADE).
CREATE TABLE IF NOT EXISTS assessment_inputs (
    assessment_id INT UNSIGNED NOT NULL,
    inputs TEXT NOT NULL,
    PRIMARY KEY (assessment_id),
    CONSTRAINT fk_assessment_inputs_assessment FOREIGN KEY (assessment_id) REFERENCES assessments (assessment_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
