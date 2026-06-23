"""
HostFlow — Database Utility
SQLite3 for platform data. All raw queries use parameterised statements.
"""

import sqlite3
import os
import hashlib
import secrets
import string
from datetime import datetime, timedelta
from contextlib import contextmanager

from flask import current_app, g


# ── Connection management ─────────────────────────────────────────────────────

def get_db():
    """Return a per-request SQLite connection stored in Flask g."""
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["SQLITE_PATH"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@contextmanager
def db_conn(app=None):
    """Context manager for use outside request context (e.g. CLI, init)."""
    db_path = (app or current_app).config["SQLITE_PATH"]
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.commit()
        db.close()


# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT    UNIQUE NOT NULL,
    username        TEXT    UNIQUE NOT NULL,
    password_hash   TEXT    NOT NULL,
    role            TEXT    NOT NULL DEFAULT 'user',
    is_verified     INTEGER NOT NULL DEFAULT 0,
    is_suspended    INTEGER NOT NULL DEFAULT 0,
    is_banned       INTEGER NOT NULL DEFAULT 0,
    storage_limit_mb INTEGER NOT NULL DEFAULT 1024,
    avatar_url      TEXT,
    full_name       TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    last_login      TEXT,
    last_ip         TEXT,
    remember_token  TEXT
);

CREATE TABLE IF NOT EXISTS sites (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,
    subdomain       TEXT    UNIQUE NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'inactive',
    php_enabled     INTEGER NOT NULL DEFAULT 0,
    entry_file      TEXT,
    deploy_path     TEXT,
    storage_used_mb REAL    NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    deployed_at     TEXT,
    last_backed_up  TEXT
);

CREATE TABLE IF NOT EXISTS site_databases (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id         INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    db_name         TEXT    UNIQUE NOT NULL,
    db_user         TEXT    UNIQUE NOT NULL,
    db_password     TEXT    NOT NULL,
    db_host         TEXT    NOT NULL DEFAULT 'localhost',
    db_port         INTEGER NOT NULL DEFAULT 3306,
    status          TEXT    NOT NULL DEFAULT 'active',
    size_mb         REAL    NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS deployments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id         INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status          TEXT    NOT NULL DEFAULT 'pending',
    log             TEXT,
    zip_filename    TEXT,
    started_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    finished_at     TEXT
);

