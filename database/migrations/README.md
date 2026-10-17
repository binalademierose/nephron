# Database migrations

Numbered `.sql` files, applied in order by `python init_db.py`. A file that was already applied is skipped,
so running it again is always safe.

| File | Adds | Phase |
|---|---|---|
| `001_create_users.sql` | `users`: who can sign in, their role and password hash | 2 |
| `002_create_professionals.sql` | `professionals`: details typed in by healthcare professionals | 2 |
| `003_create_login_attempts.sql` | `login_attempts`: slows down password guessing | 2 |
| `004_create_assessments.sql` | `assessments`: one permanent row per completed screening (the dashboard reads it) | 3 |
| `005_create_assessment_inputs.sql` | `assessment_inputs`: the exact answers behind each assessment | 4 |

Rules for writing a migration (the runner depends on them):
- Plain SQL. Every statement ends with `;`.
- Comments are whole lines that start with `--`, and the comment text must not contain `;`.
- No `;` inside a text value.
- Use `CREATE TABLE IF NOT EXISTS`, so a re-run after a failure is safe.
- Never turn off foreign-key checks to make something pass.
- Never edit a migration that has already been applied. Add a new numbered file instead.

Tables from the blueprint that are NOT here yet ( `laboratory_documents`,
`laboratory_extractions`, `assessment_shares`, `clinical_reviews`, `follow_ups`, `patient_profiles`) are added in
the phase that needs them, because their columns depend on the real model artifact and on features that do not exist yet.
