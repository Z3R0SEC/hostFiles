"""
HostFlow — Sites Routes
Handles site creation, deployment, status, logs, and deletion.
"""

import os
import threading

from flask import (
    Blueprint, render_template, redirect, url_for, flash,
    session, request, jsonify, current_app
)
from werkzeug.utils import secure_filename

from routes import login_required
from utils.db import (
    get_user_by_id, get_site_by_user, get_site_by_id,
    create_site, update_site, create_deployment, get_deployment,
    get_site_deployments, log_activity
)
from utils.security import sanitise_subdomain, is_valid_subdomain, safe_join
from utils.validators import CreateSiteForm, UploadSiteForm
from utils.database_manager import provision_database
from utils.db import create_site_db_record, get_site_database
from utils.notifications import notify_deploy_success, notify_deploy_failed
from utils.activity_logger import log

sites_bp = Blueprint("sites", __name__)


def _require_site_owner(site_id):
    """Return (site, error_response). Validates ownership."""
    site = get_site_by_id(site_id)
    if not site:
        return None, ("Site not found.", 404)
    user_id = session["user_id"]
    user = get_user_by_id(user_id)
    if site["user_id"] != user_id and user["role"] not in ("admin", "super_admin"):
        return None, ("Access denied.", 403)
    return site, None


# ── Create Site ───────────────────────────────────────────────────────────────

@sites_bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    user = get_user_by_id(session["user_id"])
    existing = get_site_by_user(user["id"])
    if existing:
        flash("You already have a website. Upgrade for more sites.", "warning")
        return redirect(url_for("sites.manage", site_id=existing["id"]))

    form = CreateSiteForm()
    if form.validate_on_submit():
        name = form.name.data.strip()
        subdomain = sanitise_subdomain(name)

        # Ensure unique subdomain
        from utils.db import get_site_by_subdomain
        base = subdomain
        counter = 1
        while get_site_by_subdomain(subdomain):
            subdomain = f"{base}-{counter}"
            counter += 1

        deploy_path = os.path.join(
            current_app.config["USER_SITES_DIR"],
            str(user["id"]),
            subdomain,
        )
        os.makedirs(deploy_path, exist_ok=True)

        site_id = create_site(user["id"], name, subdomain, deploy_path)

        # Provision database (MySQL if available, else SQLite fallback)
        try:
            db_info = provision_database(site_id)
            if db_info["success"]:
                create_site_db_record(
                    site_id,
                    db_info["db_name"],
                    db_info["db_user"],
                    db_info["db_password"],
                    host=db_info.get("db_host", "localhost"),
                )
        except Exception as exc:
            current_app.logger.warning(f"DB provision skipped: {exc}")

        log("create_site", "site", site_id, f"Created site: {name}")
        flash(f'Site "{name}" created! Now upload your files.', "success")
        return redirect(url_for("sites.deploy", site_id=site_id))

    return render_template("sites/create.html", form=form)


# ── Deploy (upload ZIP) ───────────────────────────────────────────────────────

@sites_bp.route("/<int:site_id>/deploy", methods=["GET", "POST"])
@login_required
def deploy(site_id):
    site, err = _require_site_owner(site_id)
    if err:
        flash(err[0], "error")
        return redirect(url_for("dashboard.index"))

    form = UploadSiteForm()
    if form.validate_on_submit():
        f = form.zip_file.data
        filename = secure_filename(f.filename)
        if not filename.lower().endswith(".zip"):
            flash("Only ZIP files are accepted.", "error")
            return render_template("sites/deploy.html", site=site, form=form)

        upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], str(site_id))
        os.makedirs(upload_dir, exist_ok=True)
        zip_path = os.path.join(upload_dir, filename)
        f.save(zip_path)

        user = get_user_by_id(session["user_id"])
        dep_id = create_deployment(site_id, user["id"], filename)

        # Kick off background thread
        app = current_app._get_current_object()
        sid = request.form.get("socket_sid", "")

        def run():
            with app.app_context():
                from utils.deployment import run_deployment
                result = run_deployment(
                    dep_id, site_id, zip_path, site["deploy_path"],
                    user["email"], sid or None
                )
                if result["success"]:
                    notify_deploy_success(user["id"], site["name"], site_id)
                else:
                    notify_deploy_failed(user["id"], site["name"], site_id)

        t = threading.Thread(target=run, daemon=True)
        t.start()

        log("deploy", "site", site_id, f"Deployment #{dep_id} started")
        return redirect(url_for("sites.deploy_progress", site_id=site_id, dep_id=dep_id))

    return render_template("sites/deploy.html", site=site, form=form)


