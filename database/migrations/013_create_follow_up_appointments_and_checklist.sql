-- Migration 013: follow_up_appointments and checklist_completions.
--
-- follow_up_appointments is a genuine scheduled visit a professional sets for their patient - date, time,
-- purpose, and optional notes - distinct from follow_up_requests (migration 009, "please screen again soon",
-- which only bypasses the reassessment waiting period and has no date or time of its own). A professional may
-- add, edit, or cancel their own appointments for a patient they are currently authorized for - the patient sees
-- them on their own Follow-up calendar. scheduled_at is stored in UTC, like every other timestamp in this
-- project - it is entered as a local date and time and converted once, by services/followup_appointments.py.
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

-- checklist_completions: one row per (person, tip) they have marked complete. A tip's own text and category
-- always come fresh from services/kidney_tips.py - only the checked/unchecked state persists here, keyed by the
-- tip's own stable id string, never a copy of its wording (so improving a tip's wording later never orphans
-- anyone's progress).
CREATE TABLE IF NOT EXISTS checklist_completions (
    completion_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    tip_id VARCHAR(60) NOT NULL,
    completed_at DATETIME NOT NULL,
    PRIMARY KEY (completion_id),
    UNIQUE KEY uq_checklist_user_tip (user_id, tip_id),
    CONSTRAINT fk_checklist_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
