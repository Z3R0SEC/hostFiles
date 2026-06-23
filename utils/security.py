"""
HostFlow — Security Utilities
Password hashing, token generation, Turnstile verification.
"""

import hashlib
import hmac
import os
import re
import secrets
import string

import requests
from flask import current_app, request


# ── Password ──────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Return a salted SHA-256 hash. Use bcrypt in production if preferred."""
    salt = secrets.token_hex(32)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"pbkdf2:sha256:{salt}:{h.hex()}"


def check_password(stored: str, candidate: str) -> bool:
    parts = stored.split(":")
    if len(parts) != 4 or parts[0] != "pbkdf2":
        return False
    _, algo, salt, stored_hash = parts
    h = hashlib.pbkdf2_hmac(algo, candidate.encode(), salt.encode(), 260_000)
    return hmac.compare_digest(h.hex(), stored_hash)


def validate_password_strength(password: str) -> tuple[bool, str]:
    if len(password) < 8:
        return False, "Password must be at least 8 characters."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r"\d", password):
        return False, "Password must contain at least one digit."
    return True, ""


# ── Tokens ────────────────────────────────────────────────────────────────────

def generate_token(n=32) -> str:
    return secrets.token_urlsafe(n)


def generate_otp(length=6) -> str:
    return "".join(secrets.choice(string.digits) for _ in range(length))


def generate_db_password(length=20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        # ensure complexity
        if (
            any(c.isupper() for c in pwd)
            and any(c.islower() for c in pwd)
            and any(c.isdigit() for c in pwd)
        ):
            return pwd


# ── Turnstile ─────────────────────────────────────────────────────────────────

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def verify_turnstile(token: str) -> bool:
    secret = current_app.config.get("TURNSTILE_SECRET_KEY", "")
    if not secret or not token:
        # If no key configured, skip verification (dev mode)
        return True
    try:
        resp = requests.post(
            TURNSTILE_VERIFY_URL,
            data={
                "secret": secret,
                "response": token,
                "remoteip": request.remote_addr,
            },
            timeout=5,
        )
        return resp.json().get("success", False)
    except Exception:
        return False


# ── Input sanitisation ────────────────────────────────────────────────────────

SAFE_SUBDOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,61}[a-z0-9]$")
SAFE_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,30}$")


def sanitise_subdomain(name: str) -> str:
    """Convert a site name to a safe lowercase subdomain slug."""
    slug = re.sub(r"[^a-z0-9\-]", "-", name.lower().strip())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:62]


def is_valid_subdomain(subdomain: str) -> bool:
    return bool(SAFE_SUBDOMAIN_RE.match(subdomain))


def is_valid_username(username: str) -> bool:
    return bool(SAFE_USERNAME_RE.match(username))


def is_valid_email(email: str) -> bool:
    pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


# ── Path traversal guard ──────────────────────────────────────────────────────

def safe_join(base: str, *paths) -> str | None:
    """Return the joined path only if it stays within base. Returns None on traversal."""
    target = os.path.realpath(os.path.join(base, *paths))
    base_real = os.path.realpath(base)
    if not target.startswith(base_real + os.sep) and target != base_real:
        return None
    return target
