-- Migration 006: Stage 2 (Enhanced Screening) lab documents, and where an enhanced assessment came from.
--
-- source_assessment_id on assessments: for an 'enhanced' assessment, which 'preliminary' assessment its
-- non-laboratory answers were pulled from (Enhanced Screening is an extension of a Preliminary screening, not a
-- fresh questionnaire). NULL for a 'preliminary' assessment, and NULL for an 'enhanced' one whose source was later
-- deleted (ON DELETE SET NULL): the enhanced result and its own saved inputs stay, only the traceability link is lost.
--
-- lab_documents: one row per uploaded file. It moves through a small number of stages:
--   uploaded    just received, not yet processed
--   extracted   OCR has produced candidate values (ocr_values holds them), waiting for the person to confirm
--   confirmed   the person reviewed and confirmed the values (confirmed_values holds what they confirmed),
--               assessment_id then points at the Enhanced Screening result those values produced
--   discarded   the person chose not to use this upload (for example, they re-uploaded a clearer photo)
-- ocr_values and confirmed_values are JSON text, in the same shape as assessment_inputs.inputs: only the fields
-- that were actually read or confirmed, never a placeholder for one that was not. The stored file itself is not
-- this table's concern (services/lab_documents.py keeps the path on disk), this table is the audit trail of what
-- came out of it and what the person did about it. Deleting a user deletes their uploads (ON DELETE CASCADE).
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
