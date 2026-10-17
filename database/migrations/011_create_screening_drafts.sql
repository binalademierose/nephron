-- Migration 011: screening_drafts - an unfinished screening's answers, saved automatically as the person fills
-- the form in, so a refresh, a closed tab, or navigating away never loses their progress.
--
-- One row per (user, assessment_type): starting a new draft of the same type overwrites the same row rather than
-- creating another one - there is never more than one open draft per type per person. A completed assessment
-- deletes its own draft (routes/screening_routes.py, routes/lab_routes.py), and this table only ever holds
-- UNFINISHED work, never a permanent record - assessments and assessment_inputs are that.
--
-- answers_json is the same shape as the form's own POST body (every field name to its current text value), so
-- resuming a draft simply re-renders the form with these as the starting values - nothing here is trusted as a
-- real answer until the person submits the form for real and services/screening_contract.py checks it again.
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
