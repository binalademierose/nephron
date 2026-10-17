"""
config.py - every application setting lives here.

Values come from the ".env" file (see ".env.example"), so no password or
secret is ever written inside the code.
"""
import os
import re
from datetime import timedelta

from dotenv import load_dotenv

from services import clock

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _get_bool(name, default=False):
    """Read a true/false setting such as FLASK_DEBUG=1."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _get_optional_int(name):
    """A whole number from .env, or None when the setting is empty. Text that is not a number is kept as text
    so validate_config() can explain the mistake in plain words."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return raw


class Config:
    APP_NAME = "Nephron"

    # Shown in the footer of every page and, later, in every report.
    MEDICAL_DISCLAIMER = (
        "Nephron provides risk screening and decision-support information. "
        "It does not provide a medical diagnosis and does not replace "
        "professional medical evaluation or clinical judgment."
    )

    # The secret key signs the session cookie. It has no default on purpose.
    SECRET_KEY = os.getenv("SECRET_KEY")
    DEBUG = _get_bool("FLASK_DEBUG", False)

    # MySQL connection
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_NAME = os.getenv("DB_NAME", "nephron")

    # Session cookie safety
    SESSION_COOKIE_HTTPONLY = True   # JavaScript cannot read the cookie
    SESSION_COOKIE_SAMESITE = "Lax"  # the browser will not send it from other sites
    SESSION_COOKIE_SECURE = _get_bool("SESSION_COOKIE_SECURE", False)

    # How many trusted reverse proxies sit in front of the app. 0 (the default) means the app is reached directly,
    # so forwarded headers like X-Forwarded-Proto/X-Forwarded-For are IGNORED - otherwise a client could spoof them.
    # Behind exactly one trusted proxy that terminates HTTPS (for example Vercel, or nginx), set TRUSTED_PROXY_COUNT=1
    # so request.is_secure and the client IP are read from that proxy's headers. See app.py (ProxyFix).
    _proxy_hops = _get_optional_int("TRUSTED_PROXY_COUNT")
    TRUSTED_PROXY_HOPS = _proxy_hops if isinstance(_proxy_hops, int) and _proxy_hops >= 0 else 0
    PERMANENT_SESSION_LIFETIME = timedelta(
        minutes=int(os.getenv("SESSION_LIFETIME_MINUTES", "30"))
    )

    # Sign-in protection: after this many wrong passwords for one email address, that address is locked
    # for LOGIN_LOCK_MINUTES (the failures are counted inside that same window).
    LOGIN_MAX_FAILURES = 5
    LOGIN_LOCK_MINUTES = 15

    # Central rules the dashboard reads (never written into a page or a template).
    # REASSESSMENT_DAYS: how many days must pass before a new screening may start. Empty = no waiting period.
    #                    Nephron has not fixed a real value yet, so it is empty until the team decides.
    # APP_TIMEZONE: the time zone dates are shown in. Times are stored in UTC.
    REASSESSMENT_DAYS = _get_optional_int("REASSESSMENT_DAYS")
    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Manila").strip() or "Asia/Manila"

    # Where the saved model lives (model_metadata.json and the model file). See ml/README.md.
    MODEL_DIR = os.getenv("MODEL_DIR", "").strip() or os.path.join(BASE_DIR, "ml", "model")
    # Where the Stage 2 (Enhanced Screening) model lives. See ml/model_stage2/README.md.
    MODEL_STAGE2_DIR = os.getenv("MODEL_STAGE2_DIR", "").strip() or os.path.join(BASE_DIR, "ml", "model_stage2")
    # Where an uploaded lab document is stored until it is confirmed or discarded. Outside static/ on purpose:
    # a lab document is private and must never be reachable by guessing its URL.
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "").strip() or os.path.join(BASE_DIR, "uploads")
    # The full path to tesseract.exe (Windows) / the tesseract binary, only if it is not already on PATH. Leave
    # empty to rely on PATH (pytesseract's default). See requirements.txt.
    TESSERACT_CMD = os.getenv("TESSERACT_CMD", "").strip()

    LOG_DIR = os.path.join(BASE_DIR, "logs")


def validate_config(config):
    """Stop early, with a clear message, if a required setting is missing or makes no sense."""
    if not config.get("SECRET_KEY"):
        raise RuntimeError(
            "SECRET_KEY is missing. Copy .env.example to .env and set SECRET_KEY "
            "(see the comment inside .env.example for how to generate one)."
        )
    # A database name is placed in SQL text (it cannot be a parameter),
    # so only plain letters, digits and underscores are accepted.
    if not re.fullmatch(r"[A-Za-z0-9_]+", config["DB_NAME"]):
        raise RuntimeError("DB_NAME may contain only letters, digits and underscores.")
    days = config.get("REASSESSMENT_DAYS")
    if days is not None and (not isinstance(days, int) or days < 1):
        raise RuntimeError("REASSESSMENT_DAYS must be a whole number of days (1 or more), or empty for no waiting period.")
    zone = config.get("APP_TIMEZONE")
    if zone is not None and not clock.timezone_exists(zone):
        raise RuntimeError(
            f"APP_TIMEZONE '{zone}' is not a known time zone. Use a name such as Asia/Manila. "
            "On Windows the time zone list comes from the 'tzdata' library: run  pip install -r requirements.txt"
        )
