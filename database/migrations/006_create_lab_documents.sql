ALTER TABLE assessments
    ADD COLUMN source_assessment_id INT UNSIGNED NULL AFTER assessment_type,
    ADD CONSTRAINT fk_assessments_source FOREIGN KEY (source_assessment_id) REFERENCES assessments (assessment_id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS lab_documents (
    lab_document_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    status ENUM('uploaded', 'extracted', 'confirmed', 'discarded') NOT NULL DEFAULT 'uploaded',
    original_filename VARCHAR(255) NOT NULL,
    stored_filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(100) NOT NULL,
    ocr_values TEXT NULL,
    confirmed_values TEXT NULL,
    assessment_id INT UNSIGNED NULL,
    uploaded_at DATETIME NOT NULL,
    confirmed_at DATETIME NULL,
    PRIMARY KEY (lab_document_id),
    KEY idx_lab_documents_user_time (user_id, uploaded_at),
    CONSTRAINT fk_lab_documents_user FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
    CONSTRAINT fk_lab_documents_assessment FOREIGN KEY (assessment_id) REFERENCES assessments (assessment_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
