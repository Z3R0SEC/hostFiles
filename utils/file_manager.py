"""
HostFlow — File Manager Utility
Safe file operations within a site's deploy directory.
"""

import os
import shutil
import zipfile
import mimetypes
from pathlib import Path

from utils.security import safe_join
from flask import current_app


EDITABLE_EXTENSIONS = {
    "php", "html", "htm", "css", "js", "json", "txt",
    "xml", "svg", "md", "htaccess", "env.example", "ini",
}

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "svg", "ico"}
BINARY_EXTENSIONS = {"pdf", "zip", "tar", "gz", "woff", "woff2", "ttf", "eot"}


def get_site_dir(site) -> str:
    """Return the absolute deploy path for a site dict/Row."""
    return site["deploy_path"]


def list_directory(site_dir: str, rel_path: str = "") -> dict | None:
    """
    List contents of a directory within the site.
    Returns dict with files and folders, or None on traversal.
    """
    target = safe_join(site_dir, rel_path) if rel_path else site_dir
    if target is None or not os.path.isdir(target):
        return None

    entries = {"folders": [], "files": [], "current": rel_path, "parent": None}

    if rel_path:
        entries["parent"] = str(Path(rel_path).parent) if "/" in rel_path else ""

    try:
        for name in sorted(os.listdir(target)):
            full = os.path.join(target, name)
            rel = os.path.join(rel_path, name) if rel_path else name
            stat = os.stat(full)
            if os.path.isdir(full):
                entries["folders"].append({"name": name, "rel": rel})
            else:
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                entries["files"].append({
                    "name": name,
                    "rel": rel,
                    "ext": ext,
                    "size": stat.st_size,
                    "size_human": _human_size(stat.st_size),
                    "editable": ext in EDITABLE_EXTENSIONS,
                    "is_image": ext in IMAGE_EXTENSIONS,
                    "mtime": stat.st_mtime,
                })
    except PermissionError:
        return None

    return entries


def read_file(site_dir: str, rel_path: str) -> str | None:
    target = safe_join(site_dir, rel_path)
    if target is None or not os.path.isfile(target):
        return None
    ext = rel_path.rsplit(".", 1)[-1].lower() if "." in rel_path else ""
    if ext not in EDITABLE_EXTENSIONS:
        return None
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None


def write_file(site_dir: str, rel_path: str, content: str) -> bool:
    target = safe_join(site_dir, rel_path)
    if target is None:
        return False
    os.makedirs(os.path.dirname(target), exist_ok=True)
    try:
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception:
        return False


def create_folder(site_dir: str, rel_path: str) -> bool:
    target = safe_join(site_dir, rel_path)
    if target is None:
        return False
    try:
        os.makedirs(target, exist_ok=True)
        return True
    except Exception:
        return False


def rename_entry(site_dir: str, old_rel: str, new_name: str) -> bool:
    old = safe_join(site_dir, old_rel)
    parent = os.path.dirname(old_rel)
    new_rel = os.path.join(parent, new_name) if parent else new_name
    new = safe_join(site_dir, new_rel)
    if old is None or new is None:
        return False
    try:
        os.rename(old, new)
        return True
    except Exception:
        return False


def delete_entry(site_dir: str, rel_path: str) -> bool:
    target = safe_join(site_dir, rel_path)
    if target is None:
        return False
    try:
        if os.path.isdir(target):
            shutil.rmtree(target)
        else:
            os.remove(target)
        return True
    except Exception:
        return False


def save_upload(site_dir: str, rel_dir: str, filename: str, file_storage) -> bool:
    """Save a Werkzeug FileStorage object into rel_dir."""
    target_dir = safe_join(site_dir, rel_dir) if rel_dir else site_dir
    if target_dir is None:
        return False
    os.makedirs(target_dir, exist_ok=True)
    dest = os.path.join(target_dir, filename)
    try:
        file_storage.save(dest)
        return True
    except Exception:
        return False


def zip_directory(site_dir: str, rel_path: str, zip_dest: str) -> bool:
    """ZIP a subdirectory (or the whole site) and write to zip_dest."""
    target = safe_join(site_dir, rel_path) if rel_path else site_dir
    if target is None or not os.path.exists(target):
        return False
    try:
        with zipfile.ZipFile(zip_dest, "w", zipfile.ZIP_DEFLATED) as zf:
            if os.path.isfile(target):
                zf.write(target, os.path.basename(target))
            else:
                for root, dirs, files in os.walk(target):
                    for fname in files:
                        full = os.path.join(root, fname)
                        arc = os.path.relpath(full, target)
                        zf.write(full, arc)
        return True
    except Exception:
        return False


def get_dir_size_mb(path: str) -> float:
    total = 0
    for root, _, files in os.walk(path):
        for fname in files:
            try:
                total += os.path.getsize(os.path.join(root, fname))
            except OSError:
                pass
    return round(total / (1024 * 1024), 2)


def search_files(site_dir: str, query: str) -> list:
    results = []
    query_lower = query.lower()
    for root, dirs, files in os.walk(site_dir):
        for fname in files:
            if query_lower in fname.lower():
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, site_dir)
                stat = os.stat(full)
                ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
                results.append({
                    "name": fname,
                    "rel": rel,
                    "ext": ext,
                    "size_human": _human_size(stat.st_size),
                    "editable": ext in EDITABLE_EXTENSIONS,
                })
                if len(results) >= 100:
                    return results
    return results


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
