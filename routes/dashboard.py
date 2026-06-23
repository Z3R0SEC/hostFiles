"""
HostFlow — Dashboard Routes
"""

from flask import Blueprint, render_template, redirect, url_for, flash, session, request
from routes import login_required, verified_required
from utils.db import (
    get_user_by_id, get_site_by_user, get_user_activity,
    get_user_notifications, get_unread_count, mark_all_read,
    mark_notification_read, get_user_sessions, get_active_announcements,
    update_user
)
from utils.security import check_password, hash_password, validate_password_strength
from utils.validators import ChangePasswordForm, ChangeEmailForm
from utils.email import send_otp
from utils.db import verify_otp

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.before_request
@login_required
def require_login():
    pass


@dashboard_bp.route("/")
def index():
    user = get_user_by_id(session["user_id"])
    site = get_site_by_user(user["id"])
    activity = get_user_activity(user["id"], limit=10)
    notifications = get_user_notifications(user["id"], limit=5)
    announcements = get_active_announcements()
    unread = get_unread_count(user["id"])

    storage_pct = 0
    if site and user["storage_limit_mb"] > 0:
        storage_pct = round((site["storage_used_mb"] / user["storage_limit_mb"]) * 100, 1)

    return render_template(
        "dashboard/index.html",
        user=user,
        site=site,
        activity=activity,
        notifications=notifications,
        announcements=announcements,
        unread=unread,
        storage_pct=storage_pct,
    )


@dashboard_bp.route("/profile", methods=["GET", "POST"])
def profile():
    user = get_user_by_id(session["user_id"])
    cp_form = ChangePasswordForm()
    ce_form = ChangeEmailForm()
    sessions = get_user_sessions(user["id"])

    if request.method == "POST":
        action = request.form.get("action")

        if action == "change_password" and cp_form.validate_on_submit():
            if not check_password(user["password_hash"], cp_form.current_password.data):
                flash("Current password is incorrect.", "error")
            else:
                ok, msg = validate_password_strength(cp_form.new_password.data)
                if not ok:
                    flash(msg, "error")
                else:
                    update_user(user["id"], password_hash=hash_password(cp_form.new_password.data))
                    flash("Password updated successfully.", "success")
                    return redirect(url_for("dashboard.profile"))

        elif action == "change_email" and ce_form.validate_on_submit():
            if not check_password(user["password_hash"], ce_form.password.data):
                flash("Password is incorrect.", "error")
            else:
                new_email = ce_form.new_email.data.lower()
                from utils.db import get_user_by_email
                if get_user_by_email(new_email):
                    flash("That email is already in use.", "error")
                else:
                    send_otp(new_email, "email_change")
                    session["pending_email_change"] = new_email
                    flash("Verification code sent to your new email.", "info")
                    return redirect(url_for("dashboard.verify_email_change"))

    return render_template(
        "dashboard/profile.html",
        user=user, cp_form=cp_form, ce_form=ce_form, sessions=sessions
    )


@dashboard_bp.route("/verify-email-change", methods=["GET", "POST"])
def verify_email_change():
    new_email = session.get("pending_email_change")
    if not new_email:
        return redirect(url_for("dashboard.profile"))

    from utils.validators import OTPForm
    form = OTPForm()
    if form.validate_on_submit():
        if verify_otp(new_email, form.code.data, "email_change"):
            update_user(session["user_id"], email=new_email)
            session.pop("pending_email_change", None)
            flash("Email updated successfully.", "success")
            return redirect(url_for("dashboard.profile"))
        else:
            flash("Invalid or expired code.", "error")

    return render_template("dashboard/verify_email_change.html", form=form, new_email=new_email)


@dashboard_bp.route("/notifications")
def notifications():
    user_id = session["user_id"]
    notifs = get_user_notifications(user_id, limit=50)
    mark_all_read(user_id)
    return render_template("dashboard/notifications.html", notifications=notifs)


@dashboard_bp.route("/notifications/<int:notif_id>/read")
def mark_read(notif_id):
    mark_notification_read(notif_id, session["user_id"])
    return redirect(url_for("dashboard.notifications"))
