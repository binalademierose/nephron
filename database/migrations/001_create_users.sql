-- Migration 001: user accounts.
-- One row for every person who can sign in. A password is never stored, only its salted hash.
-- All times are stored in UTC and are written by the application, not by MySQL.
-- role is fixed to two values on purpose: there is no administrator in this version.
CREATE TABLE IF NOT EXISTS users (
    user_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    email VARCHAR(254) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(120) NOT NULL,
    role ENUM('general', 'professional') NOT NULL,
    created_at DATETIME NOT NULL,
    last_login_at DATETIME NULL,
    password_changed_at DATETIME NULL,
    PRIMARY KEY (user_id),
    UNIQUE KEY uq_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
