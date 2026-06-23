"""
HostFlow — Deployment Utility
Handles ZIP validation, extraction, Zip-Slip prevention, and site deployment.
Emits SocketIO progress events during each stage.
"""

import os
import re
import shutil
import zipfile
from pathlib import Path

from flask import current_app


BLOCKED_EXTENSIONS = {
    "exe", "sh", "bash", "bat", "cmd", "py", "rb", "pl", "cgi",
    "jar", "class", "dll", "so", "dylib", "phar",
}
ALLOWED_EXTENSIONS = {
    "php", "html", "htm", "css", "js", "json", "xml", "svg",
    "png", "jpg", "jpeg", "gif", "webp", "ico", "woff", "woff2",
    "ttf", "eot", "otf", "pdf", "txt", "md", "csv", "htaccess",
    "map", "mp4", "mp3", "ogg", "webm", "zip",
}
MAX_ZIP_MEMBERS = 5000
MAX_UNCOMPRESSED_MB = 900


def emit(sid, event, data):
    """Emit SocketIO event if possible."""
    try:
        from app import socketio
        socketio.emit(event, data, room=sid)
    except Exception:
        pass


def run_deployment(deployment_id: int, site_id: int, zip_path: str, deploy_path: str,
                   user_email: str, socket_sid: str | None = None) -> dict:
    """
    Full deployment pipeline. Returns {"success": bool, "log": str, "entry": str|None}.
    """
    from utils.db import update_deployment, update_site, create_notification
    from utils.db import get_site_by_id
    import sqlite3

    log_lines = []

    def step(msg, stage=None):
        log_lines.append(msg)
        if socket_sid and stage:
            emit(socket_sid, "deploy_progress", {"stage": stage, "msg": msg})

    def fail(msg):
        log_lines.append(f"ERROR: {msg}")
        if socket_sid:
            emit(socket_sid, "deploy_progress", {"stage": "error", "msg": msg})
        full_log = "\n".join(log_lines)
        # Use a fresh connection to avoid closed-db issues in thread
        _update_deployment_direct(deployment_id, "failed", full_log)
        _update_site_direct(site_id, status="inactive")
        return {"success": False, "log": full_log, "entry": None}

    step("Starting deployment…", "uploading")

    # ── 1. Validate ZIP ───────────────────────────────────
    step("Validating archive…", "validating")
    if not zipfile.is_zipfile(zip_path):
        return fail("Uploaded file is not a valid ZIP archive.")

    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.infolist()
        if len(members) > MAX_ZIP_MEMBERS:
            return fail(f"ZIP contains too many files ({len(members)} > {MAX_ZIP_MEMBERS}).")

        total_uncompressed = sum(m.file_size for m in members)
        if total_uncompressed > MAX_UNCOMPRESSED_MB * 1024 * 1024:
            return fail(f"Uncompressed size exceeds {MAX_UNCOMPRESSED_MB} MB.")

        # Zip-Slip check + filename validation
        for member in members:
            name = member.filename

            # Zip-Slip: reject absolute paths or paths with ..
            if os.path.isabs(name) or ".." in name.split("/"):
                return fail(f"Dangerous path detected in archive: {name}")

            # Check extension
            if "." in os.path.basename(name):
                ext = name.rsplit(".", 1)[-1].lower()
                if ext in BLOCKED_EXTENSIONS:
                    return fail(f"Blocked file type in archive: {name}")

        step(f"Archive OK — {len(members)} files, "
             f"{round(total_uncompressed / 1024 / 1024, 1)} MB uncompressed.", "validating")

    # ── 2. Extract ────────────────────────────────────────
    step("Extracting files…", "extracting")
    tmp_extract = deploy_path + "_tmp"
    if os.path.exists(tmp_extract):
        shutil.rmtree(tmp_extract)
    os.makedirs(tmp_extract, exist_ok=True)

    try:
        tmp_extract_real = os.path.realpath(tmp_extract)
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                # Skip directories — makedirs handles them
                if member.filename.endswith("/"):
                    continue
                # Safe extraction path
                target = os.path.realpath(os.path.join(tmp_extract, member.filename))
                if not target.startswith(tmp_extract_real + os.sep) and target != tmp_extract_real:
                    shutil.rmtree(tmp_extract)
                    return fail("Zip-Slip attack detected — aborting.")
                # Ensure parent directory exists
                os.makedirs(os.path.dirname(target), exist_ok=True)
                # Extract single file with size limit guard
                with zf.open(member) as src, open(target, "wb") as dst:
                    written = 0
                    while True:
                        chunk = src.read(65536)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > MAX_UNCOMPRESSED_MB * 1024 * 1024:
                            shutil.rmtree(tmp_extract, ignore_errors=True)
                            return fail("Extraction exceeded size limit — aborting.")
                        dst.write(chunk)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(tmp_extract, ignore_errors=True)
        return fail(f"Corrupt ZIP archive: {exc}")
    except Exception as exc:
        shutil.rmtree(tmp_extract, ignore_errors=True)
        return fail(f"Extraction failed: {exc}")

    # ── 3. Flatten single-folder zip ─────────────────────
    extracted_root = _find_root(tmp_extract)
    step(f"Extracted to {extracted_root}", "extracting")

    # ── 4. Detect entry file ──────────────────────────────
    step("Scanning for entry file…", "validating")
    entry_file = None
    php_enabled = False

    if os.path.isfile(os.path.join(extracted_root, "index.php")):
        entry_file = "index.php"
        php_enabled = True
        step("Detected entry: index.php — PHP mode enabled.", "validating")
    elif os.path.isfile(os.path.join(extracted_root, "index.html")):
        entry_file = "index.html"
        step("Detected entry: index.html — static mode.", "validating")
    else:
        files_found = _list_top_files(extracted_root)
        step(f"No index.php or index.html found. Files: {', '.join(files_found[:10])}", "validating")

    # ── 5. Deploy ─────────────────────────────────────────
    step("Deploying files…", "deploying")
    if os.path.exists(deploy_path):
        shutil.rmtree(deploy_path)
    shutil.move(extracted_root, deploy_path)

    # Clean up tmp
    shutil.rmtree(tmp_extract, ignore_errors=True)

    step("Deployment complete!", "done")
    full_log = "\n".join(log_lines)

    _update_deployment_direct(deployment_id, "success", full_log)
    _update_site_direct(
        site_id,
        status="active",
        php_enabled=1 if php_enabled else 0,
        entry_file=entry_file or "",
        deployed_at="datetime('now')",
    )

    if socket_sid:
        emit(socket_sid, "deploy_done", {"success": True, "entry": entry_file})

    return {"success": True, "log": full_log, "entry": entry_file}


