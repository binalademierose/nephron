ALTER TABLE users ADD COLUMN username VARCHAR(32) NULL AFTER full_name;

ALTER TABLE users ADD COLUMN date_of_birth DATE NULL AFTER username;

ALTER TABLE users ADD COLUMN address VARCHAR(255) NULL AFTER date_of_birth;

ALTER TABLE users ADD COLUMN avatar VARCHAR(40) NULL AFTER address;

CREATE UNIQUE INDEX uq_users_username ON users (username);
