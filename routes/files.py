"""
HostFlow — File Manager Routes
"""

import os
from flask import (
    Blueprint, render_template, redirect, url_for, flash, session,
    request, jsonify, send_file, current_app
)
from werkzeug.utils import secure_filename

from routes import login_required
from utils.db import get_site_by_user, get_site_by_id, get_user_by_id
from utils.file_manager import (
    list_directory, read_file, write_file, create_folder,
    rename_entry, delete_entry, save_upload, zip_directory,
    search_files, get_dir_size_mb
)
from utils.activity_logger import log

files_bp = Blueprint("files", __name__)


def _get_site(site_id=None):
    user_id = session["user_id"]
    user = get_user_by_id(user_id)
    if site_id:
        site = get_site_by_id(site_id)
        if not site:
            return None, None
        if site["user_id"] != user_id and user["role"] not in ("admin", "super_admin"):
            return None, None
    else:
        site = get_site_by_user(user_id)
    return site, user


@files_bp.route("/<int:site_id>/")
@files_bp.route("/<int:site_id>/<path:rel_path>")
@login_required
def browse(site_id, rel_path=""):
    site, user = _get_site(site_id)
    if not site:
        flash("Site not found.", "error")
        return redirect(url_for("dashboard.index"))
    if not os.path.isdir(site["deploy_path"]):
        flash("No files deployed yet.", "warning")
        return redirect(url_for("sites.manage", site_id=site_id))

    query = request.args.get("q", "")
    if query:
        results = search_files(site["deploy_path"], query)
        return render_template("files/browse.html", site=site, entries=None,
                               search_results=results, query=query, rel_path=rel_path)

    entries = list_directory(site["deploy_path"], rel_path)
    if entries is None:
        flash("Directory not found.", "error")
        return redirect(url_for("files.browse", site_id=site_id))

    storage_mb = get_dir_size_mb(site["deploy_path"])
    from utils.db import update_site
    update_site(site_id, storage_used_mb=storage_mb)

    return render_template("files/browse.html", site=site, entries=entries,
                           search_results=None, query="", rel_path=rel_path,
                           storage_mb=storage_mb)


@files_bp.route("/<int:site_id>/edit/<path:rel_path>", methods=["GET", "POST"])
@login_required
def edit(site_id, rel_path):
    site, user = _get_site(site_id)
    if not site:
        flash("Site not found.", "error")
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        data = request.get_json(silent=True)
        content = (data or {}).get("content", "")
        if write_file(site["deploy_path"], rel_path, content):
            log("edit_file", "site", site_id, rel_path)
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Write failed"}), 400

    content = read_file(site["deploy_path"], rel_path)
    if content is None:
        flash("File not found or not editable.", "error")
        return redirect(url_for("files.browse", site_id=site_id))

    ext = rel_path.rsplit(".", 1)[-1].lower() if "." in rel_path else "txt"
    lang_map = {
        "php": "php", "html": "html", "htm": "html", "css": "css",
        "js": "javascript", "json": "json", "txt": "plaintext",
        "xml": "xml", "svg": "xml", "md": "markdown",
    }
    language = lang_map.get(ext, "plaintext")

    return render_template("files/editor.html", site=site, rel_path=rel_path,
                           content=content, language=language)


@files_bp.route("/<int:site_id>/upload", methods=["POST"])
@login_required
def upload(site_id):
    site, user = _get_site(site_id)
    if not site:
        return jsonify({"success": False, "error": "Site not found"}), 404

    rel_dir = request.form.get("rel_dir", "")
    files = request.files.getlist("files")
    errors = []
    saved = 0

    for f in files:
        name = secure_filename(f.filename)
        if not name:
            continue
        if save_upload(site["deploy_path"], rel_dir, name, f):
            saved += 1
            log("upload_file", "site", site_id, os.path.join(rel_dir, name))
        else:
            errors.append(name)

    # Update storage
    storage_mb = get_dir_size_mb(site["deploy_path"])
    from utils.db import update_site
    update_site(site_id, storage_used_mb=storage_mb)

    return jsonify({"success": True, "saved": saved, "errors": errors})


@files_bp.route("/<int:site_id>/mkdir", methods=["POST"])
@login_required
def mkdir(site_id):
    site, user = _get_site(site_id)
    if not site:
        return jsonify({"success": False}), 404

    data = request.get_json(silent=True) or {}
    rel_path = data.get("path", "")
    if create_folder(site["deploy_path"], rel_path):
        log("create_folder", "site", site_id, rel_path)
        return jsonify({"success": True})
    return jsonify({"success": False}), 400


@files_bp.route("/<int:site_id>/rename", methods=["POST"])
@login_required
def rename(site_id):
    site, user = _get_site(site_id)
    if not site:
        return jsonify({"success": False}), 404

    data = request.get_json(silent=True) or {}
    old = data.get("old", "")
    new = secure_filename(data.get("new", ""))
    if not new:
        return jsonify({"success": False, "error": "Invalid name"}), 400

    if rename_entry(site["deploy_path"], old, new):
        log("rename_file", "site", site_id, f"{old} → {new}")
        return jsonify({"success": True})
    return jsonify({"success": False}), 400


@files_bp.route("/<int:site_id>/delete-file", methods=["POST"])
@login_required
def delete_file(site_id):
    site, user = _get_site(site_id)
    if not site:
        return jsonify({"success": False}), 404

    data = request.get_json(silent=True) or {}
    rel = data.get("path", "")
    if delete_entry(site["deploy_path"], rel):
        log("delete_file", "site", site_id, rel)
        return jsonify({"success": True})
    return jsonify({"success": False}), 400


@files_bp.route("/<int:site_id>/download/<path:rel_path>")
@login_required
def download(site_id, rel_path):
    site, user = _get_site(site_id)
    if not site:
        flash("Site not found.", "error")
        return redirect(url_for("dashboard.index"))

    from utils.security import safe_join
    full = safe_join(site["deploy_path"], rel_path)
    if full is None or not os.path.isfile(full):
        flash("File not found.", "error")
        return redirect(url_for("files.browse", site_id=site_id))

    return send_file(full, as_attachment=True, download_name=os.path.basename(rel_path))


@files_bp.route("/<int:site_id>/download-zip")
@login_required
def download_zip(site_id):
    site, user = _get_site(site_id)
    if not site:
        flash("Site not found.", "error")
        return redirect(url_for("dashboard.index"))

    rel = request.args.get("path", "")
    import tempfile
    tmp = tempfile.mktemp(suffix=".zip")
    if zip_directory(site["deploy_path"], rel, tmp):
        fname = os.path.basename(rel) + ".zip" if rel else f"{site['subdomain']}.zip"
        return send_file(tmp, as_attachment=True, download_name=fname)
    flash("Could not create ZIP.", "error")
    return redirect(url_for("files.browse", site_id=site_id))