@sites_bp.route("/<int:site_id>/deploy/<int:dep_id>/progress")
@login_required
def deploy_progress(site_id, dep_id):
    site, err = _require_site_owner(site_id)
    if err:
        flash(err[0], "error")
        return redirect(url_for("dashboard.index"))
    dep = get_deployment(dep_id)
    return render_template("sites/deploy_progress.html", site=site, dep=dep, dep_id=dep_id)


@sites_bp.route("/<int:site_id>/deploy/<int:dep_id>/status")
@login_required
def deploy_status(site_id, dep_id):
    dep = get_deployment(dep_id)
    if not dep:
        return jsonify({"status": "not_found"})
    return jsonify({
        "status": dep["status"],
        "log": dep["log"] or "",
        "finished_at": dep["finished_at"],
    })


# ── Manage Site ───────────────────────────────────────────────────────────────

@sites_bp.route("/<int:site_id>")
@login_required
def manage(site_id):
    site, err = _require_site_owner(site_id)
    if err:
        flash(err[0], "error")
        return redirect(url_for("dashboard.index"))

    deps = get_site_deployments(site_id)
    db_info = get_site_database(site_id)
    # Build site URL dynamically from the current request host
    from flask import request as _req
    host = _req.host
    scheme = _req.scheme
    bare = host.split(":")[0]
    if bare in ("localhost", "127.0.0.1", "0.0.0.0"):
        port = (":" + host.split(":")[1]) if ":" in host else ""
        site_url = f"{scheme}://localhost{port}/preview/{site['subdomain']}"
    else:
        site_url = f"{scheme}://{site['subdomain']}.{bare}"

    return render_template(
        "sites/manage.html",
        site=site, deps=deps, db_info=db_info, site_url=site_url,
    )


# ── Delete Site ───────────────────────────────────────────────────────────────

@sites_bp.route("/<int:site_id>/delete", methods=["POST"])
@login_required
def delete(site_id):
    site, err = _require_site_owner(site_id)
    if err:
        flash(err[0], "error")
        return redirect(url_for("dashboard.index"))

    import shutil
    from utils.db import get_site_database
    from utils.database_manager import drop_database

    db_info = get_site_database(site_id)
    if db_info:
        try:
            drop_database(db_info["db_name"], db_info["db_user"])
        except Exception:
            pass

    if os.path.isdir(site["deploy_path"]):
        shutil.rmtree(site["deploy_path"], ignore_errors=True)

    from utils.db import execute
    execute("DELETE FROM sites WHERE id=?", (site_id,))
    log("delete_site", "site", site_id, f"Deleted site {site['name']}")
    flash("Site deleted successfully.", "info")
    return redirect(url_for("dashboard.index"))


# ── View Logs ─────────────────────────────────────────────────────────────────

@sites_bp.route("/<int:site_id>/logs")
@login_required
def view_logs(site_id):
    site, err = _require_site_owner(site_id)
    if err:
        flash(err[0], "error")
        return redirect(url_for("dashboard.index"))

    deps = get_site_deployments(site_id, limit=20)
    return render_template("sites/logs.html", site=site, deps=deps)


# ── Suspend / Activate (admin) ────────────────────────────────────────────────

@sites_bp.route("/<int:site_id>/toggle-status", methods=["POST"])
@login_required
def toggle_status(site_id):
    from routes import role_required
    user = get_user_by_id(session["user_id"])
    if user["role"] not in ("admin", "super_admin"):
        flash("Access denied.", "error")
        return redirect(url_for("dashboard.index"))

    site = get_site_by_id(site_id)
    if not site:
        flash("Site not found.", "error")
        return redirect(url_for("admin.sites"))

    new_status = "inactive" if site["status"] == "active" else "active"
    update_site(site_id, status=new_status)
    flash(f"Site status changed to {new_status}.", "success")
    return redirect(url_for("admin.sites"))
