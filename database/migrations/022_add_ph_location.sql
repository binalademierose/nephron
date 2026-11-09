ALTER TABLE users ADD COLUMN province_code VARCHAR(12) NULL;

ALTER TABLE users ADD COLUMN municipality_code VARCHAR(12) NULL;

ALTER TABLE users ADD COLUMN barangay_code VARCHAR(12) NULL;

ALTER TABLE patient_records ADD COLUMN province_code VARCHAR(12) NULL;

ALTER TABLE patient_records ADD COLUMN municipality_code VARCHAR(12) NULL;

ALTER TABLE patient_records ADD COLUMN barangay_code VARCHAR(12) NULL;