CREATE TABLE IF NOT EXISTS backups (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id         INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    filename        TEXT    NOT NULL,
    size_mb         REAL    NOT NULL DEFAULT 0,
    type            TEXT    NOT NULL DEFAULT 'manual',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS otps (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT    NOT NULL,
    code            TEXT    NOT NULL,
    purpose         TEXT    NOT NULL,
    expires_at      TEXT    NOT NULL,
    used            INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS activity_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action          TEXT    NOT NULL,
    entity_type     TEXT,
    entity_id       INTEGER,
    detail          TEXT,
    ip_address      TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
    title           TEXT    NOT NULL,
    message         TEXT    NOT NULL,
    type            TEXT    NOT NULL DEFAULT 'info',
    is_read         INTEGER NOT NULL DEFAULT 0,
    link            TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_token   TEXT    UNIQUE NOT NULL,
    ip_address      TEXT,
    user_agent      TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    last_active     TEXT    NOT NULL DEFAULT (datetime('now')),
    is_active       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS settings (
    key             TEXT    PRIMARY KEY,
    value           TEXT,
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS announcements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT    NOT NULL,
    message         TEXT    NOT NULL,
    type            TEXT    NOT NULL DEFAULT 'info',
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sites_user_id ON sites(user_id);
CREATE INDEX IF NOT EXISTS idx_activity_user_id ON activity_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_otps_email ON otps(email);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
"""

DEFAULT_SETTINGS = {
    "platform_name": "HostFlow",
    "platform_logo": "",
    "platform_favicon": "",
    "maintenance_mode": "0",
    "registration_enabled": "1",
    "default_storage_limit_mb": "1024",
    "turnstile_site_key": "",
    "turnstile_secret_key": "",
    "email_api_base": "",
}


def init_db(app):
    """Create schema and seed default settings."""
    with db_conn(app) as conn:
        conn.executescript(SCHEMA)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (key, value),
            )
    app.teardown_appcontext(close_db)


def seed_super_admin(app):
    """Create the initial super admin if none exists."""
    from utils.security import hash_password
    email = app.config["SUPER_ADMIN_EMAIL"]
    password = app.config["SUPER_ADMIN_PASSWORD"]
    with db_conn(app) as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE role = 'super_admin' LIMIT 1"
        ).fetchone()
        if not existing:
            username = email.split("@")[0]
            conn.execute(
                """INSERT INTO users (email, username, password_hash, role, is_verified)
                   VALUES (?, ?, ?, 'super_admin', 1)""",
                (email, username, hash_password(password)),
            )


# ── Generic helpers ───────────────────────────────────────────────────────────

def query(sql, params=(), one=False):
    cur = get_db().execute(sql, params)
    rv = cur.fetchone() if one else cur.fetchall()
    return rv


def execute(sql, params=()):
    db = get_db()
    cur = db.execute(sql, params)
    db.commit()
    return cur.lastrowid


# ── Settings ──────────────────────────────────────────────────────────────────

def get_setting(key, default=None):
    row = query("SELECT value FROM settings WHERE key = ?", (key,), one=True)
    if row:
        return row["value"]
    return default


def set_setting(key, value):
    execute(
        "INSERT INTO settings(key, value, updated_at) VALUES(?,?,datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value),
    )


# ── Users ─────────────────────────────────────────────────────────────────────

def get_user_by_id(user_id):
    return query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)


def get_user_by_email(email):
    return query("SELECT * FROM users WHERE email = ?", (email.lower(),), one=True)


def get_user_by_username(username):
    return query("SELECT * FROM users WHERE username = ?", (username,), one=True)


def create_user(email, username, password_hash, role="user"):
    return execute(
        "INSERT INTO users(email,username,password_hash,role) VALUES(?,?,?,?)",
        (email.lower(), username, password_hash, role),
    )


def update_user(user_id, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k}=?" for k in kwargs)
    execute(f"UPDATE users SET {cols} WHERE id=?", (*kwargs.values(), user_id))


def get_all_users(page=1, per_page=25, search=None):
    offset = (page - 1) * per_page
    if search:
        rows = query(
            "SELECT * FROM users WHERE email LIKE ? OR username LIKE ? "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (f"%{search}%", f"%{search}%", per_page, offset),
        )
        total = query(
            "SELECT COUNT(*) as c FROM users WHERE email LIKE ? OR username LIKE ?",
            (f"%{search}%", f"%{search}%"), one=True
        )["c"]
    else:
        rows = query(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (per_page, offset),
        )
        total = query("SELECT COUNT(*) as c FROM users", one=True)["c"]
    return rows, total


# ── Sites ─────────────────────────────────────────────────────────────────────

def get_site_by_user(user_id):
    return query("SELECT * FROM sites WHERE user_id = ? LIMIT 1", (user_id,), one=True)


def get_site_by_id(site_id):
    return query("SELECT * FROM sites WHERE id = ?", (site_id,), one=True)


def get_site_by_subdomain(subdomain):
    return query("SELECT * FROM sites WHERE subdomain = ?", (subdomain,), one=True)


def create_site(user_id, name, subdomain, deploy_path):
    return execute(
        "INSERT INTO sites(user_id,name,subdomain,deploy_path) VALUES(?,?,?,?)",
        (user_id, name, subdomain, deploy_path),
    )


def update_site(site_id, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k}=?" for k in kwargs)
    execute(f"UPDATE sites SET {cols} WHERE id=?", (*kwargs.values(), site_id))


def get_all_sites(page=1, per_page=25):
    offset = (page - 1) * per_page
    rows = query(
        """SELECT s.*, u.email, u.username FROM sites s
           JOIN users u ON s.user_id = u.id
           ORDER BY s.created_at DESC LIMIT ? OFFSET ?""",
        (per_page, offset),
    )
    total = query("SELECT COUNT(*) as c FROM sites", one=True)["c"]
    return rows, total


# ── Databases ─────────────────────────────────────────────────────────────────

def get_site_database(site_id):
    return query("SELECT * FROM site_databases WHERE site_id = ?", (site_id,), one=True)


def create_site_db_record(site_id, db_name, db_user, db_password, host="localhost"):
    return execute(
        "INSERT INTO site_databases(site_id,db_name,db_user,db_password,db_host) "
        "VALUES(?,?,?,?,?)",
        (site_id, db_name, db_user, db_password, host),
    )


def get_all_databases(page=1, per_page=25):
    offset = (page - 1) * per_page
    rows = query(
        """SELECT d.*, s.name as site_name, u.email FROM site_databases d
           JOIN sites s ON d.site_id = s.id
           JOIN users u ON s.user_id = u.id
           ORDER BY d.created_at DESC LIMIT ? OFFSET ?""",
        (per_page, offset),
    )
    total = query("SELECT COUNT(*) as c FROM site_databases", one=True)["c"]
    return rows, total


# ── Deployments ───────────────────────────────────────────────────────────────

def create_deployment(site_id, user_id, zip_filename):
    return execute(
        "INSERT INTO deployments(site_id,user_id,zip_filename,status) VALUES(?,?,?,'pending')",
        (site_id, user_id, zip_filename),
    )


def update_deployment(dep_id, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k}=?" for k in kwargs)
    execute(f"UPDATE deployments SET {cols} WHERE id=?", (*kwargs.values(), dep_id))


def get_deployment(dep_id):
    return query("SELECT * FROM deployments WHERE id=?", (dep_id,), one=True)


def get_site_deployments(site_id, limit=10):
    return query(
        "SELECT * FROM deployments WHERE site_id=? ORDER BY started_at DESC LIMIT ?",
        (site_id, limit),
    )


# ── Backups ───────────────────────────────────────────────────────────────────

def create_backup_record(site_id, filename, size_mb, btype="manual"):
    return execute(
        "INSERT INTO backups(site_id,filename,size_mb,type) VALUES(?,?,?,?)",
        (site_id, filename, size_mb, btype),
    )


def get_site_backups(site_id):
    return query(
        "SELECT * FROM backups WHERE site_id=? ORDER BY created_at DESC",
        (site_id,),
    )


def get_backup_by_id(backup_id):
    return query("SELECT * FROM backups WHERE id=?", (backup_id,), one=True)


def delete_backup_record(backup_id):
    execute("DELETE FROM backups WHERE id=?", (backup_id,))


# ── OTP ───────────────────────────────────────────────────────────────────────

def create_otp(email, code, purpose, expiry_minutes=15):
    expires = (datetime.utcnow() + timedelta(minutes=expiry_minutes)).isoformat()
    execute("DELETE FROM otps WHERE email=? AND purpose=?", (email, purpose))
    execute(
        "INSERT INTO otps(email,code,purpose,expires_at) VALUES(?,?,?,?)",
        (email, code, purpose, expires),
    )


def verify_otp(email, code, purpose):
    row = query(
        "SELECT * FROM otps WHERE email=? AND code=? AND purpose=? AND used=0",
        (email, code, purpose),
        one=True,
    )
    if not row:
        return False
    if datetime.fromisoformat(row["expires_at"]) < datetime.utcnow():
        return False
    execute("UPDATE otps SET used=1 WHERE id=?", (row["id"],))
    return True


# ── Activity Log ──────────────────────────────────────────────────────────────

def log_activity(user_id, action, entity_type=None, entity_id=None, detail=None, ip=None):
    execute(
        "INSERT INTO activity_logs(user_id,action,entity_type,entity_id,detail,ip_address) "
        "VALUES(?,?,?,?,?,?)",
        (user_id, action, entity_type, entity_id, detail, ip),
    )


def get_user_activity(user_id, limit=50):
    return query(
        "SELECT * FROM activity_logs WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    )


def get_all_activity(page=1, per_page=50):
    offset = (page - 1) * per_page
    rows = query(
        """SELECT a.*, u.email, u.username FROM activity_logs a
           LEFT JOIN users u ON a.user_id = u.id
           ORDER BY a.created_at DESC LIMIT ? OFFSET ?""",
        (per_page, offset),
    )
    total = query("SELECT COUNT(*) as c FROM activity_logs", one=True)["c"]
    return rows, total


# ── Notifications ─────────────────────────────────────────────────────────────

def create_notification(user_id, title, message, ntype="info", link=None):
    execute(
        "INSERT INTO notifications(user_id,title,message,type,link) VALUES(?,?,?,?,?)",
        (user_id, title, message, ntype, link),
    )


def get_user_notifications(user_id, limit=20):
    return query(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    )


def mark_notification_read(notif_id, user_id):
    execute(
        "UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?",
        (notif_id, user_id),
    )


def mark_all_read(user_id):
    execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (user_id,))


def get_unread_count(user_id):
    row = query(
        "SELECT COUNT(*) as c FROM notifications WHERE user_id=? AND is_read=0",
        (user_id,),
        one=True,
    )
    return row["c"] if row else 0


# ── Sessions (device tracking) ────────────────────────────────────────────────

def create_session_record(user_id, token, ip, ua):
    execute(
        "INSERT INTO sessions(user_id,session_token,ip_address,user_agent) VALUES(?,?,?,?)",
        (user_id, token, ip, ua),
    )


def invalidate_session(token):
    execute("UPDATE sessions SET is_active=0 WHERE session_token=?", (token,))


def get_user_sessions(user_id):
    return query(
        "SELECT * FROM sessions WHERE user_id=? AND is_active=1 ORDER BY last_active DESC",
        (user_id,),
    )


def refresh_session(token):
    execute(
        "UPDATE sessions SET last_active=datetime('now') WHERE session_token=?",
        (token,),
    )


# ── Announcements ─────────────────────────────────────────────────────────────

def get_active_announcements():
    return query(
        "SELECT * FROM announcements WHERE is_active=1 ORDER BY created_at DESC"
    )


def get_all_announcements(page=1, per_page=20):
    offset = (page - 1) * per_page
    rows = query(
        "SELECT * FROM announcements ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (per_page, offset),
    )
    total = query("SELECT COUNT(*) as c FROM announcements", one=True)["c"]
    return rows, total


def create_announcement(title, message, atype, created_by):
    return execute(
        "INSERT INTO announcements(title,message,type,created_by) VALUES(?,?,?,?)",
        (title, message, atype, created_by),
    )


# ── Stats (admin dashboard) ───────────────────────────────────────────────────

def get_platform_stats():
    return {
        "total_users": query("SELECT COUNT(*) as c FROM users", one=True)["c"],
        "active_sites": query(
            "SELECT COUNT(*) as c FROM sites WHERE status='active'", one=True
        )["c"],
        "total_sites": query("SELECT COUNT(*) as c FROM sites", one=True)["c"],
        "total_databases": query("SELECT COUNT(*) as c FROM site_databases", one=True)["c"],
        "total_backups": query("SELECT COUNT(*) as c FROM backups", one=True)["c"],
    }
