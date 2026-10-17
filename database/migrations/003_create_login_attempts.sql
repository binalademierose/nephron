-- Migration 003: sign-in attempts, used to slow down password guessing.
-- Attempts are recorded by email text (not by user_id) so that an email address with no account
-- behaves exactly like one with an account, and nothing reveals which addresses are registered.
-- There is deliberately no foreign key here for the same reason.
CREATE TABLE IF NOT EXISTS login_attempts (
    attempt_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    email VARCHAR(254) NOT NULL,
    ip_address VARCHAR(45) NULL,
    was_successful TINYINT(1) NOT NULL,
    attempted_at DATETIME NOT NULL,
    PRIMARY KEY (attempt_id),
    KEY idx_login_attempts_email_time (email, attempted_at),
    KEY idx_login_attempts_time (attempted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
