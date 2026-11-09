ALTER TABLE users ADD COLUMN country VARCHAR(40) NULL;

ALTER TABLE patient_records ADD COLUMN country VARCHAR(40) NULL;

ALTER TABLE patient_records ADD COLUMN date_of_birth DATE NULL;
