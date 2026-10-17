-- Migration 010: username, date_of_birth, address, avatar on users.
--
-- All four are nullable at the database level, so this migration never breaks an existing row: every NEW
-- registration is required (by services/validation.py, not by the database) to fill in username and date of
-- birth, address stays optional there too, matching how little of it Nephron actually needs. avatar names one of
-- a small, fixed set of preset pictures (static/images/avatars/) - never an uploaded file, so there is nothing here
-- to store, scan or serve on someone else's behalf.
--
-- uq_users_username is its own statement (not "ADD UNIQUE KEY" inside the ALTER TABLE) because a column added by
-- ALTER TABLE cannot carry a UNIQUE constraint in every engine this project runs on.
ALTER TABLE users ADD COLUMN username VARCHAR(32) NULL AFTER full_name;
ALTER TABLE users ADD COLUMN date_of_birth DATE NULL AFTER username;
ALTER TABLE users ADD COLUMN address VARCHAR(255) NULL AFTER date_of_birth;
ALTER TABLE users ADD COLUMN avatar VARCHAR(40) NULL AFTER address;
CREATE UNIQUE INDEX uq_users_username ON users (username);
