"""
HostFlow — Database Routes
"""

from flask import (
    Blueprint, render_template, redirect, url_for, flash,
    session, request, jsonify, current_app
)
from routes import login_required
from utils.db import (
    get_user_by_id, get_site_by_user, get_site_by_id,
    get_site_database, update_user
)
from utils.database_manager import (
    reset_db_password, suspend_database, restore_database,
    execute_user_sql, get_db_tables, get_table_rows
)
from utils.notifications import notify_db_password_changed
from utils.activity_logger import log
from utils.db import execute

databases_bp = Blueprint("databases", __name__)


def _require_db_access(site_id):
    """Return (site, db_info, None) or (None, None, error_str)."""
    user = get_user_by_id(session["user_id"])
    site = get_site_by_id(site_id)
    if not site or (site["user_id"] != user["id"] and user["role"] not in ("admin", "super_admin")):
        return None, None, "Access denied."
    db_info = get_site_database(site_id)
    if not db_info:
        return site, None, "No database provisioned for this site yet."
    return site, db_info, None


# ── Credentials page ──────────────────────────────────────────────────────────

@databases_bp.route("/<int:site_id>")
@login_required
def info(site_id):
    user = get_user_by_id(session["user_id"])
    site = get_site_by_id(site_id)
    if not site or (site["user_id"] != user["id"] and user["role"] not in ("admin", "super_admin")):
        flash("Access denied.", "error")
        return redirect(url_for("dashboard.index"))

    db_info = get_site_database(site_id)
    return render_template("databases/info.html", site=site, db_info=db_info)


# ── SQL Manager ───────────────────────────────────────────────────────────────

@databases_bp.route("/<int:site_id>/manager")
@login_required
def manager(site_id):
    site, db_info, err = _require_db_access(site_id)
    if err:
        flash(err, "error")
        return redirect(url_for("dashboard.index"))

    tables = get_db_tables(db_info)
    return render_template(
        "databases/manager.html",
        site=site,
        db_info=db_info,
        tables=tables,
        query_result=None,
        query_error=None,
        last_sql="",
    )


@databases_bp.route("/<int:site_id>/manager/query", methods=["POST"])
@login_required
def run_query(site_id):
    site, db_info, err = _require_db_access(site_id)
    if err:
        flash(err, "error")
        return redirect(url_for("dashboard.index"))

    sql = request.form.get("sql", "").strip()
    tables = get_db_tables(db_info)

    if not sql:
        flash("No SQL provided.", "warning")
        return render_template(
            "databases/manager.html",
            site=site, db_info=db_info, tables=tables,
            query_result=None, query_error=None, last_sql="",
        )

    result, error = execute_user_sql(db_info, sql)
    log("sql_query", "site", site_id, f"SQL executed ({len(sql)} chars)")

    return render_template(
        "databases/manager.html",
        site=site, db_info=db_info, tables=tables,
        query_result=result,
        query_error=error,
        last_sql=sql,
    )


@databases_bp.route("/<int:site_id>/manager/import", methods=["POST"])
@login_required
def import_sql(site_id):
    site, db_info, err = _require_db_access(site_id)
    if err:
        flash(err, "error")
        return redirect(url_for("dashboard.index"))

    f = request.files.get("sql_file")
    if not f or not f.filename.endswith(".sql"):
        flash("Please upload a valid .sql file.", "error")
        return redirect(url_for("databases.manager", site_id=site_id))

    sql = f.read().decode("utf-8", errors="replace")
    result, error = execute_user_sql(db_info, sql, multi=True)

    if error:
        flash(f"Import error: {error}", "error")
    else:
        flash("SQL file imported successfully.", "success")

    log("sql_import", "site", site_id, f"Imported {f.filename}")
    return redirect(url_for("databases.manager", site_id=site_id))


@databases_bp.route("/<int:site_id>/manager/browse/<table_name>")
@login_required
def browse_table(site_id, table_name):
    site, db_info, err = _require_db_access(site_id)
    if err:
        flash(err, "error")
        return redirect(url_for("dashboard.index"))

    page = int(request.args.get("page", 1))
    limit = 50
    offset = (page - 1) * limit

    rows, columns, total, error = get_table_rows(db_info, table_name, limit=limit, offset=offset)
    tables = get_db_tables(db_info)

    return render_template(
        "databases/manager.html",
        site=site, db_info=db_info, tables=tables,
        browse_table=table_name,
        browse_rows=rows,
        browse_columns=columns,
        browse_total=total,
        browse_page=page,
        browse_limit=limit,
        browse_error=error,
        query_result=None, query_error=None, last_sql="",
    )


# ── Reset password ────────────────────────────────────────────────────────────

@databases_bp.route("/<int:site_id>/reset-password", methods=["POST"])
@login_required
def reset_password(site_id):
    user = get_user_by_id(session["user_id"])
    site = get_site_by_id(site_id)
    if not site or (site["user_id"] != user["id"] and user["role"] not in ("admin", "super_admin")):
        flash("Access denied.", "error")
        return redirect(url_for("dashboard.index"))

    db_info = get_site_database(site_id)
    if not db_info:
        flash("No database found.", "error")
        return redirect(url_for("databases.info", site_id=site_id))

    new_pwd = reset_db_password(db_info["db_user"])
    if new_pwd:
        execute(
            "UPDATE site_databases SET db_password=? WHERE site_id=?",
            (new_pwd, site_id)
        )
        notify_db_password_changed(user["id"], db_info["db_name"])
        log("reset_db_password", "site", site_id, db_info["db_name"])
        flash("Database password reset successfully.", "success")
    else:
        flash("Failed to reset database password.", "error")

    return redirect(url_for("databases.info", site_id=site_id))


# ── Suspend / Restore (admin) ─────────────────────────────────────────────────

@databases_bp.route("/<int:site_id>/suspend", methods=["POST"])
@login_required
def suspend(site_id):
    user = get_user_by_id(session["user_id"])
    if user["role"] not in ("admin", "super_admin"):
        flash("Access denied.", "error")
        return redirect(url_for("dashboard.index"))

    db_info = get_site_database(site_id)
    if db_info:
        suspend_database(db_info["db_name"], db_info["db_user"])
        execute("UPDATE site_databases SET status='suspended' WHERE site_id=?", (site_id,))
        flash("Database suspended.", "warning")
    return redirect(url_for("admin.databases"))


@databases_bp.route("/<int:site_id>/restore-db", methods=["POST"])
@login_required
def restore_db(site_id):
    user = get_user_by_id(session["user_id"])
    if user["role"] not in ("admin", "super_admin"):
        flash("Access denied.", "error")
        return redirect(url_for("dashboard.index"))

    db_info = get_site_database(site_id)
    if db_info:
        restore_database(db_info["db_name"], db_info["db_user"])
        execute("UPDATE site_databases SET status='active' WHERE site_id=?", (site_id,))
        flash("Database restored.", "success")
    return redirect(url_for("admin.databases"))
