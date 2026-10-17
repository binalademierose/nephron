-- Migration 012: notifications - one row per notification, always for a real event that already happened
-- (routes/authorization_routes.py is the only place that creates one, right where the real event itself is
-- saved: a follow-up request, a clinical review, a share request, or a share response). Nothing here is
-- generated just to make the notification bell look busier.
CREATE TABLE IF NOT EXISTS notifications (
    notification_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    category ENUM('follow_up', 'clinical_review', 'share_request', 'share_response') NOT NULL,
    title VARCHAR(160) NOT NULL,
    body VARCHAR(500) NULL,
    link VARCHAR(255) NULL,
    is_read TINYINT(1) NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (notification_id),
    KEY idx_notifications_user (user_id, created_at),
    CONSTRAINT fk_notifications_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
