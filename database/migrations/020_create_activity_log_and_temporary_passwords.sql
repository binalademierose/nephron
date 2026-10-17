-- Migration 020: an activity log for the administrator, and temporary passwords set by an administrator.
-- activity_log records WHAT happened, WHO did it and to WHOM - never anyone's health information (no answers,
-- probabilities or results). A deleted account leaves its entries in place, with the person shown as removed.
CREATE TABLE IF NOT EXISTS activity_log (
    activity_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    actor_user_id INT UNSIGNED NULL,
    action VARCHAR(40) NOT NULL,
    target_user_id INT UNSIGNED NULL,
    details VARCHAR(255) NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (activity_id),
    KEY idx_activity_created (created_at),
    KEY idx_activity_action (action),
    CONSTRAINT fk_activity_actor FOREIGN KEY (actor_user_id) REFERENCES users (user_id) ON DELETE SET NULL,
    CONSTRAINT fk_activity_target FOREIGN KEY (target_user_id) REFERENCES users (user_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
-- An administrator's password reset gives a temporary password the person must replace at their next sign-in.
ALTER TABLE users ADD COLUMN must_change_password TINYINT(1) NOT NULL DEFAULT 0;
