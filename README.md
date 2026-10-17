# Nephron - Phase 8: Reports

Nephron is a risk-screening and decision-support system for early chronic kidney disease
risk stratification. It does not provide a medical diagnosis.

## What you need
- Python 3.10 or newer
- MySQL Server 8 or newer, running on your computer

## Setup (do these once)
Open a terminal inside this folder.

1. Create and activate a virtual environment
   - Windows (Command Prompt):  `py -m venv venv`  then  `venv\Scripts\activate`
   - Windows (PowerShell):      `py -m venv venv`  then  `venv\Scripts\Activate.ps1`
     (if PowerShell blocks it, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` first)
   - macOS / Linux:             `python3 -m venv venv`  then  `source venv/bin/activate`
2. Install the libraries:       `pip install -r requirements.txt`
   (Run it again after every update. Phase 3 added `tzdata`, the time zone list Windows does not have.)
3. Create your settings file
   - Windows: `copy .env.example .env`      macOS / Linux: `cp .env.example .env`
   - Generate a secret key:  `python -c "import secrets; print(secrets.token_hex(32))"`
   - Open `.env`, paste the key after `SECRET_KEY=`, and set `DB_PASSWORD` to your MySQL password.
4. Create the database and its tables:   `python init_db.py`
   (Run it again after every update: it only applies the migration files it has not applied yet.)

## Run
    python app.py
Open http://127.0.0.1:5000 . Check MySQL at http://127.0.0.1:5000/health
Then create an account at http://127.0.0.1:5000/register . A General User lands on the dashboard.

## Run the automated checks
    python -m unittest discover -s tests -v
These check the pages, error handling, headers, the logo files, that the design previews are
hidden when not debugging and are accessible when shown, that charts and metrics are calculated
correctly (`tests/test_visuals.py`), and that no chart or number is ever drawn without real data.

Phase 2 added the checks for accounts and security:

| File | What it proves |
|---|---|
| `tests/test_validation.py` | What each form field accepts and refuses (email, name, password, role, professional details) |
| `tests/test_security.py` | Passwords are stored as salted hashes; the CSRF token; redirects can never leave the site |
| `tests/test_auth_flow.py` | The whole path: register, sign in and out, wrong passwords, lockout, roles, password change, no private page in the cache, friendly errors when the database is down |
| `tests/test_migrations.py` | The SQL files match the validation rules (no column is narrower than what a form allows) and the code |
| `tests/test_user_store.py` | The same checks run against an in-memory store AND against real MySQL |
| `tests/test_assessments.py` | What may be saved as an assessment; probabilities become percentages; dates are the local date, not the UTC date |
| `tests/test_assessment_store.py` | Saving and reading assessments, newest first, one person never sees another's, run on both stores |
| `tests/test_screening_contract.py` | The 31 screening questions are exactly the Stage 1 predictors (no laboratory value); every answer is checked, and a missing answer is never filled in |
| `tests/test_model_service.py` | The strict checks on the saved model: checksum, library versions, inputs, answer categories, classes, threshold; refusals; it never trains |
| `tests/test_verify_model.py` | `verify_model.py` accepts a good model, refuses a bad one, and catches a threshold that belongs to another model |
| `tests/test_screening_flow.py` | The form, the analysis, the saved result, the waiting period, the "not available" states, and that nobody sees another person's result |
| `tests/test_eligibility.py` | The one rule for "may this person screen now?": never screened, no waiting period, inside the wait, the last day, the day it opens, no model; and that the dashboard gives exactly the same answer |
| `tests/test_history.py` | Pagination, and the comparison of two assessments: which is earlier, the change in points, which answers changed (in words), nothing guessed when answers were not saved, model versions compared |
| `tests/test_history_flow.py` | The history page and the comparison through the real website: newest first, ten per page, odd page numbers, only your own records, exactly two chosen, someone else's id answered like a missing one, the waiting rule agreeing on every page |
| `tests/test_dashboard.py` | The dashboard rules: an empty account gets honest empty states, every number comes from the person's own records, no dead links, wrong role refused |
| `tests/test_egfr.py` | The CKD-EPI 2021 eGFR equation, checked against an independently-computed reference, not just against itself |
| `tests/test_lab_contract.py` | Validating a Stage 2 submission: only Serum_Creatinine is required, everything given is still range-checked, eGFR is added only when creatinine is present |
| `tests/test_lab_ocr.py` | Extracting lab values from a real synthetic report image and PDF; a value outside its range, or a field not on the report, is left out, never guessed |
| `tests/test_lab_documents.py` | Saving an uploaded file: the real file type is sniffed from its own bytes (never trusted from the claimed type or extension), size limits, no collisions |
| `tests/test_lab_document_store.py` | Saving and reading lab document rows (uploaded/extracted/confirmed/discarded), on both stores, one person never sees another's |
| `tests/test_model_service_stage2.py` | The same strict checks as Stage 1, for the Enhanced Screening model: missing optional labs are fine, Serum_Creatinine is required, eGFR is always computed, the Alcohol_Consumption vocabulary gap is translated not refused |
| `tests/test_lab_flow.py` | The whole Enhanced Screening website path: blocked without a preliminary screening, upload and OCR, confirming or correcting suggested values, the saved result, privacy between users |
| `tests/test_authorization_store.py` | Saving and reading authorization rows: request/accept/decline/revoke, re-requesting after a decline or revoke reuses the same row |
| `tests/test_authorizations.py` | Who may request whom (only a real professional account, never yourself), and describing a row for display |
| `tests/test_authorization_flow.py` | The whole sharing website path: search, request, accept/decline, viewing an authorized patient's history, either side ending it, privacy between accounts |
| `tests/test_clinical_review_store.py` | Saving and reading clinical review notes: kept oldest first, a deleted assessment removes its notes, a deleted professional's notes stay with a name snapshot |
| `tests/test_followup_store.py` | Saving and reading follow-up requests: open/fulfilled, re-requesting after fulfilment opens a new one |
| `tests/test_clinical_review_flow.py` | The whole website path for both: only an authorized professional may write a note or request a follow-up, the patient sees both, an open follow-up lets them screen again early and closes itself the moment they do |
| `tests/test_pdf_report.py` | Every PDF is valid bytes; with pypdf installed, the real text is read back and checked - the patient's own data, an included or excluded review, and that a free-text review note with `<`, `>` or `&` in it never breaks the file |
| `tests/test_report_flow.py` | The whole download path, patient and professional: single result vs whole history, the include-reviews choice, and that no one can download someone else's report |

`tests/test_user_store.py` creates a separate database called `nephron_test` (your `DB_NAME` plus `_test`), builds
it from the real migration files, and drops it again at the end. Your own data is never touched. If MySQL is not running,
or the MySQL user may not create databases, those tests are **skipped** and say why. A good run of
`python -m unittest tests.test_user_store -v` shows **no skipped tests**: that is the proof that the SQL works on your MySQL.

## Where things are
- `app.py` creates the app. `config.py` holds settings. `db.py` is the only file that talks to MySQL.
- `routes/` receives requests. `services/` holds the rules and business logic (validation, security, sign-in, the user store).
- `templates/` and `static/` are the pages, styles and scripts (see "Design system" below).
- Technical errors are written to `logs/nephron.log`. Users only ever see friendly messages.

## Design system
The look follows the approved dashboard design and the project blueprint: a soft lavender page, white rounded
cards, a curved white navigation rail, a circular logo badge, and one identity colour, lavender `#E3E2FF`.
The layout and the kidney artwork come from that design; every number and word on the screens is Nephron's own.

| Colour | Job |
|---|---|
| Lavender `#E3E2FF` | The identity colour: highlights, the active state, soft fills. **Always a fill with dark text on it, never text on white** (it is too pale) |
| Deep indigo `#302B91` | The logo mark, links, strong accents |
| Navy `#0C0D35`, `#17193F` | Headings and main text; the dark pill button |
| Violet `#7D75EE` | Graphics only: the chart line, the probability ring, dots |
| Off-white `#F6F7FC`, white | The page, and the cards on it |
| Teal / green `#0FA287` | Low Preliminary Risk, always with words |
| Red `#D64560` | High Preliminary Risk or an error, always with words |
| Amber `#C97C00` | Pending or attention |
| Gray `#8A90B2` | Secondary, unavailable or inactive |

Every text colour was measured for WCAG AA contrast on the rendered pages, including over the gradients, and every icon for 3:1.

| File | What it holds |
|---|---|
| `static/css/tokens.css` | Every colour, shadow, shape, size, space and timing, defined once. **Change values here.** |
| `static/css/base.css` | Reset, text styles, focus outline, the reduced-motion rule |
| `static/css/layout.css` | Public header/footer, the signed-in shell (header with the badge, the curved rail), the sign-in layout |
| `static/css/components.css` | Buttons (pills), forms, badges, alerts, toasts, dialogs, tables, empty and loading states, the **card family**, icon chips |
| `static/css/domain.css` | Nephron parts: hero, path card, stat cards, probability ring, donut, trend chart, sparkline, timeline, resources, the right-hand panel, ranked factors, stepper, result layout |
| `static/css/pages.css` | Styles that belong to one page (home, about, the dashboard grid, result, register, previews) |
| `static/js/main.js` | Toasts, dialogs, drawer, account menu, loading buttons, busy screen, tooltips, greeting, count-up numbers (`window.Nephron`) |
| `services/visuals.py` | **Turns assessment records into metrics and chart shapes.** No Flask, no database. |
| `services/assessments.py`, `services/assessment_store.py` | The rules for saved assessments, and the only place with the SQL for the `assessments` table |
| `services/screening_contract.py`, `ml/feature_catalog.json` | The screening questions and the rules for the answers (no Flask, no model) |
| `services/model_service.py`, `verify_model.py` | Loading and strictly checking the saved model; running it; the command that tells you whether it is accepted |
| `routes/screening_routes.py`, `templates/screening/`, `static/js/screening.js` | The guided form, the analysis and the result page |
| `templates/dashboard/_overview.html` | The dashboard markup, shared by the real page and the design preview |
| `templates/partials/_visuals.html` | `icon_chip()`, `ring()`, `donut()`, `trend_chart()`, `trend_empty()`, `sparkline()`, `mini_meter()`, `path_steps()`, `risk_pill()`, `info_tip()`, `sample_tag()` |
| `templates/partials/_sidebar.html` | The curved rail (its two curved ends are SVG paths traced from the design) |
| `templates/partials/_macros.html` | `icon()`, `logo_mark()`, `logo_lockup()`, `alert_box()`, `risk_badge()`, `risk_meter()`, `csrf_field()`, `field_error()` |
| `templates/layouts/` | `document.html` (root), `app_base.html` (header + rail), `auth_base.html` (sign-in) |
| `static/images/art/kidney-hero.png` | The kidney artwork, cut from the approved design with soft edges so it blends into the hero gradient |
| `static/images/brand/` | `nephron-logo-master.png` is your original logo, untouched. `nephron-logo.png` is the same picture with the empty space cropped away. `nephron-badge.png` (header badge), `favicon-64.png` and `apple-touch-icon.png` only place that logo on a background; nothing is recoloured or redrawn |

The overview placement: header (badge, greeting, Guide, settings, bell, account), a hero with the kidney artwork and
"Your path to better kidney health", three stat cards, the risk trend beside the latest result, the classification
summary, the assessment history, helpful resources, and a right-hand panel (profile, quick actions, recent activity).

Rules: the logo file is the two-kidney mark and has no wordmark, so where the name should be readable (public header,
footer, sign-in) `logo_lockup()` puts the word "Nephron" beside it as real text; inside the signed-in app the circular badge is used. Never stretch, recolour or redraw the logo. Risk is always shown
with words, never colour alone. Icons come from the one sprite in `_icon_sprite.html`. The model is binary, so there is
only ever "Low Preliminary Risk" or "High Preliminary Risk" (never "Moderate"). Fonts are the system fonts, so nothing is downloaded.

## The rule about data: nothing is invented
A chart or number is only drawn from real assessment records.
1. Later phases load the records from MySQL and pass them to `summarize_assessments()` in `services/visuals.py`.
2. That function returns the counts, latest result, next screening, and whether there is enough data for each
   chart (a trend needs at least two assessments; the ring, the donut and the history need at least one).
3. The templates only draw what it returns. With no records, each chart is replaced by an empty state.

The charts are plain SVG drawn from those numbers, so no chart library is needed.

## The dashboard (Phase 3)
`/dashboard` is the General User's overview, in the approved design. Every card reads a real source; nothing is made up.

| On the dashboard | Where it comes from | With no data |
|---|---|---|
| Greeting, avatar, side panel | The signed-in account | (always available) |
| Total Assessments, "this month" | Count of the person's rows in `assessments` | "0" and "No assessments yet" |
| Latest Risk, Latest Result ring, threshold | The newest row: its saved probability, its classification, and the threshold saved with it | "No result yet"; no threshold is shown if none was saved |
| Risk Probability Trend | The rows in date order (needs at least two) | "Chart appears when sufficient data exists" |
| Assessment Summary (donut) | Counts of Low / High among the rows | "No results to summarise yet" |
| Assessment History, Recent Activity | The newest rows (activity lists only completed assessments) | Empty state |
| Path (Screening, Analysis, Results, Follow-up) | How many steps the rows show as done | Starts at Screening |
| Next Assessment | The administrator's re-assessment rule (3 months by default; see "The re-assessment rule") and the last assessment | see below |

What is **not** shown, because it has no real source yet: a notification bell or count, review status, follow-up
records, any percentage without a result. Buttons for things that are not built yet (Upload Lab
Results, View Reports, Share Assessment, About CKD, Tips) appear as "Coming soon" and are not links. Each becomes a
real link in the phase that builds it. Start Assessment is a real link only while a verified model is installed;
otherwise the dashboard says "Screening is not available yet". To review the filled-in design use the preview, `/design/dashboard?data=sample`.

Two settings in `.env` (both optional):
- `REASSESSMENT_DAYS` - days that must pass between screenings. Empty means no waiting period. The team has not chosen
  a number yet, so it is empty.
- `APP_TIMEZONE` - the time zone dates are shown in (default `Asia/Manila`). Without it an assessment made at 7 in the
  morning in Manila would show the day before, because times are stored in UTC.

`services/assessments.py` has `record_assessment(store, user_id, values, inputs)`. The screening (Phase 4, below) calls it to
save the model's probability, its classification, the threshold, the model version and the answers. It refuses values that make no sense.

## History and reassessment (Phase 5)

| Page | What it does |
|---|---|
| `/history` | All of your assessments, newest first, ten to a page, with the trend chart, the state of your next screening, and "Compare with previous" on each row |
| `/history/compare?id=A&id=B` | Two of your assessments side by side: the change in points, whether the classification changed, and **which answers changed** (in words). The older one is always "Earlier" |

- **Records are permanent.** These pages only read. Nothing on them can change, add or delete an assessment (a POST is refused with 405).
- **Privacy.** Only your own rows are asked for. An id that belongs to someone else is answered exactly like an id that does not exist (404).
- **Neutral words.** "Higher" or "lower", never "better" or "worse". A different result can come from different answers, a different
  version of the model, or both, so results made by **different model versions carry a warning** that the probabilities are not directly comparable.
  Answers are only compared when both assessments saved them; nothing is guessed.
- **One eligibility rule** (`services/eligibility.py`): `unavailable` (no verified model), `waiting` (`REASSESSMENT_DAYS` has not passed since the
  newest assessment) or `available`. The dashboard, the history page and the screening page all call it, and the screening page **enforces it on
  the server**, not only by hiding a button. Days are counted in `APP_TIMEZONE`. `REASSESSMENT_DAYS` is still empty (no waiting period) until the team chooses a number.
- The selection boxes on the history page work without JavaScript too; `static/js/history.js` only limits the choice to two and enables the button.

## Laboratory upload and Enhanced Screening (Phase 6)

Enhanced Screening is an **extension** of a person's most recent preliminary screening, not a fresh questionnaire:
it reuses those 27 answers and adds laboratory values.

| Page | What it does |
|---|---|
| `/enhanced-screening` | The entry point. Needs a preliminary screening to extend, and a ready Stage 2 model, or says plainly why not |
| `/enhanced-screening/upload` (POST) | Upload a lab report (JPEG, PNG or PDF, up to 10 MB). The real file type is checked from its own bytes, then OCR (Tesseract) proposes candidate values |
| `/enhanced-screening/manual` | Skip the upload and type values in directly |
| `/enhanced-screening/confirm[/<id>]` | Review every value (grouped by panel), pre-filled and marked where OCR suggested one, before anything is analysed |

- **Nothing OCR proposes is ever saved on its own.** The person must open the confirmation page and submit it - the
  same as anything typed by hand - and `services/lab_contract.py` checks it again from scratch there. A value
  outside its plausible range is refused, not silently accepted or clamped.
- **Only `Serum_Creatinine` is required.** Every other of the 20 lab fields (`ml/lab_catalog.json`) is optional,
  matching the model's own trained tolerance for missing labs - a real lab report is rarely complete.
- **eGFR is never asked for.** `services/egfr.py` calculates it with the CKD-EPI 2021 (race-free) equation from
  serum creatinine, age and sex, every time it is needed - the same way a real lab report calculates it.
- **The Stage 2 model is a provided artifact, not trained by this project.** It was trained on a different dataset
  than Stage 1, uses a different threshold rule (sensitivity-first, not Youden's J), and its result is presented as
  a *confirmation-level estimate*, not independent evidence, with a link back to the preliminary screening it
  extends. See `ml/model_stage2/README.md` for the full reasoning, and `verify_model_stage2.py` to check it
  (mirrors `verify_model.py` for Stage 1).
- **"What raised/lowered your estimate" works here too**, from the same `services/explanations.py` used by Stage 1,
  describing whichever of the 27 reused answers or the given lab values actually moved the estimate.
- Uploaded files are stored under `UPLOAD_DIR` (default `uploads/`, outside `static/`, never reachable by guessing
  a URL) and never committed to source control.
- OCR needs Tesseract itself (a separate program, not a Python package) and, for PDF uploads, Poppler (the
  OCR Python packages are in `requirements.txt`). When Tesseract is absent (for example on a host that cannot
  install system programs), the Enhanced-Screening pages detect this and show manual lab entry instead of an
  upload that could not be read.

## Professional sharing, clinical reviews and follow-up (Phase 7)

A patient shares their own assessment history with a professional; nothing is visible until the professional
explicitly accepts. Once accepted, the professional can leave a note on any of that patient's results, and can ask
the patient to screen again - even during their normal waiting period.

| Page | Who | What it does |
|---|---|---|
| `/share` | Patient | Search for a professional by name or email, send a request, see the status of every request, revoke an accepted one |
| `/patients` | Professional | Requests waiting for an answer, and patients who have accepted |
| `/patients/<id>` | Professional | Every authorized patient's assessment, each with its own clinical review notes and a form to add one, plus a follow-up request |

**Sharing:**
- **Always patient-initiated.** There is no professional-initiated request in this version.
- **One row per (patient, professional) pair**, not one row per event (`database/migrations/007_create_authorizations.sql`):
  the relationship has a current status (`pending` / `accepted` / `declined` / `revoked`) that changes over time.
  Requesting again after a decline or a revoke reuses the same row rather than creating a new one.
- **Either side can end an accepted authorization** - the patient from `/share`, or the professional from `/patients`.
- **Searching is by exact email or by partial, case-insensitive name** (`services/user_store.py:search_professionals`),
  and only ever returns `role = 'professional'` accounts.
- Every route re-checks `authorizations.is_authorized()` itself before showing anything - a page having been
  reachable once before is never trusted, and an unauthorized or non-existent patient answers with the same 404.
- `/patients/<id>` does not currently link into the detailed result pages with "What raised/lowered your estimate",
  which are scoped to the signed-in patient viewing their own result. Extending that to an authorized professional
  is a later piece of work.

**Clinical reviews** (`database/migrations/008_create_clinical_reviews.sql`, `services/clinical_reviews.py`):
- A note is attached to ONE specific assessment, written by a professional CURRENTLY authorized for its owner
  (checked fresh every time, never trusted from an earlier visit).
- **Append-only**, like assessments themselves: there is no edit or delete, only new notes - a running conversation,
  oldest first. The patient sees every note on their own result page ("Notes from your professional"), and it stays
  there even if access is later revoked (the professional's name and title are snapshotted at write time).

**Follow-up requests** (`database/migrations/009_create_follow_up_requests.sql`, `services/followups.py`):
- A professional asks their patient to screen again, with an optional message. This is the only way anything
  overrides `REASSESSMENT_DAYS`'s normal waiting period - `services/eligibility.py`'s `follow_up_open` parameter -
  and only for that one patient, only until they actually screen again (either stage marks it fulfilled
  automatically - `services/followups.py:mark_fulfilled_by_new_assessment`, called from both
  `routes/screening_routes.py` and `routes/lab_routes.py` right after a new assessment is saved).
- An open request shows as a banner on the patient's dashboard, and completes the fourth step ("Follow-up") of
  "Your path to better kidney health".

## Reports (Phase 8)

A real, downloadable PDF - not a printable web page - of one result or a whole history, with an explicit choice of
whether to include clinical review notes. Needs `reportlab` (in `requirements.txt`); nothing to install on the
system itself, unlike Tesseract for Phase 6.

| Page | Who | What it does |
|---|---|---|
| `/reports` | Patient | Choose one result or the whole history, choose whether to include professional notes, download |
| A form on `/patients/<id>` | Professional | The same choice, for one authorized patient |
| A button on the result page | Patient | A one-click download of that one result, with notes included |

- **`services/reports.py`** gathers the data (reusing the exact same "only explain a result the running model
  actually produced" rule the result page itself uses - `services/explanations.py`); **`services/pdf_report.py`**
  only lays it out. Colors match `static/css/tokens.css` on purpose.
- **Every piece of dynamic text is escaped before it reaches reportlab's Paragraph markup** (`pdf_report._escape`).
  This is not just tidiness: a clinical review note is free text a professional typed - the one place in a report
  that is not a controlled vocabulary - and an unescaped `<`, `>` or `&` in it would break the PDF, not just look
  wrong. The same function also fixes eGFR's `mL/min/1.73m²` unit, which the standard PDF fonts have no glyph for
  at all (it renders as a real superscript instead of a silent gap).
- **The choice is made every time**, never a standing preference: the checkbox on the download form is what decides
  whether a given PDF includes review notes, nothing else.
- A patient can only ever download their own data; a professional, only an authorized patient's - the same checks
  `routes/authorization_routes.py` already uses, asked again here.

## PhilHealth Accredited Centers

A real directory of PhilHealth-accredited dialysis/kidney-care facilities, replacing the earlier "About CKD"
placeholder in Resources.

- **`scripts/build_philhealth_centers.py`** turns the PhilHealth-provided source spreadsheet into
  `data/philhealth_centers.json` - reference data, loaded once and cached (`services/philhealth_centers.py`),
  same pattern as `ml/feature_catalog.json`. Re-run it whenever PhilHealth provides an updated list.
- **Nothing is invented.** Every facility, address, phone number and accreditation detail comes directly from the
  source file, including its own inconsistencies (a phone number written with or without a leading 0 is shown
  exactly as given, never "corrected" by a guess).
- **`/philhealth-centers`** works with no JavaScript at all (a plain GET, server-rendered results), then
  `static/js/facility_search.js` upgrades the same search box into a live, debounced search against
  `/philhealth-centers/search` - search by name/city/municipality, filter by region or sector, with proper
  loading, empty, no-results and error states.

## Kidney health in the Philippines (dashboard education)

A full-width row on the dashboard: compact, sourced figures about CKD **in the Philippines** - never a claim about
the person's own data. The earlier figures about US adults were removed (panel review: Nephron's users are in
the Philippines).

- **`services/ckd_facts.py`** holds six facts, each with the source it was read from: about 7 million Filipinos
  estimated to have CKD (2021) and only as few as 1 in 10 diagnosed (Philippine Society of Nephrology, via the
  Philippine News Agency, June 2023); one Filipino developing chronic kidney failure every hour (NKTI, via ABS-CBN,
  June 2025); CKD as the 4th most common cause of death in the Philippines in 2019 (IHME data, via PNA); men
  progressing to kidney failure more often (research, written to avoid a single-cause claim - a test guards it);
  and the gradual decline of kidney function after about 40.
- A ring is used only for a true share ("1 in 10"); other figures ("7 million", "Every hour") are big-number cards.
- **A reusable source-citation control** (`source_note()` in `templates/partials/_visuals.html`) - the small "i"
  button on every card - reuses the same popover as a lab field's (?) button (`static/js/main.js`).

## Notifications

A real bell in the header - unread badge, dropdown preview, and a dedicated `/notifications` page to mark
read/unread or delete - built from four real events, never invented ones.

- **`services/notification_store.py`** + **`services/notifications.py`**: one row per notification, always
  scoped to the person it is for (a save-time and a read-time check, matching every other per-person store here).
- **Exactly four real events create one**, each right where `routes/authorization_routes.py` already saves that
  event: a patient requests to share (professional is notified), a professional accepts or declines (patient is
  notified), a professional requests a follow-up (patient is notified), a professional adds a clinical review
  note (patient is notified). Nothing else creates a notification.
- The header bell (`templates/layouts/app_base.html`) shows an unread count and a short preview (reusing the
  account menu's own click/outside-click/Escape pattern in `static/js/main.js`); `/notifications` is the full
  list, reached from the dropdown's "View all" link.
- A notification is a permanent record of what happened - it is not deleted or hidden just because the thing it
  refers to (a follow-up request, say) was later fulfilled; only the person it belongs to can mark or delete it.

## Personalized kidney health tips

A right-hand panel on the result page: kidney-health tips matched to that ONE result's own saved answers - never
generic-only, never a new question asked of the person.

- **`services/kidney_tips.py`** holds ~20 rule-based tips across six categories (Diet, Hydration, Physical
  Activity, Lifestyle, Medication, Follow-up), each tied to a real KDIGO or clinical guideline source. A tip's
  condition reads directly from the SAME saved `inputs` dict already used to explain and re-check the result, so
  a lab-only rule (potassium, eGFR, phosphorus) simply never matches a Preliminary-only assessment - no
  special-casing needed. Enhanced Screening's own already-computed eGFR (`services/egfr.py`, CKD-EPI 2021) is
  reused directly, never recalculated a second time.
- **Never invented, never a prescription**: every tip is phrased as general, conditional education ("ask your
  doctor before...") - none ever tells a person to start, stop, or change a medication dose, and hydration is
  deliberately never given a single universal number (tests guard both of these).
- Shown on the result page's own right column (`.result-tips`), sticky, with its own internal scroll if there
  are many tips - the page itself never grows long just because of the tips list.

## Follow-up calendar and checklist

The Follow-up screen is deliberately not another dashboard: a real month calendar is its own primary content,
built from appointments a professional actually scheduled - full add/edit/cancel/complete/delete, all
re-authorized on every write.

- **`follow_up_appointments`** (migration 013) is its own table, separate from the earlier `follow_up_requests`
  (migration 009, "please screen again soon" - no date or time of its own): a genuine scheduled visit with a
  date, time, purpose, optional notes, and a status (scheduled/completed/cancelled).
- **`services/followup_appointments.py`** re-checks the professional is CURRENTLY authorized for that patient on
  every single write (schedule, reschedule, complete, cancel, delete) - a past authorization that has since been
  revoked is never enough, matching how `services/clinical_reviews.py` already works.
- The professional's own view (`templates/authorizations/patient_history.html`) schedules new appointments and
  lists existing ones with inline edit (a `<details>` disclosure, pre-filled), complete, cancel, and delete -
  each its own real form, each re-checked server-side.
- The patient's own `/follow-up` page (`templates/followup/index.html`) is read-only for appointments (a
  professional's own action) but shows a genuine month-grid calendar with month navigation, plus an agenda list
  of every appointment for anyone who prefers a plain list to a grid.
- **The checklist** (`checklist_completions`, migration 013; `services/checklist.py`) turns the SAME personalized
  tips already shown on the result page into checkable items - only the checked/unchecked state persists,
  keyed by each tip's own stable id, so improving a tip's wording later never loses anyone's progress.

## Feedback and consent

Every consequential action asks first, every result of an action is acknowledged, and sharing health information
needs a real yes.

- **Sharing needs an active, recorded yes.** A patient's share request opens a consent dialog (what will be shared,
  who receives it, why, and their control) with a checkbox that must be ticked before "Agree and send request"
  works. That is not just on the page: `routes/authorization_routes.py` refuses a request without `consent=1`
  (`services/consents.py`), so a request can never be made by skipping the dialog. Each agreement is written to
  `consent_records` (migration 014) with the wording version it was given under (`CURRENT_VERSION` - change it
  whenever `templates/authorizations/_consent_template.html` changes in what it promises), and the Share page shows
  "You agreed to share on ...". Without JavaScript the same form carries a plain checkbox instead.
- **One dialog for every "are you sure".** `partials/_confirm_dialog.html` + `static/js/main.js` (section 12) are
  filled from `data-confirm-*` attributes on the form that asked (`consent`, `danger`, or default), so live-search
  results added after page load work too. Destructive ones focus the safe button first and colour the confirm
  button red: ending access (both sides), discarding a screening draft, cancelling or deleting an appointment. A
  professional accepting a request acknowledges confidentiality first - that acknowledgement is on the page only,
  not recorded or enforced by the server (only the patient's consent is).
- **Toasts for good news, banners for what must be read.** Every `success` flash is a toast (slides in, progress bar,
  holds still under the pointer, leaves by itself; pure CSS fades it out if JavaScript never loads). Errors,
  warnings and notices stay banners until dismissed, so they can never vanish before being read.
  `Nephron.toast()` uses the same look for anything raised from JavaScript. Finishing a Preliminary or Enhanced
  Screening now says so.

## Home and How it works: the animation system

A public home page and a scroll-driven "How it works" walkthrough, built on a small, project-wide animation
system rather than one-off page effects.

- **`static/css/motion.css` + `static/js/motion.js`** are the rules: only `opacity`/`transform` animate, one easing
  token, and - the one that matters most - every "before" (hidden, unfilled, undrawn) state is gated behind BOTH
  `html.js` (a class an external script in `<head>` sets before the first paint - never an inline `<script>`, which
  the project's own CSP-style tests forbid) AND `@media (prefers-reduced-motion: no-preference)`. No JavaScript, or
  a request for less motion, always shows the finished page - never a blank one. `[data-animate]` reveals an
  element once scrolled into view; `[data-stagger]` numbers its children for a cascade; a ring or a bar fills once
  seen.
- **The home page** (`templates/main/home.html`, `static/css/home.css`) keeps the same sections and wording as
  before, with a five-step "How screening works" strip (each step with its own small animated picture) and a
  closing call to action. Every picture is a labelled **illustration** with no invented number - a public page
  animating a count-up toward a specific percentage would itself be an invented figure, so there are none.
- **How it works** (`templates/main/about.html`) adds a scroll-driven walkthrough: on wide screens a picture stays
  in a sticky stage and changes as each of the five steps scrolls past (`static/js/motion.js`'s `[data-walk]`,
  tracking whichever step is nearest the middle of the viewport); on phones, and with no JavaScript, the sticky
  stage is replaced by the same picture sitting above its own step - one `role`-appropriate markup, two CSS-only
  presentations. Every reviewed sentence about the five steps is unchanged.
- **`tests/test_home_pages.py`** guards the properties that matter most: the pages are complete without motion or
  scripting, no illustration states an invented number, and no CSS rule can hide content unless both the
  scripting flag and the motion preference allow it (checked by parsing the stylesheets themselves, not just by
  loading a page).

## A professional's own patients

A professional can manage patients directly - a walk-in, or anyone without their own Nephron account - separate
from Shared Assessments (where a General User shares their own history instead).

- **Each patient record wraps its own shadow account** in the existing `users` table (migration 015), rather than
  a parallel "who does this assessment belong to" column: every table already built around `assessments.user_id`
  (assessment_inputs, clinical_reviews, follow_up_appointments, checklist_completions, reports) keeps working for
  a patient record with no change. The shadow account can never sign in as anybody - `is_patient_record` is
  checked twice, independently: `routes/auth_hooks.py` refuses the session outright (treated exactly like one
  that does not exist), and `services/auth_service.py` refuses it again at the password check.
- **The patient ID** ("NPH-0001", "NPH-0002"...) is assigned from the record's own database id once it is
  created - never typed in, never guessed at.
- **Creating a patient continues straight into an assessment** (`services/patient_records.py`,
  `routes/patient_records_routes.py`): choose Preliminary Screening (Enhanced/Laboratory for a patient record is
  not built yet, and says so rather than offering a form that leads nowhere), then the SAME question-by-question
  form, validation, and model scoring used everywhere else - reused via a small shared partial
  (`templates/screening/_question_macro.html`) rather than copied, so both forms can never quietly drift apart.
  Importing a macro from a template that itself extends a layout can misfire (Jinja evaluates that template's own
  block content as a side effect); giving the question renderer its own extends-free file avoids that entirely.
- **The Risk Analysis page** a professional sees for one of their patient's assessments reuses the SAME
  explanation partial the patient's own result page uses (`templates/screening/_explanation.html`) - the same
  ring, classification, and factor cards mean the same thing in both places.
- Ownership is checked on every route (`_owned_or_404`): a patient code that exists but belongs to a different
  professional is answered exactly like one that does not exist at all.

## The Professional Dashboard

The first page a professional sees after signing in - six stats, a risk distribution, recent activity across
every patient, and a follow-up/review overview, all worked out fresh by `services/professional_overview.py`
rather than stored anywhere.

- **Two kinds of patient, one dashboard.** A professional's own patient records and their accepted shared
  patients are combined into one pool for every count and every row of the activity table - but "review status"
  only ever applies to a shared patient's own assessment (they performed it themselves, so it genuinely needs the
  professional's clinical review); a patient record's own assessment - which the professional performed
  themselves - is labelled "Self-recorded" and never counted as pending.
- **Nothing here is invented.** An empty dashboard says "No patients yet" plainly, with a way to add one, rather
  than showing zeroed-out stat cards.
- **A genuine CSS bug worth naming**: a plain `1fr` grid track, placed inside an ancestor with
  `container-type: inline-size` (the pattern this project's own patient dashboard already used), sized itself
  off its own content's intrinsic width instead of the real available width, on a narrow screen - a real
  rendering quirk, reproduced and confirmed by inspecting computed styles directly rather than guessed at. The
  Professional Dashboard's stat row and two-column overview are laid out with plain media queries instead, side-
  stepping the container-query context entirely.

## Search

A professional can search their own patients and assessments - by patient name, patient code, or a numeric
assessment id - from `/search` (`services/professional_overview.py` search(), reusing the same patient pool the
dashboard uses).

- A name or code matches a patient; a plain number also tries a direct assessment-id lookup
  (`assessment_store.find_owner()` first checks who an id belongs to, so an id from someone else's patient is
  refused before anything about it is read - the same "answered like it does not exist" pattern used everywhere
  else in this project).
- Matching a patient by name also lists every one of their assessments, not just their profile.
- Each assessment links straight to the right page for its own kind of patient: a patient record's own Risk
  Analysis page, or a shared patient's history page - there still is not one shared result page for both kinds.

## Patient Management: filters and categories

`/patient-records` shows every patient a professional works with - their own patient records and their shared
patients together (`services/professional_overview.py` patient_list()) - narrowed by a name/code search, a risk
filter, and four category tabs.

- **The categories mean the same thing "pending"/"reviewed" mean everywhere else in this project**: a patient
  record with no assessment yet, or a shared patient whose latest assessment is still awaiting review, is
  Pending; anything else with at least one assessment is Reviewed. A patient record's own assessment - which the
  professional performed themselves - can never be "awaiting review" to begin with, so it moves straight to
  Reviewed the moment it exists.
- **Follow-Up** matches a patient with at least one currently scheduled follow-up appointment - today, that
  only exists for shared patients (follow-up scheduling for a patient record is not built yet).
- Every tab's own count is worked out from the SAME filtered set the search box and risk dropdown already
  narrowed to, so a tab's number always matches what choosing it would actually show.
- "Reset" is a plain link back to the unfiltered page, not a client-side clear - it always works, with or
  without JavaScript.

## New Assessment: existing or new patient

`/assessments/new` is the explicit starting point sections 12-14 describe: choose Existing Patient (search your
own patient records, see each match's basic info - name, ID, age, sex, last assessment - before choosing) or
New Patient (the registration form already built). Both choices lead to the same assessment-type page.

- Scoped to patient records only, on purpose: a shared patient already has their own Nephron account and
  screens themselves - there is no "assess them on their behalf" action for that kind of patient.
- The "New assessment" buttons on the Patients page and the dashboard's empty state now point here first,
  rather than straight to patient registration - the existing-patient path was previously only reachable from a
  patient's own profile page.

## The Assessments section

`/assessments` lists every assessment across every patient a professional works with, separate from the
Patients page - filterable by time period (Last 1 Day / 7 Days / 30 Days / All Records), a search term (patient
name, patient code, or an exact assessment id), and risk. Built on the same `assessment_list()` aggregation as
the dashboard and Patients page (`services/professional_overview.py`), so "review status" follows the identical
rule everywhere: a patient record's own assessment is "Self-recorded"; only a shared patient's own assessment is
ever "Awaiting review" or "Reviewed".

## Shared Assessments: filters

`/patients` (Shared assessments) now also lists every assessment from a professional's ACCEPTED shared patients
- never a patient record, which has no "review" of this kind to begin with - filterable by a calendar date
period (Today / This week / This month / All dates, not a rolling window: "this week" means the current
Monday-Sunday week, matching how a professional would actually ask "what came in this week"), a search term
(patient name or an exact assessment id), risk, and review status.

## The Follow-Up section

`/follow-up-cases` lists every follow-up appointment a professional has scheduled, across every patient -
separate from `/follow-up`, which is a PATIENT's own calendar page. Status tabs (All / Pending / Due /
Completed / Cancelled), a name/patient-code search, and a follow-up-date period filter (Today / This week / This
month / All dates, the appointment's own scheduled date, not when it was created).

- **Pending vs Due** is worked out fresh, not stored: a scheduled appointment is Due once its own date has
  arrived and it has not been marked complete, Pending while that date is still ahead - so this never drifts out
  of sync with the clock the way a stored flag could.
- Editing, cancelling, and completing an appointment still happens from the patient's own history page
  (`templates/authorizations/patient_history.html`) - this section is a searchable overview, with "View" going
  straight there.
- The sidebar's Follow-up item, "Coming soon" until now, points here.

## The Reports section

`/patient-reports` treats each assessment across every patient a professional works with as a downloadable
report - stats (Total / High-Risk / Pending / Reviewed Reports), and the same search and risk/status filters as
the Assessments section, reusing the same `assessment_list()` aggregation. "Reviewed" counts a patient record's
own self-recorded assessment too (there is nothing pending about it) - the same rule as everywhere else.

- **A genuine bug caught while adding this**: a large edit to `routes/report_routes.py` accidentally deleted the
  `@reports_bp.route(...)` decorator in front of the existing shared-patient download route, silently
  un-registering it - the file still parsed fine (a bare function is valid Python), and it only surfaced by
  actually loading the app and listing its routes. Fixed and re-verified.
- **New**: patient records - which had no report download route at all - now have one
  (`/patient-records/<code>/reports/download`), reusing the exact same PDF builder; the header shows the
  patient's ID in place of an email, since a patient record's own account has no real one to show.

## Manage Connection

`/patients/<id>/connection` is a focused page for the relationship between a professional and one shared patient
- when it was requested and accepted, and the one control that manages it: ending access, with the same
confirmation dialog used everywhere else a connection can be ended. Linked from the patient's own history page.
Scoped to shared/authorized patients only - a patient record has no such relationship to manage: it is owned
directly, not granted.

## The Professional Dashboard now matches the patient dashboard's own look

Rebuilt on the exact same visual structure as `templates/dashboard/_overview.html` (the patient dashboard),
rather than its own separate layout: the same hero card (the same kidney artwork, a floating glance-card in the
same spot the patient dashboard's step tracker sits), the same `.stat-card` row, the same two-column
`.dash-row` (main content + a matching card alongside it), and the same right-hand `.dash-aside` panel - profile
card, a quote card, Quick Actions, and a Recent Activity list - all reusing the SAME CSS classes and macros, not
a parallel set that happens to look similar.

- The hero's "This week at a glance" card takes the same visual slot as the patient dashboard's step tracker,
  with professional-relevant content instead (patient count, pending reviews, follow-ups due) - not the
  `path_steps()` macro itself, since a professional's week is not a sequence to complete in order.
- The six stats keep their own two rows of three (`repeat(3, minmax(0,1fr))` twice), matching the identical
  `.stat-card` markup and sizing the patient dashboard's own three use.
- Recent Activity appears TWICE, on purpose, at two different levels of detail: a compact 3-column table (main
  column, alongside the risk donut) and a shorter list in the aside (same `.activity-list` markup and icons the
  patient dashboard's own Recent Activity uses) - both link out to `/assessments` for the full list.

## Patient Insights: the same visualizations as the patient dashboard's "Kidney health, by the numbers" - about your own patients this time

A third dashboard column, in the exact spot `templates/dashboard/_overview.html` puts its population CKD facts
(`.dash-ckd`, between the main column and the profile/quick-actions panel) - reusing the SAME ring macros
(`fact_ring_card`, `fact_mini_rings`, `fact_sex_differences`) with real, live data about the professional's own
patients instead of a cited statistic:

- **Who is at risk** - a single ring, the percentage of the professional's own patients (with at least one
  result) currently classified High Preliminary Risk.
- **High risk, by sex** - how many of their male and female patients there are, and what percentage of each is
  High Preliminary Risk by their latest result.
- **Your patients, by age** - three mini rings, the same 18-44 / 45-64 / 65+ groups the population facts use,
  showing what share of the professional's own patients fall in each.

Every card's own "source" line reads "Your own patient records, not a general population statistic" rather than
a citation - the same `source_note()` button the population facts use, repurposed honestly rather than left
implying a citation that does not exist for live data.

- **With fewer than three patients with a result, the whole section is left out** rather than showing a
  misleading distribution from too little data - the same honesty standard used throughout this project.
- **Age and sex for a patient record** come directly from the record itself (entered when the professional
  registered them); for a shared patient, from the Age/Sex answers saved with their own most recent
  assessment - a General User's account carries no separate profile field for either.
- A genuine bug caught while building this: the sex-comparison text used the HTML entity `&middot;` inside a
  Python f-string passed to a template variable - Jinja auto-escapes that context, so the entity showed up
  literally on the page instead of rendering as a dot. Fixed by using the real Unicode character instead of an
  HTML entity, which needs no escaping to render correctly.

## Visual consistency pass (both roles)

- **Screening form:** every question in one column with one spacing scale; yes/no questions (Health history,
  Medicines) are checklist rows - question left, Yes/No right, equal-width buttons. The old two-column grid's
  `:first-of-type` rules also counted the card header (a div), so the right column always started one border
  lower. The Review step is grouped by step, each group with its own Edit button.
- **Lab confirm:** spacing between group cards; every box in a row lines up (labels are a fixed two-line,
  bottom-aligned row, so a long label no longer pushes only its own box down).
- **Sidebar:** the outline now runs down the straight edge too (it was drawn only on the two curved caps); every
  item highlights its own page (the lab pages and the professional Follow-up set the wrong key); Professional
  review is a real page for both roles (`/reviews`, `/review-queue`); Resources is now PhilHealth Centers.
- **Risk badges:** an Enhanced result was labelled "Preliminary" in many lists - every badge now passes the
  assessment type by keyword (one existing page passed it positionally into the `large` parameter).
- **One vertical rhythm** between every top-level section of a page (`.app-main > :where(...) + :where(...)`).
- **How it works:** the step icons sit in front of the line (the line was painted after them, and the whole
  inactive step was dimmed, which made each white circle see-through).
- **Professional:** the dashboard's Risk overview keeps its own height; Shared assessments' row buttons sit
  together on the right; live filtering on every search/filter form (`form[data-live-filter]` in main.js fetches
  the same page and swaps just the results, so it needs no extra endpoint and still works without JavaScript);
  a month calendar on Follow-up (`services/followup_calendar.py` and `templates/followup/_calendar.html`, shared
  with the patient's own Follow-up page); and an Enhanced / Laboratory assessment for a patient record
  (`/patient-records/<code>/enhanced` - the same lab form, validation, Stage 2 model and eGFR as a General User's
  own Enhanced Screening, built on the patient's latest Preliminary Screening).

## Card-content pass (General User)

- **Enhanced results were labelled "Preliminary"** on the dashboard (Latest Risk, Latest Result pill, Recent
  Activity), in chart tooltips, and on the compare page: `risk_pill()` and several `level_label()` calls assumed
  preliminary. Each now passes the record's own type; activity items and chart points carry it.
- **The classification donut** counts Preliminary and Enhanced results together, so its title ("Your results")
  and its sentence ("Most of your results are in the lower-risk group") no longer name one type for both.
- **History trend chart** is drawn at the size it is shown (`trend_geometry(..., width=620, height=250)`): an SVG
  scales its text with it, and the 340-wide drawing shown 650 wide had axis text twice the page's size.
- **Every `<fieldset>`** starts plain (`base.css`) - Reports showed the browser's grey box and inset legend.
- **Settings** read "30.0 minutes": in Jinja `x // 60 | int` applies `int` to the 60 only.
- **Result page** highlights Laboratory for an Enhanced result and Preliminary screening for a preliminary one.

## Fixed answers, realistic ranges, Philippines, professional drafts and OCR, SweetAlert2

- **Realistic ranges, not training ranges** (`ml/feature_catalog.json` `valid_min`/`valid_max`): an answer outside
  what the model was TRAINED on (e.g. age 16, 13 hours of sleep) is accepted and flagged on the result
  (`screening_contract.outside_training()`), so the model can be checked on people it never saw; only an
  unrealistic answer is refused. **Philippines** is offered and saved as itself but given to both models as
  "Other" (an option's `model_value`), and the result says so.
- **Fixed answers** (`services/fixed_answers.py`, migration 016): Age comes from the date of birth (it changes only
  on a birthday), Country from the account (asked at registration), and Sex/Ethnicity/Country are kept from the
  first preliminary screening. They are shown locked and **enforced by the server** (`fixed_answers.apply()`
  replaces whatever the page sent). A patient record gets the same: the New patient form asks for a birthday
  and country instead of an age.
- **Professional drafts:** a professional's half-finished screening for a patient autosaves under the patient
  record's own account and resumes after a refresh, a Back or a closed tab.
- **Professional OCR:** the Enhanced / Laboratory assessment of a patient record accepts a lab report upload, read
  by the same Tesseract pipeline as a General User's own upload; values only pre-fill the form for checking.
- **SweetAlert2:** download https://cdn.jsdelivr.net/npm/sweetalert2@11/dist/sweetalert2.all.min.js into
  `static/vendor/sweetalert2/` (see the README there). When present, every confirmation (consent with its
  tick-box, dangerous actions starting on the safe button), every toast, and every after-the-fact error uses it;
  without it, the built-in dialog and toasts are used, so nothing depends on the file.
- **Calendars** mark today clearly; **dashboards** keep the side panel at its own height (no tall empty block when
  the main column grows) and give side-by-side cards one height with their content centred.

## Lab report checks (migration 018)

When a lab report is uploaded (by a General User, or by a professional for a patient record), the text Tesseract
reads is checked for signs that the report is genuine and about the right person (`services/lab_verification.py`):
the name on it (against the account's or patient record's name), its date (recent, older than six months, or in
the future), a signature or attestation (pathologist, medical technologist, licence/PRC number, "verified by"),
and a laboratory or hospital name. The results are shown as "Report checks" beside the values - **signs, never
proof**: a photo cannot prove a report is real, so nothing is blocked or changed by them. Before an uploaded
report is analysed, the person must confirm it is theirs (or their patient's) and that the values match it; the
server enforces that confirmation.

SweetAlert2: the app logs at startup whether `static/vendor/sweetalert2/sweetalert2.all.min.js` was found, and the
browser console says whether it loaded - the quickest way to tell why pop-ups look built-in rather than SweetAlert2.

## Database older than the code, and level dashboard columns

- **Pending migrations:** at startup the app compares `database/migrations` with the `schema_migrations` table that
  `init_db.py` keeps. If any migration has not been applied, it logs exactly which ones and every page shows
  "The database needs updating - run `python init_db.py`" (a 503 naming the fix) instead of failing later with a
  bare "Error 500" when new code reads a column the database does not have yet (`db.pending_migrations()`).
- **Dashboards (both roles):** two columns that end level - the main column and one right-hand panel (profile,
  quick actions, recent activity) - with the "by the numbers" facts as a full-width row of side-by-side cards
  underneath. Whichever column is shorter lets its last card grow to meet the other.
- **Sidebar:** the edge glow is one strength all the way down (the top curve, straight edge and bottom curve were
  three different strengths before).

## The administrator side (migration 019)

**Creating an administrator.** Never through the public registration page - only someone with access to the server:

    python create_admin.py admin@example.com "Admin Name"      # asks for a password
    python create_admin.py existing@example.com --promote      # makes an existing account an administrator

An administrator is stored with `users.is_admin = 1` (the `role` ENUM is never MODIFIED - migrations only ADD), and
`auth_service.describe()` reads that account as role `"admin"`, so `@role_required("admin")` guards every page.

**What an administrator can do** (`routes/admin_routes.py`, `/admin`):
- **Overview** - account counts by role, professionals awaiting verification, system-wide assessment COUNTS, and
  whether each model is ready (a short plain status, with the technical reason folded away).
- **Accounts** - search and filter every real person's account (never a patient record's shadow account), and
  switch an account off or on again. Switching off deletes nothing; the person cannot sign in, and an open session
  ends at once. A deactivated account is only revealed at sign-in once the password is right, so it is never
  disclosed to someone guessing. An administrator cannot switch off their own account.
- **Professional verification** - compare each stated licence with the PRC's own records (outside Nephron), then
  mark it verified or not verified. Patients see the result as a badge when they search for a professional to
  share with, and a switched-off professional cannot be found there at all.

**KPIs** (overview): people using Nephron (all accounts except administrators), how many signed in during the last
30 days and joined this month, people screened, and how many are higher risk - each person counted ONCE, by their
most recent result - broken down by age group (Under 18, 18-44, 45-64, 65+). `assessment_store.latest_per_person()`
returns only (classification, age) pairs - no id, no name, no other answer.

**Activity log** (`/admin/activity`, migration 020 `activity_log`): sign-ins, failed sign-ins, sign-outs, new
accounts, password changes, and every administrator action, with who did it and to whom. Never health
information. Writing to it can never break the action it records (`services/activity.py`).

**Password reset** (`/admin/users/<id>/reset-password`): a random temporary password, shown to the administrator
once (never stored readable, never in a URL, a flash message, the log, or the browser cache). Every session of that
account ends, and at the next sign-in the person must choose their own password before any other page opens
(`users.must_change_password`, `routes/auth_hooks.py`).

**Model performance** (`/admin/model`): for each model - measured accuracy, sensitivity (recall), specificity,
precision, F1, ROC-AUC with its curve, PR-AUC, Brier score and the confusion matrix at the model's own threshold;
feature importance (how much each input weighs in the model overall, read from the loaded model); and its model
card (version, threshold and how it was chosen, training data, libraries, startup checks, and any warning from the
model's author). The figures are computed from real predictions on labelled data and saved next to the model:

    python model_report.py --stage 1 --csv path/to/test_set.csv --target CKD
    python model_report.py --stage 2 --csv path/to/test_set.csv --target CKD

Use held-out rows the model was not trained on. Until a model has been measured, its page says so and shows the
command - no figure is ever estimated or typed in (`services/model_insights.py`).

**What an administrator never sees:** anyone's screening answers, probabilities or results. Every admin page is
built from accounts and totals only (`services/admin_overview.py`, `assessment_store.totals()`), and a test checks
that no admin page contains a result link or a probability.

Every change is a POST with a CSRF token, confirmed in the page first, and logged with the administrator's id.

## The preliminary screening (Phase 4)
`/screening` is a guided form (About you, Health history, Medicines, Lifestyle, Review). It asks the 31 inputs of the
preliminary screening, which uses **no laboratory value** and no Frailty_Index. Height and weight are asked and the BMI is
worked out; Obesity is worked out from the BMI (30 or more), because that is how the dataset defines it. Every question
comes from `ml/feature_catalog.json`, so the form, the checks on the server and the model can never disagree.
After the last step the answers are checked again on the server, the model is asked once, and the result and the answers are
saved together as a new permanent row. The person lands on `/results/<id>` (a redirect, so Refresh cannot save it twice).

| The result page shows | Where it comes from |
|---|---|
| Predicted Risk Probability (the ring) | The model's probability of the high-risk class, saved with the assessment |
| Risk Classification (High or Low Preliminary Risk) | The saved classification, decided with the model's own validated threshold |
| The threshold | The one saved with THIS assessment (never a number written in the program) |
| Two cards: "What raised your estimate" and "What lowered your estimate" | For THIS person: how much each of their own answers raised or lowered the estimate compared with an average person in the training data (XGBoost's built-in TreeSHAP), worked out again from the saved answers. Up to five per card, one shared scale for the bars, a short explanation in each card. Shown only if the same model made the result and the contributions add up to the saved probability |
| Compared with previous | The person's previous assessment, in points, without judging it |
| Your answers | The snapshot saved with the assessment |

**A result is never invented.** The saved pipeline fills gaps by itself: a missing answer becomes the most common value and an
unknown category is quietly treated as the first one. So before the model may be used, `services/model_service.py` proves
that the file is the one recorded (SHA-256) and was saved with the library versions installed here; that its inputs are
exactly the screening questions (names and order); that every answer the form can send is one the model was trained on;
that its classes and threshold are sound; that it really runs; and that every input maps to its feature importance.
If any check fails the app keeps running, screening says it is unavailable, nothing is analysed or saved, and the reason is
written to `logs/nephron.log`. The program contains no code that trains or saves a model.

**There is no model in this project.** You make one by running `ml/notebooks/CKD_Stage1_Modeling.ipynb` (it trains on
`CKD_400k.csv`, writes the model file and its metadata, and computes the threshold from the very model being saved), as described in `ml/README.md`. Then run `python verify_model.py`: it runs the same checks and says plainly whether
Nephron will accept the model, and if not, why. Until a model passes, the dashboard says "Screening is not available yet".
The tests use a small stand-in model built in a temporary folder; it is not Nephron's model and never leaves the tests.

## Accounts and security (Phase 2)
| Page | Who | What it does |
|---|---|---|
| `/register` | anyone | Create a General User or Healthcare Professional account, then sign in automatically |
| `/login`, `/logout` | anyone / signed in | Sign in (with a safe "return to where you were") and sign out (a button, never a link) |
| `/dashboard` | General User only | The first page after signing in (an honest empty state until assessments exist) |
| `/professional` | Healthcare Professional only | The professional's first page |
| `/account` | any signed-in person | Their details, change password, sign out |

How it is protected, in plain words:
- **Passwords** are never stored. Only a salted, deliberately slow hash is (scrypt). At least 10 characters, no list of
  well-known passwords, and it may not contain the email address. Length is asked for instead of tricky symbols.
- **Sign in** says the same thing for a wrong password and for an email with no account, and takes the same time, so
  nobody can find out who is registered. After 5 wrong passwords for one email the address is paused for 15 minutes
  (`LOGIN_MAX_FAILURES` and `LOGIN_LOCK_MINUTES` in `config.py`). Guessing the current password on the account page counts too.
- **Sessions**: the cookie holds only the user number, is signed with `SECRET_KEY`, cannot be read by scripts, and ends after
  30 minutes without activity. The person's role is read from the database on every request. Changing a password
  signs out every other device. A fresh session is made at sign-in.
- **Forms** (every POST) carry a secret token (CSRF), so another website cannot make a signed-in browser act.
  Signing out is a POST for the same reason.
- **Roles**: `login_required` and `role_required("general")` / `role_required("professional")` sit above each protected
  route (`routes/decorators.py`). A person of the other role gets "Access not allowed". There is no administrator.
  Nobody can pick their role by editing the form: it is only ever one of two values, checked on the server.
- **Private pages** are marked "do not store", so the Back button after signing out does not show them again.
- **Technical details** (SQL, errors) go to `logs/nephron.log`, never to the screen. Sign-in events are logged without passwords or emails.

Not in this version, on purpose: sending email (so no email check and no "forgot password" email), an administrator,
verifying that a professional really holds the licence they typed (their details are shown as "not verified"), and a
privacy notice. The privacy notice must be added before people enter health information.
If someone is locked out, whoever runs the system uses `python reset_password.py` in the terminal: it sets a new
password, removes the lock, and signs that account out everywhere.

## The database
`python init_db.py` creates the database from the numbered files in `database/migrations/` (see the README there).
Tables so far: `users`, `professionals` (linked to `users`, deleted with them), `login_attempts`, `assessments`
(one permanent row per completed screening; `source_assessment_id` links an 'enhanced' row to the 'preliminary' one
it extends), `assessment_inputs` (the answers behind each assessment; both deleted with the user), and
`lab_documents` (an uploaded lab document: what OCR read from it, what the person confirmed, and which assessment
it produced; deleted with the user), `authorizations` (a patient sharing their history with a professional),
`clinical_reviews` (a professional's note on one assessment) and `follow_up_requests` (a professional asking their
patient to screen again). All times are stored in UTC and shown in `APP_TIMEZONE`.
To look at them in MySQL:  `USE nephron;  SHOW TABLES;  DESCRIBE users;`

## Design previews (development only)
Set `FLASK_DEBUG=1` in `.env`, run the app, then open http://127.0.0.1:5000/design/ . The previews
show how screens built in later phases will look: sign-in, register, dashboard, guided screening,
result, and empty/loading/error states. `/style-guide` shows every component.

- **`/design/dashboard`** opens in its REAL state: a new person with no assessments (charts become empty states).
- **`/design/dashboard?data=sample`** fills it with made-up records so you can judge the populated design.
- **`/design/dashboard?data=sample&locked=1`** is the same sample, but with the waiting period between screenings still running (the hero and the quick action say when screening opens).
  Every chart carries a visible "Sample data" tag. Use the switch in the bottom bar to move between the two.
  In the waiting period, "Start Assessment" becomes a disabled item that says when screening opens.
- The result page has nothing to show without a result, so it always uses sample values and says so.

The previews never touch the database, and their buttons are inert or say "Preview only". With
`FLASK_DEBUG=0` they do not exist (the pages return 404). Sign in and Create account are already real (`/login`, `/register`); the previews of them show the same
design with sample behaviour. The other previews become real in later phases and will reuse the same layouts.

## Gender (with LGBTQ+ answers) and Nephron's own Philippines picture (migration 021)

Panel request: the "Sex" question is now **Gender**, with LGBTQ+ answers, and the dashboards show how many Nephron
users living in the Philippines are at risk, and how that compares by gender.

- **Gender question** (`ml/feature_catalog.json`, the Sex question's `asked_through` block): Male, Female, Gay man,
  Lesbian woman, Bisexual man, Bisexual woman, Transgender man, Transgender woman, Non-binary, Queer or another
  identity, Prefer not to say. The answer is saved exactly as chosen (`Gender` in the saved answers).
- **The model still gets Male or Female** - what it was trained on. An answer that tells the sex is translated
  (Gay man -> Male, Lesbian woman -> Female, Bisexual man -> Male...). For the answers that do not tell
  (transgender, non-binary, queer, prefer not to say) one extra question appears: **Sex assigned at birth**. The
  model is never given a guess. The server works this out again whatever the page sends
  (`screening_contract.validate_answers`), and `verify_model.py` still passes (the model's Sex values are unchanged).
- **After the first screening**, sex at birth stays as answered then (as before). Gender may change, but only to
  answers that agree with that sex; a contradicting one is refused, never silently applied.
- **Professionals** record a new patient's gender the same way (sex at birth asked only when needed). It is saved in
  the new `patient_records.gender` column and fixed in that patient's screenings.
- **Philippines and gender visuals** (`services/community_stats.py`), from each person's latest result, keeping only
  level, age, country and gender (`assessment_store.latest_profiles()` - no name, id or other answer):
  - General User dashboard: "Nephron users in the Philippines" - X of Y at higher risk, and a count plot by gender.
  - Professional dashboard: the same picture for everyone in the Philippines, plus their own patients - patients in
    the Philippines at higher risk, and their patients by gender.
  - Administrator overview: "People living in the Philippines" with the same two charts.
- **Privacy**: these are Nephron's own counts, labelled as such, not national statistics. Outside a professional's
  own patients, a gender with fewer than 3 people is combined into "Other answers" (or left out, with a note), so
  no one's result can be picked out, and the community cards wait until 5 people in the Philippines have a result.
- Screenings saved before Gender was asked are counted by their Sex (Male/Female).

**Run `python init_db.py` once** to add migration 021 (`patient_records.gender`).

## How the models work (administrator)

One more administrator page, in the sidebar next to Model performance:

- **How the models work** (`/admin/model/how-it-works`) - for each model:
  - **From answers to a result**: the saved pipeline, read from the model file itself and described in plain words.
    Steps: inputs, preparing the answers (blank-filling, one-hot encoding), the XGBoost model with its tree settings,
    isotonic calibration, the threshold rule, and the result.
  - **Where its inputs and weight come from**: each input group (About you, Health history... or the lab panels)
    with how much of the model's importance it carries.
  - **How it separates people**: the probabilities the model gave people with and without CKD in the test set,
    with the threshold marked.
  - **Why the threshold sits where it does**: sensitivity and specificity at every threshold, with the chosen one
    marked and the rule explained (Youden's J for Preliminary; at least 98% of cases caught for Enhanced).

The pipeline is read from the installed model. The charts come from `model_report.py`, which now also saves the
score distribution and the threshold trade-off. Run it once per model (an older `model_metrics.json` still works,
but these two charts ask for a re-run):

    python model_report.py --stage 1 --csv ml\validation_holdout.csv --target CKD
    python model_report.py --stage 2 --csv ml\stage2_sealed_test.csv --target CKD

`ml\stage2_sealed_test.csv` is the Stage 2 notebook's own sealed test split (20%, `random_state=42`, stratified on
CKD) of `CKD_RiskAssessment_Synthetic.csv`. Like `validation_holdout.csv`, it is a data file: keep it out of
public repositories.

> The earlier **Model comparison** page (baseline vs tuned Random Forest vs XGBoost) and its `compare_models.py`
> script were removed in Phase 9. The model-selection evidence still lives in `ml/model_stage2/README.md` and
> `ml/model_stage2/model_card_stage2.json` for the write-up.

## Where people live, the Pangasinan map, research data, and activity from exercise hours (migration 022)

**Run `python init_db.py` once** to add migration 022: `province_code`, `municipality_code` and `barangay_code` on
`users` and `patient_records`.

- **Where people live** (`services/ph_locations.py`). A General User who lives in the Philippines gives their
  province when registering (or later in *Your account*; the dashboard reminds anyone who has not). A Pangasinan
  resident also gives their municipality or city and their barangay. A professional records the same for a new patient.
  - Saved as official **PSGC codes**: barangay names repeat between towns, codes don't, and LGUs use the same codes.
  - The lists (85 provinces with Metro Manila as one choice, Pangasinan's 48 municipalities and cities, 1,364
    barangays) are in `data/ph_locations.json`.
  - The barangays of the chosen town load from `/locations/pangasinan/<code>/barangays`.
- **Pangasinan map** (admin sidebar, `/admin/map`, `services/location_heatmap.py`). A heatmap of Pangasinan, by
  municipality/city or by barangay, for the whole province or one town (choose a town or click it on the map).
  - It can show the **share at higher risk**, the **number at higher risk**, or the **number screened**, with a legend.
  - It counts General Users and professionals' patients, each once, by their latest result.
  - Totals per place only. A place with fewer than 3 people screened shows no risk figure (hatched on the map).
  - People elsewhere in the Philippines are listed by province.
  - **No map API, no key, no internet.** The map is drawn on the server from the official PSGC boundaries (31 December 2023, via
    `faeldon/philippines-json-maps`, MIT licence, in `data/maps/`). `scripts/build_ph_locations.py` rebuilds both
    files if the boundaries change.
  - Nine barangays have no outline in that source; they are counted in the tables, just not drawn.
- **Research data** (admin sidebar, `/admin/research-data`, `services/research_export.py`). Valid screenings as a CSV, one file per screening type:
  - **predictors only**, in the model's column order, de-identified (no name, email, id, date, gender or location, and no
    result; age 90 or over written as 90; rows shuffled);
  - each person's latest screening by default, or every screening;
  - every download is written to the activity log.
  
  To retrain on it, each row still needs a confirmed outcome (for example a diagnosis); the file has none on purpose.
  The registration form now says how answers are used.
- **"How active are you?" is no longer asked.** "Hours of exercise in a usual week" comes first, and the level is
  worked out from it and shown locked: under 0.6 hours Sedentary, 0.6–2 Light, 2.1–5 Moderate, 5.1 or more Active.
  - The cut-offs were read from the training data: they match the dataset's own activity level in 97.9% of its
    400,000 rows.
  - The server works the level out again, whatever the page sends.
  - The model's inputs are unchanged, so `verify_model.py` still passes.

## The re-assessment rule (migration 023)

Run `python init_db.py` once to apply migration 023, which adds two tables. The rule is **3 months** until the administrator changes it.

- **Waiting period.** After a screening, a General User can start the next one only when the waiting period has passed.
  - The period is counted in calendar months from their latest screening, for example 17 October to 17 January.
  - The administrator sets it on **Re-assessment rule**: 1 to 12 months, or no waiting period.
  - `REASSESSMENT_DAYS` in `.env` applies only when no administrator setting exists.
- **Screening again early.** During the waiting period, one early screening can be opened in two ways:
  - **A healthcare professional** the person shares their results with uses **Request follow-up** on the patient's page. This works for any profession: Nephrologist, Physician, Nurse or Other.
  - **The administrator** approves the person's own request. The person asks with **Ask the administrator** on the waiting page, giving an optional reason of up to 300 characters. The administrator approves or declines it on **Re-assessment rule**, and the person gets a notification either way.
- **One screening, then the rule again.** The next saved screening uses up the opening. The waiting period then applies again from that screening's date, until someone opens another one.
  - A request still waiting for a decision is closed when the person screens another way. It is listed as "Screened before a decision".
- **What the administrator sees for a request:** who asked, when, the reason they typed, and the date of their latest screening. It never shows their answers or results.
- Every request, decision and rule change is written to the activity log.

Code: `services/reassessment.py` holds the rules, `services/reassessment_store.py` holds the SQL, `services/eligibility.py` does the date arithmetic, and the tests are in `tests/test_reassessment_rule.py`.
