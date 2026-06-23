"""
HostFlow — Admin Control Center Routes
"""

from flask import (
    Blueprint, render_template, redirect, url_for, flash,
    session, request, jsonify, current_app
)
from routes import admin_required, super_admin_required
from utils.db import (
    get_all_users, get_user_by_id, update_user, get_all_sites,
    get_all_databases, get_platform_stats, get_all_activity,
    get_all_announcements, create_announcement, get_setting, set_setting,
    execute, query
)
from utils.validators import AdminUserForm, SystemSettingsForm, AnnouncementForm
from utils.email import send_email
from utils.activity_logger import log

admin_bp = Blueprint("admin", __name__)


@admin_bp.before_request
@admin_required
def check_admin():
    pass


# ── Dashboard ─────────────────────────────────────────────────────────────────

@admin_bp.route("/")
def dashboard():
    stats = get_platform_stats()
    activity, _ = get_all_activity(per_page=20)

    import shutil
    disk = shutil.disk_usage("/")
    disk_pct = round((disk.used / disk.total) * 100, 1)

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        activity=activity,
        disk_total_gb=round(disk.total / (1024 ** 3), 1),
        disk_used_gb=round(disk.used / (1024 ** 3), 1),
        disk_pct=disk_pct,
    )


# ── Users ─────────────────────────────────────────────────────────────────────

@admin_bp.route("/users")
def users():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "")
    rows, total = get_all_users(page=page, per_page=25, search=search or None)
    pages = (total + 24) // 25
    return render_template("admin/users.html", users=rows, total=total,
                           page=page, pages=pages, search=search)


@admin_bp.route("/users/<int:user_id>", methods=["GET", "POST"])
def edit_user(user_id):
    user = get_user_by_id(user_id)
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("admin.users"))

    form = AdminUserForm(obj=user)
    if form.validate_on_submit():
        admin = get_user_by_id(session["user_id"])
        # Prevent non-super-admin from editing super_admin
        if user["role"] == "super_admin" and admin["role"] != "super_admin":
            flash("Cannot edit a super admin.", "error")
            return redirect(url_for("admin.users"))

        update_user(
            user_id,
            role=form.role.data,
            is_verified=int(form.is_verified.data),
            is_suspended=int(form.is_suspended.data),
            is_banned=int(form.is_banned.data),
            storage_limit_mb=int(form.storage_limit_mb.data or 1024),
        )
        log("admin_edit_user", "user", user_id, f"Role={form.role.data}")
        flash("User updated.", "success")
        return redirect(url_for("admin.users"))

    from utils.db import get_site_by_user, get_user_activity
    site = get_site_by_user(user_id)
    activity = get_user_activity(user_id, limit=20)
    return render_template("admin/user_detail.html", user=user, form=form,
                           site=site, activity=activity)


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@super_admin_required
def delete_user(user_id):
    user = get_user_by_id(user_id)
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("admin.users"))
    if user["role"] == "super_admin":
        flash("Cannot delete super admin.", "error")
        return redirect(url_for("admin.users"))

    execute("DELETE FROM users WHERE id=?", (user_id,))
    log("admin_delete_user", "user", user_id)
    flash(f"User {user['email']} deleted.", "info")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/impersonate")
@super_admin_required
def impersonate(user_id):
    user = get_user_by_id(user_id)
    if not user or user["role"] == "super_admin":
        flash("Cannot impersonate.", "error")
        return redirect(url_for("admin.users"))

    session["impersonator_id"] = session["user_id"]
    session["user_id"] = user["id"]
    session["role"] = user["role"]
    flash(f"Now logged in as {user['email']}. Return via admin panel.", "warning")
    log("impersonate_user", "user", user_id)
    return redirect(url_for("dashboard.index"))


