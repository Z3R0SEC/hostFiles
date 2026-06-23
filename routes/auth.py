"""
HostFlow — Authentication Routes
"""

from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, session, request, current_app
)
from app import limiter
from utils.db import (
    get_user_by_email, get_user_by_username, create_user,
    update_user, verify_otp, create_session_record, invalidate_session,
    get_user_sessions, log_activity
)
from utils.security import (
    hash_password, check_password, verify_turnstile,
    is_valid_email, is_valid_username, validate_password_strength, generate_token
)
from utils.email import send_otp, send_welcome_email, send_password_reset_email
from utils.validators import (
    RegisterForm, LoginForm, OTPForm, ForgotPasswordForm, ResetPasswordForm
)
from utils.activity_logger import log
from routes import login_required

auth_bp = Blueprint("auth", __name__)


# ── Register ──────────────────────────────────────────────────────────────────

@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def register():
    from utils.db import get_setting
    if get_setting("registration_enabled", "1") != "1":
        flash("Registration is currently disabled.", "error")
        return redirect(url_for("public.home"))

    if "user_id" in session:
        return redirect(url_for("dashboard.index"))

    form = RegisterForm()
    if form.validate_on_submit():
        # Turnstile
        if not verify_turnstile(request.form.get("cf-turnstile-response", "")):
            flash("Security check failed. Please try again.", "error")
            return render_template("auth/register.html", form=form)

        email = form.email.data.lower().strip()
        username = form.username.data.strip()
        password = form.password.data

        if get_user_by_email(email):
            flash("An account with that email already exists.", "error")
            return render_template("auth/register.html", form=form)

        if get_user_by_username(username):
            flash("That username is taken.", "error")
            return render_template("auth/register.html", form=form)

        ok, msg = validate_password_strength(password)
        if not ok:
            flash(msg, "error")
            return render_template("auth/register.html", form=form)

        user_id = create_user(email, username, hash_password(password))
        session["pending_verify_user_id"] = user_id
        session["pending_verify_email"] = email

        result = send_otp(email, "registration")
        if not result["success"]:
            flash("Could not send verification email. Please try again.", "error")
            return render_template("auth/register.html", form=form)

        flash("A verification code has been sent to your email.", "success")
        return redirect(url_for("auth.verify_email"))

    return render_template("auth/register.html", form=form)


# ── Email Verification ────────────────────────────────────────────────────────

@auth_bp.route("/verify-email", methods=["GET", "POST"])
def verify_email():
    user_id = session.get("pending_verify_user_id")
    email = session.get("pending_verify_email")

    if not user_id or not email:
        flash("No pending verification. Please register.", "warning")
        return redirect(url_for("auth.register"))

    form = OTPForm()
    if form.validate_on_submit():
        if verify_otp(email, form.code.data, "registration"):
            update_user(user_id, is_verified=1)
            session.pop("pending_verify_user_id", None)
            session.pop("pending_verify_email", None)
            session["user_id"] = user_id
            from utils.db import get_user_by_id
            user = get_user_by_id(user_id)
            send_welcome_email(email, user["username"])
            log("register", "user", user_id, f"Verified email {email}")
            flash("Email verified! Welcome to HostFlow.", "success")
            return redirect(url_for("dashboard.index"))
        else:
            flash("Invalid or expired code.", "error")

    return render_template("auth/verify_email.html", form=form, email=email)


@auth_bp.route("/resend-otp")
def resend_otp():
    email = session.get("pending_verify_email")
    if not email:
        return redirect(url_for("auth.register"))
    send_otp(email, "registration")
    flash("A new code has been sent.", "success")
    return redirect(url_for("auth.verify_email"))


# ── Login ─────────────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("20 per hour")
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard.index"))

    form = LoginForm()
    if form.validate_on_submit():
        if not verify_turnstile(request.form.get("cf-turnstile-response", "")):
            flash("Security check failed.", "error")
            return render_template("auth/login.html", form=form)

        user = get_user_by_email(form.email.data.lower())
        if not user or not check_password(user["password_hash"], form.password.data):
            flash("Invalid email or password.", "error")
            return render_template("auth/login.html", form=form)

        if user["is_banned"]:
            flash("Your account has been permanently banned.", "error")
            return render_template("auth/login.html", form=form)

        if user["is_suspended"]:
            flash("Your account is suspended. Contact support.", "error")
            return render_template("auth/login.html", form=form)

        if not user["is_verified"]:
            session["pending_verify_user_id"] = user["id"]
            session["pending_verify_email"] = user["email"]
            send_otp(user["email"], "registration")
            flash("Please verify your email first.", "warning")
            return redirect(url_for("auth.verify_email"))

        session["user_id"] = user["id"]
        session["role"] = user["role"]

        if form.remember_me.data:
            session.permanent = True

        ip = request.remote_addr
        ua = request.headers.get("User-Agent", "")
        token = generate_token()
        session["session_token"] = token
        create_session_record(user["id"], token, ip, ua)
        update_user(user["id"], last_login="datetime('now')", last_ip=ip)

        log("login", "user", user["id"])
        next_url = request.args.get("next")
        return redirect(next_url or url_for("dashboard.index"))

    return render_template("auth/login.html", form=form)


# ── Logout ────────────────────────────────────────────────────────────────────

@auth_bp.route("/logout")
@login_required
def logout():
    token = session.get("session_token")
    if token:
        invalidate_session(token)
    log("logout")
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


# ── Forgot Password ───────────────────────────────────────────────────────────

@auth_bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per hour")
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        email = form.email.data.lower()
        user = get_user_by_email(email)
        if user:
            result = send_otp(email, "password_reset")
            send_password_reset_email(email, result["code"])
        # Always show the same message (prevents email enumeration)
        flash("If that email exists, a reset code has been sent.", "info")
        session["reset_email"] = email
        return redirect(url_for("auth.reset_password"))

    return render_template("auth/forgot_password.html", form=form)


@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    email = session.get("reset_email")
    if not email:
        return redirect(url_for("auth.forgot_password"))

    form = ResetPasswordForm(email=email)
    if form.validate_on_submit():
        if verify_otp(form.email.data, form.code.data, "password_reset"):
            ok, msg = validate_password_strength(form.password.data)
            if not ok:
                flash(msg, "error")
                return render_template("auth/reset_password.html", form=form, email=email)
            user = get_user_by_email(form.email.data)
            if user:
                update_user(user["id"], password_hash=hash_password(form.password.data))
                log("password_reset", "user", user["id"])
                session.pop("reset_email", None)
                flash("Password changed successfully. Please log in.", "success")
                return redirect(url_for("auth.login"))
        else:
            flash("Invalid or expired code.", "error")

    return render_template("auth/reset_password.html", form=form, email=email)
