"""
HostFlow — Backups Routes
"""

import os
from flask import Blueprint, render_template, redirect, url_for, flash, session, send_file
from routes import login_required
from utils.db import (
    get_user_by_id, get_site_by_id, get_site_backups,
    create_backup_record, get_backup_by_id, delete_backup_record, update_site
)
from utils.backup import create_backup, restore_backup, get_backup_path, delete_backup_file
from utils.notifications import notify_backup_done
from utils.activity_logger import log

backups_bp = Blueprint("backups", __name__)


def _check_access(site_id):
    user = get_user_by_id(session["user_id"])
    site = get_site_by_id(site_id)
    if not site or (site["user_id"] != user["id"] and user["role"] not in ("admin", "super_admin")):
        return None, None
    return site, user


@backups_bp.route("/<int:site_id>")
@login_required
def list_backups(site_id):
    site, user = _check_access(site_id)
    if not site:
        flash("Access denied.", "error")
        return redirect(url_for("dashboard.index"))

    bkps = get_site_backups(site_id)
    return render_template("backups/list.html", site=site, backups=bkps)


@backups_bp.route("/<int:site_id>/create", methods=["POST"])
@login_required
def create(site_id):
    site, user = _check_access(site_id)
    if not site:
        flash("Access denied.", "error")
        return redirect(url_for("dashboard.index"))

    result = create_backup(site_id, site["name"], site["deploy_path"])
    if result["success"]:
        create_backup_record(site_id, result["filename"], result["size_mb"])
        update_site(site_id, last_backed_up="datetime('now')")
        notify_backup_done(user["id"], site["name"], site_id)
        log("create_backup", "site", site_id, result["filename"])
        flash("Backup created successfully.", "success")
    else:
        flash(f"Backup failed: {result['error']}", "error")

    return redirect(url_for("backups.list_backups", site_id=site_id))


@backups_bp.route("/<int:site_id>/download/<int:backup_id>")
@login_required
def download(site_id, backup_id):
    site, user = _check_access(site_id)
    if not site:
        flash("Access denied.", "error")
        return redirect(url_for("dashboard.index"))

    backup = get_backup_by_id(backup_id)
    if not backup or backup["site_id"] != site_id:
        flash("Backup not found.", "error")
        return redirect(url_for("backups.list_backups", site_id=site_id))

    path = get_backup_path(site_id, backup["filename"])
    if not path:
        flash("Backup file not found.", "error")
        return redirect(url_for("backups.list_backups", site_id=site_id))

    return send_file(path, as_attachment=True, download_name=backup["filename"])


@backups_bp.route("/<int:site_id>/restore/<int:backup_id>", methods=["POST"])
@login_required
def restore(site_id, backup_id):
    site, user = _check_access(site_id)
    if not site:
        flash("Access denied.", "error")
        return redirect(url_for("dashboard.index"))

    backup = get_backup_by_id(backup_id)
    if not backup or backup["site_id"] != site_id:
        flash("Backup not found.", "error")
        return redirect(url_for("backups.list_backups", site_id=site_id))

    result = restore_backup(site_id, backup["filename"], site["deploy_path"])
    if result["success"]:
        log("restore_backup", "site", site_id, backup["filename"])
        flash("Backup restored successfully.", "success")
    else:
        flash(f"Restore failed: {result['error']}", "error")

    return redirect(url_for("sites.manage", site_id=site_id))


@backups_bp.route("/<int:site_id>/delete/<int:backup_id>", methods=["POST"])
@login_required
def delete(site_id, backup_id):
    site, user = _check_access(site_id)
    if not site:
        flash("Access denied.", "error")
        return redirect(url_for("dashboard.index"))

    backup = get_backup_by_id(backup_id)
    if not backup or backup["site_id"] != site_id:
        flash("Backup not found.", "error")
        return redirect(url_for("backups.list_backups", site_id=site_id))

    delete_backup_file(site_id, backup["filename"])
    delete_backup_record(backup_id)
    log("delete_backup", "site", site_id, backup["filename"])
    flash("Backup deleted.", "info")
    return redirect(url_for("backups.list_backups", site_id=site_id))
