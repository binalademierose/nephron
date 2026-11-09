CREATE TABLE IF NOT EXISTS checklist_daily (
    checklist_daily_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    tip_id VARCHAR(60) NOT NULL,
    completed_on DATE NOT NULL,
    completed_at DATETIME NOT NULL,
    PRIMARY KEY (checklist_daily_id),
    UNIQUE KEY uq_checklist_daily (user_id, tip_id, completed_on),
    KEY idx_checklist_daily_user_day (user_id, completed_on),
    CONSTRAINT fk_checklist_daily_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
