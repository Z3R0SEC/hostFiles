"""
HostFlow Platform — Configuration
Production-ready config with environment-based overrides.
"""

import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # ── Core ──────────────────────────────────────────────
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production-32chars+")
    PLATFORM_NAME = os.environ.get("PLATFORM_NAME", "HostFlow")
    PLATFORM_URL = os.environ.get("PLATFORM_URL", "http://localhost:5000")
    PLATFORM_DOMAIN = os.environ.get("PLATFORM_DOMAIN", "hostflow.dev")

    # ── Database ──────────────────────────────────────────
    SQLITE_PATH = os.path.join(BASE_DIR, "instance", "platform.db")
    DATABASE_URI = f"sqlite:///{SQLITE_PATH}"

    # MariaDB/MySQL for customer databases
    MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
    MYSQL_PORT = int(os.environ.get("MYSQL_PORT", 3306))
    MYSQL_ROOT_USER = os.environ.get("MYSQL_ROOT_USER", "root")
    MYSQL_ROOT_PASSWORD = os.environ.get("MYSQL_ROOT_PASSWORD", "")
    MYSQL_CHARSET = "utf8mb4"

    # ── Sessions ──────────────────────────────────────────
    SESSION_TYPE = "filesystem"
    SESSION_FILE_DIR = os.path.join(BASE_DIR, "instance", "sessions")
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("FLASK_ENV") == "production"

    # ── File Storage ──────────────────────────────────────
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    USER_SITES_DIR = os.path.join(BASE_DIR, "user_sites")
    BACKUPS_DIR = os.path.join(BASE_DIR, "backups")
    LOGS_DIR = os.path.join(BASE_DIR, "logs")
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500 MB
    ALLOWED_ZIP_EXTENSIONS = {"zip"}
    ALLOWED_EDIT_EXTENSIONS = {
        "php", "html", "htm", "css", "js", "json", "txt",
        "xml", "svg", "md", "htaccess", "env.example"
    }
    DEFAULT_STORAGE_LIMIT_MB = 1024  # 1 GB per site

    # ── Email / OTP API ───────────────────────────────────
    EMAIL_API_BASE = os.environ.get("EMAIL_API_BASE", "https://api.motadev.xyz")
    EMAIL_API_OTP_ENDPOINT = "/api/otp"
    EMAIL_API_MESSAGE_ENDPOINT = "/api/message"
    EMAIL_FROM = os.environ.get("EMAIL_FROM", "noreply@hostflow.dev")

    # ── OTP ───────────────────────────────────────────────
    OTP_EXPIRY_MINUTES = 15
    OTP_LENGTH = 6

    # ── Cloudflare Turnstile ──────────────────────────────
    TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "")
    TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "")

    # ── WTF / CSRF ────────────────────────────────────────
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600

    # ── Rate Limiting ─────────────────────────────────────
    RATELIMIT_DEFAULT = "200 per day;50 per hour"
    RATELIMIT_STORAGE_URL = "memory://"

    # ── PHP-FPM ───────────────────────────────────────────
    PHP_FPM_SOCKET = os.environ.get("PHP_FPM_SOCKET", "/run/php/php8.2-fpm.sock")

    # ── Nginx ─────────────────────────────────────────────
    NGINX_SITES_AVAILABLE = "/etc/nginx/sites-available"
    NGINX_SITES_ENABLED = "/etc/nginx/sites-enabled"
    NGINX_RELOAD_CMD = "sudo nginx -s reload"

    # ── SocketIO ─────────────────────────────────────────
    SOCKETIO_ASYNC_MODE = "eventlet"

    # ── Security Headers ─────────────────────────────────
    SECURITY_HEADERS = {
        "X-Frame-Options": "SAMEORIGIN",
        "X-Content-Type-Options": "nosniff",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    }

    # ── Maintenance ───────────────────────────────────────
    MAINTENANCE_MODE = False
    MAINTENANCE_ALLOWED_IPS = []

    # ── Super Admin Seed ─────────────────────────────────
    SUPER_ADMIN_EMAIL = os.environ.get("SUPER_ADMIN_EMAIL", "mothathabane@gmail.com")
    SUPER_ADMIN_PASSWORD = os.environ.get("SUPER_ADMIN_PASSWORD", "Mota@321")


class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    WTF_CSRF_SSL_STRICT = True


config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}

ActiveConfig = config_map.get(os.environ.get("FLASK_ENV", "default"), DevelopmentConfig)
