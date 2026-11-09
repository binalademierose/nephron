CREATE TABLE IF NOT EXISTS professionals (
    user_id INT UNSIGNED NOT NULL,
    profession_title VARCHAR(80) NOT NULL,
    institution VARCHAR(120) NULL,
    license_number VARCHAR(50) NULL,
    PRIMARY KEY (user_id),
    CONSTRAINT fk_professionals_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
