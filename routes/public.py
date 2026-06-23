"""
HostFlow — Public Pages + Internal API Routes
"""

from flask import Blueprint, render_template, jsonify, session, request
from utils.db import get_user_notifications, get_unread_count, mark_all_read, mark_notification_read

public_bp = Blueprint("public", __name__)
api_bp = Blueprint("api", __name__)


# ── Public pages ──────────────────────────────────────────────────────────────

@public_bp.route("/")
def home():
    from utils.db import get_platform_stats
    stats = get_platform_stats()
    return render_template("public/home.html", stats=stats)


@public_bp.route("/features")
def features():
    return render_template("public/features.html")


@public_bp.route("/pricing")
def pricing():
    return render_template("public/pricing.html")


@public_bp.route("/terms")
def terms():
    return render_template("public/terms.html")


@public_bp.route("/privacy")
def privacy():
    return render_template("public/privacy.html")


@public_bp.route("/contact")
def contact():
    return render_template("public/contact.html")


# ── Internal API ──────────────────────────────────────────────────────────────

@api_bp.route("/notifications")
def notifications():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user_id = session["user_id"]
    notifs = get_user_notifications(user_id, limit=20)
    unread = get_unread_count(user_id)
    return jsonify({
        "notifications": [dict(n) for n in notifs],
        "unread": unread,
    })


@api_bp.route("/notifications/mark-all-read", methods=["POST"])
def mark_all():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    mark_all_read(session["user_id"])
    return jsonify({"success": True})


@api_bp.route("/deployment/<int:dep_id>/status")
def dep_status(dep_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    from utils.db import get_deployment
    dep = get_deployment(dep_id)
    if not dep:
        return jsonify({"status": "not_found"}), 404
    return jsonify({"status": dep["status"], "log": dep["log"] or ""})


# ── Localhost Site Preview ─────────────────────────────────────────────────────
# On localhost, subdomains don't work. This route serves site files by path.
# URL: /preview/<subdomain>/path/to/file.php

@public_bp.route("/preview/<subdomain>", defaults={"filepath": "index.php"})
@public_bp.route("/preview/<subdomain>/", defaults={"filepath": "index.php"})
@public_bp.route("/preview/<subdomain>/<path:filepath>")
def site_preview(subdomain, filepath):
    """
    Serve a deployed site's files for localhost development.
    On a real domain, Nginx handles this via subdomain routing.
    """
    import os
    from flask import send_from_directory, abort, current_app
    from utils.db import get_site_by_subdomain

    site = get_site_by_subdomain(subdomain)
    if not site:
        abort(404)

    deploy_path = site["deploy_path"] if "deploy_path" in site.keys() else ""
    if not deploy_path or not os.path.isdir(deploy_path):
        return (
            "<h2 style='font-family:sans-serif;color:#f87171;padding:2rem'>"
            "Site not deployed yet. Upload a ZIP file first.</h2>"
        ), 404

    # Prevent path traversal
    safe_path = os.path.realpath(os.path.join(deploy_path, filepath))
    if not safe_path.startswith(os.path.realpath(deploy_path)):
        abort(403)

    # If it's a directory, try index files
    if os.path.isdir(safe_path):
        for idx in ("index.php", "index.html", "index.htm"):
            candidate = os.path.join(safe_path, idx)
            if os.path.isfile(candidate):
                safe_path = candidate
                filepath = os.path.join(filepath, idx)
                break

    if not os.path.isfile(safe_path):
        # Try appending .html
        if os.path.isfile(safe_path + ".html"):
            safe_path += ".html"
            filepath += ".html"
        else:
            abort(404)

    # PHP files: note — on localhost without PHP-FPM they serve as plaintext
    # On a real server with Nginx+PHP-FPM this is handled by Nginx directly
    ext = os.path.splitext(safe_path)[1].lower()
    if ext == ".php":
        # Try to execute via PHP CLI if available
        import subprocess
        try:
            env = os.environ.copy()
            env["DOCUMENT_ROOT"] = deploy_path
            result = subprocess.run(
                ["php", safe_path],
                capture_output=True, text=True, timeout=10, env=env
            )
            html = result.stdout
            if not html:
                html = result.stderr or "<p>PHP file returned no output.</p>"
            return html, 200, {"Content-Type": "text/html; charset=utf-8"}
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # PHP not installed — serve source with a warning banner
            with open(safe_path, "r", errors="replace") as fh:
                src = fh.read()
            banner = (
                "<div style='background:#1c1c1f;color:#facc15;font-family:monospace;"
                "padding:12px 16px;font-size:13px;border-bottom:1px solid #333'>"
                "&#9888; PHP not installed — showing source. "
                "Install PHP CLI (<code>pkg install php</code> on Termux) to run this file."
                "</div>"
            )
            return (
                banner + f"<pre style='padding:1rem;background:#0d0d0f;color:#a1a1aa;"
                f"font-size:13px;margin:0'>{src}</pre>"
            ), 200

    return send_from_directory(deploy_path, os.path.relpath(safe_path, deploy_path))