def _find_root(extract_dir: str) -> str:
    """If the ZIP contained a single top-level folder, return it; else return extract_dir."""
    items = os.listdir(extract_dir)
    if len(items) == 1 and os.path.isdir(os.path.join(extract_dir, items[0])):
        return os.path.join(extract_dir, items[0])
    return extract_dir


def _list_top_files(path: str) -> list:
    result = []
    for name in os.listdir(path):
        result.append(name)
        if len(result) >= 20:
            break
    return result


def _update_deployment_direct(deployment_id, status, log):
    """Update deployment using a direct SQLite connection (thread-safe)."""
    import sqlite3
    from flask import current_app
    db_path = current_app.config["SQLITE_PATH"]
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE deployments SET status=?, log=?, finished_at=datetime('now') WHERE id=?",
        (status, log, deployment_id),
    )
    conn.commit()
    conn.close()


def _update_site_direct(site_id, **kwargs):
    import sqlite3
    from flask import current_app
    db_path = current_app.config["SQLITE_PATH"]
    conn = sqlite3.connect(db_path)
    # Handle literal SQL for deployed_at
    sets = []
    vals = []
    for k, v in kwargs.items():
        if v == "datetime('now')":
            sets.append(f"{k}=datetime('now')")
        else:
            sets.append(f"{k}=?")
            vals.append(v)
    if sets:
        conn.execute(
            f"UPDATE sites SET {', '.join(sets)} WHERE id=?",
            (*vals, site_id),
        )
    conn.commit()
    conn.close()
