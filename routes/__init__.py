"""
HostFlow — Auth Decorators
"""

from functools import wraps
from flask import session, redirect, url_for, flash, abort, request


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login", next=request.url))
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("auth.login"))
            from utils.db import get_user_by_id
            user = get_user_by_id(session["user_id"])
            if not user or user["role"] not in roles:
                abort(403)
            if user["is_banned"] or user["is_suspended"]:
                session.clear()
                flash("Your account has been suspended.", "error")
                return redirect(url_for("auth.login"))
            return f(*args, **kwargs)
        return decorated
    return decorator


def admin_required(f):
    return role_required("admin", "super_admin", "moderator", "support_agent")(f)


def super_admin_required(f):
    return role_required("super_admin")(f)


def verified_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        from utils.db import get_user_by_id
        user = get_user_by_id(session["user_id"])
        if not user or not user["is_verified"]:
            flash("Please verify your email address first.", "warning")
            return redirect(url_for("auth.verify_email"))
        return f(*args, **kwargs)
    return decorated
