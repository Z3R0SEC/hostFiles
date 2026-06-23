"""
HostFlow — Backup Utility
Creates and restores ZIP backups of site files.
"""

import os
import shutil
import zipfile
from datetime import datetime

from flask import current_app
from utils.file_manager import get_dir_size_mb


def create_backup(site_id: int, site_name: str, deploy_path: str) -> dict:
    """
    ZIP the site's deploy directory and store in the backups folder.
    Returns {success, filename, size_mb, error}.
    """
    if not os.path.isdir(deploy_path):
        return {"success": False, "filename": None, "size_mb": 0, "error": "Site directory not found."}

    backups_dir = os.path.join(
        current_app.config["BACKUPS_DIR"], str(site_id)
    )
    os.makedirs(backups_dir, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c if c.isalnum() else "_" for c in site_name)
    filename = f"{safe_name}_{timestamp}.zip"
    zip_path = os.path.join(backups_dir, filename)

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(deploy_path):
                for fname in files:
                    full = os.path.join(root, fname)
                    arc = os.path.relpath(full, deploy_path)
                    zf.write(full, arc)

        size_mb = round(os.path.getsize(zip_path) / (1024 * 1024), 2)
        return {"success": True, "filename": filename, "size_mb": size_mb, "error": None}

    except Exception as exc:
        return {"success": False, "filename": None, "size_mb": 0, "error": str(exc)}


def restore_backup(site_id: int, filename: str, deploy_path: str) -> dict:
    """
    Extract a backup ZIP back into the deploy directory.
    Returns {success, error}.
    """
    backups_dir = os.path.join(current_app.config["BACKUPS_DIR"], str(site_id))
    zip_path = os.path.join(backups_dir, filename)

    if not os.path.isfile(zip_path):
        return {"success": False, "error": "Backup file not found."}

    if not zipfile.is_zipfile(zip_path):
        return {"success": False, "error": "Invalid ZIP archive."}

    tmp = deploy_path + "_restore_tmp"
    if os.path.exists(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp, exist_ok=True)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            # Zip-Slip check
            for member in zf.infolist():
                target = os.path.realpath(os.path.join(tmp, member.filename))
                if not target.startswith(os.path.realpath(tmp)):
                    shutil.rmtree(tmp, ignore_errors=True)
                    return {"success": False, "error": "Zip-Slip detected in backup."}
            zf.extractall(tmp)

        # Replace deploy dir
        if os.path.exists(deploy_path):
            shutil.rmtree(deploy_path)
        shutil.move(tmp, deploy_path)

        return {"success": True, "error": None}

    except Exception as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        return {"success": False, "error": str(exc)}


def get_backup_path(site_id: int, filename: str) -> str | None:
    """Return the full path to a backup file, or None if it doesn't exist."""
    path = os.path.join(current_app.config["BACKUPS_DIR"], str(site_id), filename)
    return path if os.path.isfile(path) else None


def delete_backup_file(site_id: int, filename: str) -> bool:
    path = os.path.join(current_app.config["BACKUPS_DIR"], str(site_id), filename)
    try:
        if os.path.isfile(path):
            os.remove(path)
        return True
    except Exception:
        return False
