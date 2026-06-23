import os
import logging
from logging.handlers import RotatingFileHandler

from flask import Flask, session, g, request, jsonify
from flask_session import Session
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO

from config import ActiveConfig

# ── Extensions (initialised without app) ─────────────────────────────────────
sess = Session()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)
socketio = SocketIO()


def create_app(config_class=ActiveConfig):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    # ── Ensure required directories exist ────────────────
    for d in [
        app.config["UPLOAD_FOLDER"],
        app.config["USER_SITES_DIR"],
        app.config["BACKUPS_DIR"],
        app.config["LOGS_DIR"],
        app.config["SESSION_FILE_DIR"],
        os.path.join(app.root_path, "instance"),
    ]:
        os.makedirs(d, exist_ok=True)

    # ── Init extensions ───────────────────────────────────
    sess.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    socketio.init_app(
       app,
       cors_allowed_origins="*",
       manage_session=False,
       async_mode="threading"
    )

    # ── Database bootstrap ────────────────────────────────
    from utils.db import init_db, seed_super_admin
    with app.app_context():
        init_db(app)
        seed_super_admin(app)

    # ── Register blueprints ───────────────────────────────
    from routes.public import public_bp, api_bp
    from routes.auth import auth_bp
    from routes.dashboard import dashboard_bp
    from routes.sites import sites_bp
    from routes.files import files_bp
    from routes.databases import databases_bp
    from routes.backups import backups_bp
    from routes.admin import admin_bp
#    from routes.api import api_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(sites_bp, url_prefix="/sites")
    app.register_blueprint(files_bp, url_prefix="/files")
    app.register_blueprint(databases_bp, url_prefix="/databases")
    app.register_blueprint(backups_bp, url_prefix="/backups")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp, url_prefix="/internal-api")

    # ── Security headers ──────────────────────────────────
    @app.after_request
    def set_security_headers(response):
        for key, val in app.config["SECURITY_HEADERS"].items():
            response.headers[key] = val
        return response

    # ── Maintenance mode ──────────────────────────────────
    @app.before_request
    def check_maintenance():
        from utils.db import get_setting
        maintenance = get_setting("maintenance_mode", "0") == "1"
        if maintenance:
            # Allow admin and localhost
            if request.path.startswith("/admin") or request.path.startswith("/auth"):
                return
            if request.remote_addr in ("127.0.0.1", "::1"):
                return
            from flask import render_template
            return render_template("errors/maintenance.html"), 503

    # ── Inject current user into templates ────────────────
    @app.context_processor
    def inject_user():
        import datetime
        from utils.db import get_user_by_id, get_setting
        user = None
        if "user_id" in session:
            user = get_user_by_id(session["user_id"])

        # Dynamic base URL — auto-detects host, works on localhost, VPS, Ngrok
        host = request.host       # "localhost:5000" or "example.com"
        scheme = request.scheme   # "http" or "https"
        base_url = f"{scheme}://{host}"
        bare_host = host.split(":")[0]

        def make_site_url(subdomain):
            """Live URL for a deployed site, adapts to current host automatically."""
            if bare_host in ("localhost", "127.0.0.1", "0.0.0.0"):
                port = (":" + host.split(":")[1]) if ":" in host else ""
                return f"{scheme}://localhost{port}/preview/{subdomain}"
            return f"{scheme}://{subdomain}.{bare_host}"

        return {
            "current_user": user,
            "platform_name": get_setting("platform_name", app.config["PLATFORM_NAME"]),
            "config": app.config,
            "now_year": datetime.datetime.utcnow().year,
            "request": request,
            "base_url": base_url,
            "request_host": host,
            "make_site_url": make_site_url,
        }

    # ── Error handlers ────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template
        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def forbidden(e):
        from flask import render_template
        return render_template("errors/403.html"), 403

    @app.errorhandler(500)
    def server_error(e):
        from flask import render_template
        return render_template("errors/500.html"), 500

    @app.errorhandler(429)
    def rate_limited(e):
        if request.is_json:
            return jsonify(error="Too many requests. Please slow down."), 429
        from flask import render_template
        return render_template("errors/429.html"), 429

    # ── SocketIO events ───────────────────────────────────
    from routes import socket_events  # noqa: F401

    # ── Logging ───────────────────────────────────────────
    if not app.debug:
        log_file = os.path.join(app.config["LOGS_DIR"], "platform.log")
        handler = RotatingFileHandler(log_file, maxBytes=10_485_760, backupCount=5)
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        )
        handler.setFormatter(formatter)
        app.logger.addHandler(handler)
        app.logger.setLevel(logging.INFO)

    return app
