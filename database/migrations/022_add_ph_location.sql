-- Migration 022: where in the Philippines a person lives, for the administrator's (LGU's) heatmap.
-- Saved as official PSGC codes (Philippine Standard Geographic Code). Anyone in the Philippines gives a province.
-- Anyone in Pangasinan also gives a municipality or city and a barangay (services/ph_locations.py).
-- A patient record made by a professional gets the same three fields.
ALTER TABLE users ADD COLUMN province_code VARCHAR(12) NULL;
ALTER TABLE users ADD COLUMN municipality_code VARCHAR(12) NULL;
ALTER TABLE users ADD COLUMN barangay_code VARCHAR(12) NULL;
ALTER TABLE patient_records ADD COLUMN province_code VARCHAR(12) NULL;
ALTER TABLE patient_records ADD COLUMN municipality_code VARCHAR(12) NULL;
ALTER TABLE patient_records ADD COLUMN barangay_code VARCHAR(12) NULL;
