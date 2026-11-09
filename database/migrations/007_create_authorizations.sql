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
