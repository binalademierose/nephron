-- Migration 023: the re-assessment rule.
-- app_settings holds settings the administrator changes from the website. The first one is the waiting period
-- between screenings, in calendar months (0 = no waiting period). With no row the website uses 3 months
-- (services/reassessment_store.py), so this file only creates tables.
CREATE TABLE IF NOT EXISTS app_settings (
    setting_key VARCHAR(60) NOT NULL,
    setting_value VARCHAR(255) NOT NULL,
    updated_at DATETIME NOT NULL,
    updated_by INT UNSIGNED NULL,
    PRIMARY KEY (setting_key),
    CONSTRAINT fk_app_settings_admin FOREIGN KEY (updated_by) REFERENCES users (user_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
-- A General User who is still inside the waiting period may ask the administrator to screen again early.
-- Approving it opens ONE screening (a follow_up_requests row from the administrator). The next saved screening uses it up.
-- status: pending, approved, declined, or closed (a new screening was saved before anyone decided).
CREATE TABLE IF NOT EXISTS reassessment_requests (
    request_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    reason VARCHAR(300) NULL,
    status VARCHAR(10) NOT NULL DEFAULT 'pending',
    requested_at DATETIME NOT NULL,
    decided_at DATETIME NULL,
    decided_by INT UNSIGNED NULL,
    PRIMARY KEY (request_id),
    KEY idx_reassessment_status (status, requested_at),
    KEY idx_reassessment_user (user_id, requested_at),
    CONSTRAINT fk_reassessment_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_reassessment_admin FOREIGN KEY (decided_by) REFERENCES users (user_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
