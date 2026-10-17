-- Migration 007: authorizations - a patient sharing their assessment history with a professional.
--
-- One row per (patient, professional) PAIR (the UNIQUE KEY below), not one row per event: the relationship has a
-- current status that changes over time (pending -> accepted, or pending -> declined, or accepted -> revoked, and
-- a declined or revoked pair may be requested again, moving the SAME row back to pending). This is a relationship
-- toggle, not a permanent clinical record - the assessments it grants a view of are the permanent records, and are
-- never touched by this table.
--
--   pending    the patient asked, the professional has not answered yet
--   accepted   the professional may see this patient's full assessment history (services/authorizations.py decides
--              what "full" means, this table only says whether the professional may look at all)
--   declined   the professional said no. requested_at/responded_at show when
--   revoked    it was accepted, then EITHER side ended it - who is not distinguished here, only that it is over
--
-- Always initiated by the patient searching for the professional's email (services/authorizations.py), there is no
-- professional-initiated request in this version. Deleting either the patient or the professional deletes the row
-- (ON DELETE CASCADE): an authorization cannot outlive either side of it.
CREATE TABLE IF NOT EXISTS authorizations (
    authorization_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    patient_user_id INT UNSIGNED NOT NULL,
    professional_user_id INT UNSIGNED NOT NULL,
    status ENUM('pending', 'accepted', 'declined', 'revoked') NOT NULL DEFAULT 'pending',
    requested_at DATETIME NOT NULL,
    responded_at DATETIME NULL,
    PRIMARY KEY (authorization_id),
    UNIQUE KEY uq_authorizations_pair (patient_user_id, professional_user_id),
    KEY idx_authorizations_professional (professional_user_id, status),
    CONSTRAINT fk_authorizations_patient FOREIGN KEY (patient_user_id) REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_authorizations_professional FOREIGN KEY (professional_user_id) REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
