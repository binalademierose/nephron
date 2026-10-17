-- Migration 021: a patient record's gender, as the professional chose it (Male, Female, Gay man, Non-binary...).
-- The existing `sex` column keeps the sex the screening model needs (Male/Female) - worked out from the gender, or
-- asked as "sex assigned at birth" when the gender does not tell (services/patient_records.py). A General User's
-- own gender is saved with each screening's answers, so their account needs no new column.
-- Values are the screening catalog's own Gender option values (ml/feature_catalog.json).
ALTER TABLE patient_records ADD COLUMN gender VARCHAR(40) NULL;
