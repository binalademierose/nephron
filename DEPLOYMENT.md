# Deploying Nephron

Nephron is a Flask app that needs **MySQL** and, for the photo/PDF lab-upload feature, two system programs
(**Tesseract** and **Poppler**). Pick a host based on whether you need that OCR feature.

| | Container host (Render / Railway / Fly.io / a VPS) | Vercel |
|---|---|---|
| Effort | Low — runs almost as-is | Medium — a few constraints |
| OCR photo upload | ✅ works (`apt-get install tesseract-ocr poppler-utils`) | ❌ not available (manual lab entry still works) |
| Filesystem | writable | read-only except `/tmp` (the app already handles this) |
| MySQL | can run alongside the app | must be an external managed MySQL |
| Keeps warm | yes (fast) | cold starts load the models (a few seconds) |

**Recommendation:** if the OCR photo-upload matters for your defense, use a container host. Otherwise either works.

---

## 1. A managed MySQL (both hosts need this; a container host can run its own)

Create a MySQL 8 database (PlanetScale, Aiven, Railway, TiDB Cloud, or the one your container host provides). Note
the host, port, user, password, and database name. It must accept TLS connections from where the app runs.

## 2. Set environment variables (never commit them)

```
SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
FLASK_DEBUG=0
SESSION_COOKIE_SECURE=1
TRUSTED_PROXY_COUNT=1          # Vercel or nginx in front; use 0 only if the app is reached directly
APP_TIMEZONE=Asia/Manila
DB_HOST=...
DB_PORT=3306
DB_USER=...
DB_PASSWORD=...
DB_NAME=nephron
```

## 3. Create the tables and the first administrator (run once, pointed at the production DB)

```
python init_db.py                         # creates every table (migrations 001-023)
python create_admin.py you@example.com "Your Name"   # the ONLY way to make an admin (never via the sign-up page)
```

Run these from a machine that can reach the production database, with the same `.env`/environment values.

## 4a. Deploy on Railway (recommended)

The repo already has a **`Dockerfile`** that installs Tesseract + Poppler (so OCR works) and serves the app with
gunicorn. Railway detects the Dockerfile automatically — no build config needed.

1. **Push the repo to GitHub** (private). `.env` is git-ignored; the model files under `ml/model` and
   `ml/model_stage2` ARE committed (Railway needs them).
2. On **railway.app**: New Project → Deploy from GitHub repo → pick your repo. Railway builds the Dockerfile.
3. In the same project: New → Database → **MySQL**. Railway creates it with `MYSQLHOST`, `MYSQLPORT`, `MYSQLUSER`,
   `MYSQLPASSWORD`, `MYSQLDATABASE` variables.
4. On the **app service → Variables**, add:
   ```
   SECRET_KEY            = (python -c "import secrets; print(secrets.token_hex(32))")
   FLASK_DEBUG           = 0
   SESSION_COOKIE_SECURE = 1
   TRUSTED_PROXY_COUNT   = 1
   APP_TIMEZONE          = Asia/Manila
   DB_HOST               = ${{MySQL.MYSQLHOST}}
   DB_PORT               = ${{MySQL.MYSQLPORT}}
   DB_USER               = ${{MySQL.MYSQLUSER}}
   DB_PASSWORD           = ${{MySQL.MYSQLPASSWORD}}
   DB_NAME               = ${{MySQL.MYSQLDATABASE}}
   ```
   (The `${{MySQL.*}}` references use Railway's private network between the two services.)
5. **Create the tables and your admin** (step 3 above), once. Easiest: in the MySQL service, open the **Connect**
   tab to get the *public* connection values, put them in your local `.env`, and run `python init_db.py` then
   `python create_admin.py you@example.com "Your Name"` from your PC. (Or, with the Railway CLI: `railway run python
   init_db.py`.)
6. On the app service → **Settings → Networking → Generate Domain** to get a public HTTPS URL. Railway terminates
   HTTPS for you, which is why `TRUSTED_PROXY_COUNT=1` is set.

This path keeps the database on Railway's private network and keeps the OCR photo-upload working.

### Any other container host (Render private service, Fly.io, a VPS)
The same `Dockerfile` works. Build and run it; set the same environment variables; point `DB_*` at your MySQL.

## 4b. Deploy on Vercel

- `requirements.txt`, `.python-version` (3.13) and `vercel.json` are already in the repo. Vercel auto-detects the
  Flask `app` in `app.py`.
- **OCR will not run** (Tesseract/Poppler can't be installed) — the upload page offers manual entry instead.
- Set the environment variables from step 2 in the Vercel project settings.
- **Static files:** if your CSS/JS/images do not load, Vercel is serving `/static` from its CDN rather than through
  Flask. Fix by either moving the `static/` folder to a top-level `public/` folder, or adding a rewrite in
  `vercel.json` that sends `/static/(.*)` to the function. (On a container host this is not an issue.)
- Keep uploads pointed at the writable temp dir: set `UPLOAD_DIR=/tmp/uploads` (anything written elsewhere fails on
  Vercel's read-only filesystem). Uploaded files are only needed during the one request that reads them, so `/tmp`
  is fine.
- Request bodies are capped at 4.5 MB on Vercel; the app accepts up to 10 MB, so very large photos are rejected by
  the platform before reaching the app. Ask users to upload a smaller image, or lower `MAX_UPLOAD_BYTES`.

## 5. Before you call it live
- Confirm both models load: open **Admin → Model performance**; both should say "ready". If one says the library
  version is wrong, your installed `scikit-learn` isn't `1.8.0` (see `requirements.txt`).
- Sign in as the admin, create a general and a professional account, run one screening end to end.
- Confirm the address bar shows HTTPS and that signing out then pressing Back does not show a private page.
