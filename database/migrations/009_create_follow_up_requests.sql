-- Migration 009: follow_up_requests - a professional asking their patient to screen again (either stage), with an
-- optional message. requested_at/fulfilled_at, not a status column: "open" is simply fulfilled_at IS NULL, and it
-- is set automatically (services/followups.py) the moment the patient's next assessment - of EITHER type - is
-- saved after requested_at. Nothing here overrides what that next assessment says, it only marks that the ask was
-- answered. An open request lets its patient screen again immediately, even during REASSESSMENT_DAYS's normal
-- waiting period (services/eligibility.py) - a professional's clinical judgement is allowed to move a patient's
-- own timeline, never the other way around.
--
-- professional_name/profession_title are a snapshot for the same reason clinical_reviews takes one: the request
-- and what it said stay readable to the patient even if the professional's account is later deleted.
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