@admin_bp.route("/stop-impersonation")
def stop_impersonation():
    original_id = session.pop("impersonator_id", None)
    if not original_id:
        return redirect(url_for("dashboard.index"))
    session["user_id"] = original_id
    admin = get_user_by_id(original_id)
    session["role"] = admin["role"] if admin else "admin"
    flash("Returned to your admin session.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
def reset_user_password(user_id):
    from utils.security import generate_token, hash_password
    import secrets
    import string
    new_pwd = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
    update_user(user_id, password_hash=hash_password(new_pwd))
    user = get_user_by_id(user_id)
    if user:
        send_email(
            [user["email"]],
            "Your password has been reset",
            f"<p>Your temporary password is: <strong>{new_pwd}</strong></p><p>Please change it after logging in.</p>"
        )
    flash(f"Password reset. Temp: {new_pwd}", "info")
    return redirect(url_for("admin.edit_user", user_id=user_id))


# ── Sites ─────────────────────────────────────────────────────────────────────

@admin_bp.route("/sites")
def sites():
    page = request.args.get("page", 1, type=int)
    rows, total = get_all_sites(page=page, per_page=25)
    pages = (total + 24) // 25
    return render_template("admin/sites.html", sites=rows, total=total,
                           page=page, pages=pages)


# ── Databases ─────────────────────────────────────────────────────────────────

@admin_bp.route("/databases")
def databases():
    page = request.args.get("page", 1, type=int)
    rows, total = get_all_databases(page=page, per_page=25)
    pages = (total + 24) // 25
    return render_template("admin/databases.html", databases=rows, total=total,
                           page=page, pages=pages)


# ── Backups ───────────────────────────────────────────────────────────────────

@admin_bp.route("/backups")
def backups():
    rows = query("SELECT b.*, s.name as site_name FROM backups b JOIN sites s ON b.site_id=s.id ORDER BY b.created_at DESC LIMIT 100")
    return render_template("admin/backups.html", backups=rows)


# ── Logs ──────────────────────────────────────────────────────────────────────

@admin_bp.route("/logs")
def logs():
    page = request.args.get("page", 1, type=int)
    rows, total = get_all_activity(page=page, per_page=50)
    pages = (total + 49) // 50
    return render_template("admin/logs.html", logs=rows, total=total,
                           page=page, pages=pages)


# ── Announcements ─────────────────────────────────────────────────────────────

@admin_bp.route("/announcements", methods=["GET", "POST"])
def announcements():
    form = AnnouncementForm()
    if form.validate_on_submit():
        ann_id = create_announcement(
            form.title.data,
            form.message.data,
            form.type.data,
            session["user_id"],
        )

        send_all = request.form.get("send_all") == "1"
        if send_all:
            all_users = query("SELECT email FROM users WHERE is_banned=0 AND is_suspended=0")
            emails = [u["email"] for u in all_users]
            if emails:
                send_email(emails, form.title.data, f"<p>{form.message.data}</p>")
                flash(f"Announcement sent to {len(emails)} users.", "success")
        else:
            flash("Announcement published.", "success")

        return redirect(url_for("admin.announcements"))

    rows, _ = get_all_announcements(per_page=20)
    return render_template("admin/announcements.html", form=form, announcements=rows)


@admin_bp.route("/announcements/<int:ann_id>/toggle", methods=["POST"])
def toggle_announcement(ann_id):
    execute("UPDATE announcements SET is_active = 1 - is_active WHERE id=?", (ann_id,))
    flash("Announcement updated.", "success")
    return redirect(url_for("admin.announcements"))


# ── Settings ──────────────────────────────────────────────────────────────────

@admin_bp.route("/settings", methods=["GET", "POST"])
@super_admin_required
def settings():
    form = SystemSettingsForm()

    if form.validate_on_submit():
        set_setting("platform_name", form.platform_name.data)
        set_setting("maintenance_mode", "1" if form.maintenance_mode.data else "0")
        set_setting("registration_enabled", "1" if form.registration_enabled.data else "0")
        set_setting("default_storage_limit_mb", form.default_storage_limit_mb.data or "1024")
        set_setting("email_api_base", form.email_api_base.data or "")
        set_setting("turnstile_site_key", form.turnstile_site_key.data or "")
        set_setting("turnstile_secret_key", form.turnstile_secret_key.data or "")
        log("update_settings")
        flash("Settings saved.", "success")
        return redirect(url_for("admin.settings"))

    # Pre-fill form
    form.platform_name.data = get_setting("platform_name", "HostFlow")
    form.maintenance_mode.data = get_setting("maintenance_mode", "0") == "1"
    form.registration_enabled.data = get_setting("registration_enabled", "1") == "1"
    form.default_storage_limit_mb.data = get_setting("default_storage_limit_mb", "1024")
    form.email_api_base.data = get_setting("email_api_base", "")
    form.turnstile_site_key.data = get_setting("turnstile_site_key", "")
    form.turnstile_secret_key.data = get_setting("turnstile_secret_key", "")

    return render_template("admin/settings.html", form=form)


# ── Monitoring ────────────────────────────────────────────────────────────────

@admin_bp.route("/monitoring")
def monitoring():
    import shutil, psutil
    stats = get_platform_stats()

    disk = shutil.disk_usage("/")
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        mem_pct = mem.percent
        mem_used_gb = round(mem.used / (1024 ** 3), 2)
        mem_total_gb = round(mem.total / (1024 ** 3), 2)
    except Exception:
        cpu = 0
        mem_pct = 0
        mem_used_gb = 0
        mem_total_gb = 0

    from utils.database_manager import test_mysql_connection
    mysql_ok = test_mysql_connection()

    return render_template(
        "admin/monitoring.html",
        stats=stats,
        disk_total_gb=round(disk.total / (1024 ** 3), 1),
        disk_used_gb=round(disk.used / (1024 ** 3), 1),
        disk_pct=round((disk.used / disk.total) * 100, 1),
        cpu=cpu,
        mem_pct=mem_pct,
        mem_used_gb=mem_used_gb,
        mem_total_gb=mem_total_gb,
        mysql_ok=mysql_ok,
    )


# ── Security ──────────────────────────────────────────────────────────────────

@admin_bp.route("/security")
def security():
    recent_logins = query(
        """SELECT u.email, a.ip_address, a.created_at
           FROM activity_logs a JOIN users u ON a.user_id=u.id
           WHERE a.action='login'
           ORDER BY a.created_at DESC LIMIT 50"""
    )
    banned_users = query("SELECT * FROM users WHERE is_banned=1 ORDER BY created_at DESC")
    return render_template("admin/security.html",
                           recent_logins=recent_logins, banned_users=banned_users)
