-- Migration 008: clinical_reviews - a note a professional writes about ONE specific assessment they were
-- authorized to see. Append-only, like assessments themselves: a professional who wants to say something new
-- adds another row, never edits or deletes an earlier one - the patient's permanent record of what was said.
--
-- professional_name and profession_title are a SNAPSHOT taken when the note was written, not a live join to
-- professionals: if the professional's account is later deleted (ON DELETE SET NULL, professional_user_id only),
-- or they change their name or title, the patient's record of what was said and by whom at the time is unaffected.
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
