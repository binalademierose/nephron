-- Migration 018: the signs read from an uploaded lab report that it is a real report about the right person (the
-- name on it, its date, a signature or attestation, a laboratory's name) - see services/lab_verification.py.
-- JSON text. Signs only, never proof - shown beside the values, and the person still confirms the report is theirs.
ALTER TABLE lab_documents ADD COLUMN verification TEXT NULL;
