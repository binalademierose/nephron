-- Migration 016: the country a person lives in, asked once at registration, so the screening's "Where do you live?"
-- comes from the account instead of being typed again every time (services/fixed_answers.py). A patient record
-- gets the same, plus its own date of birth so its age is worked out, never typed.
-- Values are the screening catalog's own Country option values (USA, UK, India, Canada, Australia, Philippines, Other).
ALTER TABLE users ADD COLUMN country VARCHAR(40) NULL;
ALTER TABLE patient_records ADD COLUMN country VARCHAR(40) NULL;
ALTER TABLE patient_records ADD COLUMN date_of_birth DATE NULL;
