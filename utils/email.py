"""
HostFlow — Email & OTP Utilities
All email goes through the external MotaDev API. Never SMTP.
"""

import requests
from flask import current_app


def _api_base() -> str:
    from utils.db import get_setting
    base = get_setting("email_api_base") or current_app.config.get("EMAIL_API_BASE", "")
    return base.rstrip("/")


# ── OTP ───────────────────────────────────────────────────────────────────────

def send_otp(email: str, purpose: str = "verification") -> dict:
    """
    Generate and send an OTP code via the external API.
    Stores the OTP in the database.
    Returns {"success": bool, "code": str (for logging only)}.
    """
    from utils.security import generate_otp
    from utils.db import create_otp

    code = generate_otp(current_app.config.get("OTP_LENGTH", 6))
    expiry = current_app.config.get("OTP_EXPIRY_MINUTES", 15)
    create_otp(email, code, purpose, expiry)

    payload = {
        "email": email,
        "code": code,
        "purpose": purpose,
        "platform": current_app.config.get("PLATFORM_NAME", "HostFlow"),
    }

    try:
        resp = requests.post(
            _api_base() + current_app.config["EMAIL_API_OTP_ENDPOINT"],
            json=payload,
            timeout=10,
        )
        success = resp.status_code == 200
    except Exception as exc:
        current_app.logger.error(f"OTP send failed: {exc}")
        success = False

    return {"success": success, "code": code}


# ── General email ─────────────────────────────────────────────────────────────

def send_email(users: list[str], subject: str, html: str) -> bool:
    """
    Send an HTML email to one or more addresses via the external API.
    `users` is a list of email address strings.
    """
    payload = {
        "users": users,
        "subject": subject,
        "html": html,
        "from": current_app.config.get("EMAIL_FROM", "noreply@hostflow.dev"),
        "platform": current_app.config.get("PLATFORM_NAME", "HostFlow"),
    }

    try:
        resp = requests.post(
            _api_base() + current_app.config["EMAIL_API_MESSAGE_ENDPOINT"],
            json=payload,
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as exc:
        current_app.logger.error(f"Email send failed: {exc}")
        return False


# ── Convenience wrappers ──────────────────────────────────────────────────────

def _base_url() -> str:
    """Dynamically detect base URL from request context, fall back to config."""
    try:
        from flask import request as _req
        url_root = _req.url_root.rstrip("/")
        return url_root
    except RuntimeError:
        return current_app.config.get("PLATFORM_URL", "").rstrip("/")


def send_welcome_email(email: str, username: str) -> bool:
    platform = current_app.config.get("PLATFORM_NAME", "HostFlow")
    url = _base_url()
    html = f"""
    <div style="font-family:sans-serif;max-width:560px;margin:auto;padding:32px;">
      <h1 style="color:#3b82f6;">Welcome to {platform}</h1>
      <p>Hi <strong>{username}</strong>,</p>
      <p>Your account is verified and ready. Start hosting your website today.</p>
      <a href="{url}/dashboard"
         style="display:inline-block;padding:12px 24px;background:#2563eb;
                color:#fff;text-decoration:none;border-radius:8px;margin-top:16px;">
        Go to Dashboard
      </a>
      <p style="margin-top:32px;color:#888;font-size:13px;">
        &copy; {platform}. All rights reserved.
      </p>
    </div>
    """
    return send_email([email], f"Welcome to {platform}!", html)


def send_password_reset_email(email: str, code: str) -> bool:
    platform = current_app.config.get("PLATFORM_NAME", "HostFlow")
    html = f"""
    <div style="font-family:sans-serif;max-width:560px;margin:auto;padding:32px;">
      <h1 style="color:#3b82f6;">Reset Your Password</h1>
      <p>Use this code to reset your password. It expires in 15 minutes.</p>
      <div style="font-size:36px;letter-spacing:8px;font-weight:bold;
                  padding:24px;background:#0f0f11;color:#3b82f6;
                  border-radius:8px;text-align:center;margin:24px 0;">
        {code}
      </div>
      <p style="color:#888;font-size:13px;">
        If you did not request a password reset, ignore this email.
      </p>
    </div>
    """
    return send_email([email], f"[{platform}] Password Reset Code", html)


def send_deployment_notification(email: str, site_name: str, status: str) -> bool:
    platform = current_app.config.get("PLATFORM_NAME", "HostFlow")
    colour = "#22c55e" if status == "success" else "#ef4444"
    label = "Deployed Successfully" if status == "success" else "Deployment Failed"
    html = f"""
    <div style="font-family:sans-serif;max-width:560px;margin:auto;padding:32px;">
      <h1 style="color:{colour};">{label}</h1>
      <p>Your site <strong>{site_name}</strong> has been {label.lower()}.</p>
      <p style="color:#888;font-size:13px;">&copy; {platform}</p>
    </div>
    """
    return send_email([email], f"[{platform}] Site {label}: {site_name}", html)
