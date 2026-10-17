"""
security.py - passwords, form tokens (CSRF) and safe redirects.

Three ideas, each in a few lines:
  1. PASSWORDS are never stored. Only a salted, deliberately slow hash is (Werkzeug's scrypt).
  2. A CSRF TOKEN is a secret number kept in the person's session and copied into every form. A form sent from
     another website cannot know it, so the server rejects the request. That stops other sites from making
     a signed-in person's browser do things they did not ask for.
  3. A SAFE REDIRECT accepts only addresses inside this site, so a link like /login?next=https://evil.example
     cannot send someone away after they sign in.
"""
import hmac
import secrets
from urllib.parse import urlsplit

from flask import request, session
from werkzeug.security import check_password_hash, generate_password_hash


# ---------------------------------------------------------------- passwords
def hash_password(password):
    """Return the salted hash to store. scrypt is the default; older Python builds fall back to PBKDF2."""
    try:
        return generate_password_hash(password, method="scrypt")
    except (ValueError, AttributeError):
        return generate_password_hash(password, method="pbkdf2:sha256")


def verify_password(stored_hash, password):
    return check_password_hash(stored_hash, password)


# A hash of a random password nobody knows. When someone signs in with an email that has no account, we still
# check the password against this, so that answering takes about as long as for a real account and the
# time it takes cannot be used to discover which emails are registered.
DUMMY_HASH = hash_password(secrets.token_hex(16))


# ---------------------------------------------------------------- CSRF
def csrf_token():
    """The token for this session (created the first time it is needed)."""
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def csrf_is_valid(submitted):
    expected = session.get("csrf_token")
    return bool(expected) and bool(submitted) and hmac.compare_digest(expected, submitted)


# ---------------------------------------------------------------- redirects
def safe_next_url(target, fallback):
    """Return `target` if it points inside this site, otherwise `fallback`."""
    if not target or not isinstance(target, str):
        return fallback
    if any(ord(character) < 32 for character in target):          # control characters, line breaks
        return fallback
    if not target.startswith("/") or target.startswith("//") or target.startswith("/\\"):
        return fallback
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return fallback
    return target


def client_ip():
    return (request.remote_addr or "")[:45]
