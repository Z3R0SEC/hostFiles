"""
HostFlow — Database Manager
Handles database provisioning for customer sites.

MODES:
  1. MariaDB/MySQL mode  — requires MYSQL_ROOT_PASSWORD set in .env
                           Provisions real separate databases per site.

  2. SQLite mode (default) — zero config, works immediately on localhost/Termux.
                             Each site gets its own SQLite file inside their
                             deploy folder. Perfect for development/small sites.

The mode is chosen automatically: if MySQL root credentials are set AND the
server is reachable, MySQL mode is used. Otherwise SQLite mode is used.
"""

import os
import re
import sqlite3
from flask import current_app


# ── Connection helpers ────────────────────────────────────────────────────────

def _mysql_available() -> bool:
    """Return True if MySQL root credentials are configured AND the server answers."""
    cfg = current_app.config
    if not cfg.get("MYSQL_ROOT_PASSWORD"):
        return False
    try:
        import pymysql
        conn = pymysql.connect(
            host=cfg["MYSQL_HOST"],
            port=cfg["MYSQL_PORT"],
            user=cfg["MYSQL_ROOT_USER"],
            password=cfg["MYSQL_ROOT_PASSWORD"],
            charset=cfg["MYSQL_CHARSET"],
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:
        return False


def _root_conn():
    """Open a MySQL root connection. Raises if not configured."""
    import pymysql
    cfg = current_app.config
    return pymysql.connect(
        host=cfg["MYSQL_HOST"],
        port=cfg["MYSQL_PORT"],
        user=cfg["MYSQL_ROOT_USER"],
        password=cfg["MYSQL_ROOT_PASSWORD"],
        charset=cfg["MYSQL_CHARSET"],
        autocommit=True,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def provision_database(site_id: int) -> dict:
    """
    Provision a database for the given site.
    Tries MySQL first; falls back to SQLite automatically.
    """
    if _mysql_available():
        return _provision_mysql(site_id)
    return _provision_sqlite(site_id)


def drop_database(db_name: str, db_user: str) -> bool:
    """Drop a customer database (MySQL only — SQLite files are deleted with the site folder)."""
    if not _mysql_available():
        return True  # SQLite DB lives in deploy_path, removed with the folder
    try:
        conn = _root_conn()
        cur = conn.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
        cur.execute(f"DROP USER IF EXISTS `{db_user}`@`localhost`")
        cur.execute("FLUSH PRIVILEGES")
        cur.close()
        conn.close()
        return True
    except Exception as exc:
        current_app.logger.error(f"DB drop failed ({db_name}): {exc}")
        return False


def reset_db_password(db_user: str) -> str | None:
    """Reset MySQL user password. Returns new password or None."""
    if not _mysql_available():
        return None  # Not applicable for SQLite
    from utils.security import generate_db_password
    new_password = generate_db_password()
    try:
        conn = _root_conn()
        cur = conn.cursor()
        cur.execute(f"ALTER USER `{db_user}`@`localhost` IDENTIFIED BY %s", (new_password,))
        cur.execute("FLUSH PRIVILEGES")
        cur.close()
        conn.close()
        return new_password
    except Exception as exc:
        current_app.logger.error(f"DB password reset failed ({db_user}): {exc}")
        return None


def test_mysql_connection() -> bool:
    return _mysql_available()


def get_db_size_mb(db_name: str) -> float:
    """Return approximate DB size in MB."""
    if not _mysql_available():
        # For SQLite, db_name IS the file path
        try:
            return round(os.path.getsize(db_name) / 1048576, 2) if os.path.isfile(db_name) else 0.0
        except Exception:
            return 0.0
    try:
        conn = _root_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) "
            "FROM information_schema.tables WHERE table_schema = %s",
            (db_name,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return float(row[0]) if row and row[0] else 0.0
    except Exception:
        return 0.0


def suspend_database(db_name: str, db_user: str) -> bool:
    if not _mysql_available():
        return True
    try:
        conn = _root_conn()
        cur = conn.cursor()
        cur.execute(f"REVOKE ALL PRIVILEGES ON `{db_name}`.* FROM `{db_user}`@`localhost`")
        cur.execute("FLUSH PRIVILEGES")
        cur.close()
        conn.close()
        return True
    except Exception:
        return False


def restore_database(db_name: str, db_user: str) -> bool:
    if not _mysql_available():
        return True
    try:
        conn = _root_conn()
        cur = conn.cursor()
        cur.execute(f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO `{db_user}`@`localhost`")
        cur.execute("FLUSH PRIVILEGES")
        cur.close()
        conn.close()
        return True
    except Exception:
        return False


# ── MySQL provisioning ────────────────────────────────────────────────────────

def _provision_mysql(site_id: int) -> dict:
    from utils.security import generate_db_password
    db_name = f"site_{site_id}_db"
    db_user = f"site_{site_id}_user"
    password = generate_db_password()
    try:
        conn = _root_conn()
        cur = conn.cursor()
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
            f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        cur.execute(f"DROP USER IF EXISTS `{db_user}`@`localhost`")
        cur.execute(f"CREATE USER `{db_user}`@`localhost` IDENTIFIED BY %s", (password,))
        cur.execute(f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO `{db_user}`@`localhost`")
        cur.execute("FLUSH PRIVILEGES")
        cur.close()
        conn.close()
        return {
            "success": True, "mode": "mysql",
            "db_name": db_name, "db_user": db_user,
            "db_password": password, "db_host": "localhost",
            "db_port": current_app.config["MYSQL_PORT"],
            "error": None,
        }
    except Exception as exc:
        current_app.logger.error(f"MySQL provision failed for site {site_id}: {exc}")
        # Fall back to SQLite
        return _provision_sqlite(site_id)


# ── SQLite provisioning ───────────────────────────────────────────────────────

def _provision_sqlite(site_id: int) -> dict:
    """
    Create a SQLite database file for the site.
    The file is stored at: <USER_SITES_DIR>/../instance/site_dbs/site_<id>.db
    which keeps it outside the public web root but still accessible to the app.
    """
    from utils.security import generate_db_password
    base = current_app.config.get("SQLITE_PATH", "")
    db_dir = os.path.join(os.path.dirname(base), "site_dbs")
    os.makedirs(db_dir, exist_ok=True)

    db_path = os.path.join(db_dir, f"site_{site_id}.db")
    password = generate_db_password()  # Used as the "connection key" for display

    # Create the SQLite DB with a starter table
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _hostflow_info (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute(
            "INSERT OR REPLACE INTO _hostflow_info VALUES (?, ?)",
            ("created_for_site", str(site_id))
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        current_app.logger.error(f"SQLite provision failed for site {site_id}: {exc}")
        return {
            "success": False, "mode": "sqlite",
            "db_name": db_path, "db_user": "n/a",
            "db_password": None, "error": str(exc),
        }

    return {
        "success": True, "mode": "sqlite",
        "db_name": db_path,   # Full path for internal use
        "db_user": f"site_{site_id}",
        "db_password": password,
        "db_host": "sqlite_local",
        "db_port": 0,
        "error": None,
    }

# ── SQL Execution & Table Browser ─────────────────────────────────────────────

def execute_user_sql(db_info: dict, sql: str, multi: bool = False):
    """
    Execute user SQL against their database.
    Returns (result_dict | None, error_str | None).

    result_dict = {
        "columns": [...],
        "rows": [...],
        "rowcount": int,
        "statement_type": "SELECT" | "OTHER",
    }
    """
    is_sqlite = db_info.get("db_host") == "sqlite_local"

    if is_sqlite:
        return _exec_sqlite(db_info["db_name"], sql, multi)
    else:
        return _exec_mysql(db_info, sql, multi)


def _exec_sqlite(db_path: str, sql: str, multi: bool):
    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        if multi:
            conn.executescript(sql)
            conn.commit()
            conn.close()
            return {"columns": [], "rows": [], "rowcount": -1, "statement_type": "OTHER"}, None

        # Single statement — detect type
        first_word = sql.lstrip().split()[0].upper() if sql.strip() else ""
        cur.execute(sql)

        if first_word == "SELECT" or first_word == "PRAGMA":
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = [list(r) for r in cur.fetchall()]
            conn.close()
            return {"columns": columns, "rows": rows, "rowcount": len(rows), "statement_type": "SELECT"}, None
        else:
            conn.commit()
            rc = cur.rowcount
            conn.close()
            return {"columns": [], "rows": [], "rowcount": rc, "statement_type": "OTHER"}, None

    except Exception as exc:
        return None, str(exc)


def _exec_mysql(db_info: dict, sql: str, multi: bool):
    try:
        import pymysql
        from flask import current_app
        cfg = current_app.config
        conn = pymysql.connect(
            host=db_info["db_host"],
            port=int(db_info.get("db_port", 3306)),
            user=db_info["db_user"],
            password=db_info["db_password"],
            database=db_info["db_name"],
            charset="utf8mb4",
            autocommit=False,
        )
        cur = conn.cursor()

        if multi:
            # Split on semicolons and run each
            statements = [s.strip() for s in sql.split(";") if s.strip()]
            for stmt in statements:
                cur.execute(stmt)
            conn.commit()
            cur.close()
            conn.close()
            return {"columns": [], "rows": [], "rowcount": -1, "statement_type": "OTHER"}, None

        first_word = sql.lstrip().split()[0].upper() if sql.strip() else ""
        cur.execute(sql)

        if first_word == "SELECT" or first_word == "SHOW" or first_word == "DESCRIBE":
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = [list(r) for r in cur.fetchall()]
            cur.close()
            conn.close()
            return {"columns": columns, "rows": rows, "rowcount": len(rows), "statement_type": "SELECT"}, None
        else:
            conn.commit()
            rc = cur.rowcount
            cur.close()
            conn.close()
            return {"columns": [], "rows": [], "rowcount": rc, "statement_type": "OTHER"}, None

    except Exception as exc:
        return None, str(exc)


def get_db_tables(db_info: dict) -> list:
    """Return list of table names in the user's database."""
    is_sqlite = db_info.get("db_host") == "sqlite_local"
    try:
        if is_sqlite:
            import sqlite3
            conn = sqlite3.connect(db_info["db_name"])
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [r[0] for r in cur.fetchall()]
            conn.close()
            return tables
        else:
            import pymysql
            conn = pymysql.connect(
                host=db_info["db_host"],
                port=int(db_info.get("db_port", 3306)),
                user=db_info["db_user"],
                password=db_info["db_password"],
                database=db_info["db_name"],
                charset="utf8mb4",
            )
            cur = conn.cursor()
            cur.execute("SHOW TABLES")
            tables = [r[0] for r in cur.fetchall()]
            cur.close()
            conn.close()
            return tables
    except Exception:
        return []


def get_table_rows(db_info: dict, table_name: str, limit: int = 50, offset: int = 0):
    """
    Return (rows, columns, total_count, error).
    Sanitises table_name to alphanumeric + underscore only.
    """
    import re
    # Sanitise table name — alphanumeric, underscore, hyphen only
    safe_table = re.sub(r"[^\w\-]", "", table_name)
    if not safe_table:
        return [], [], 0, "Invalid table name."

    is_sqlite = db_info.get("db_host") == "sqlite_local"
    try:
        if is_sqlite:
            import sqlite3
            conn = sqlite3.connect(db_info["db_name"])
            conn.row_factory = sqlite3.Row
            total = conn.execute(f'SELECT COUNT(*) FROM "{safe_table}"').fetchone()[0]
            cur = conn.execute(f'SELECT * FROM "{safe_table}" LIMIT ? OFFSET ?', (limit, offset))
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = [list(r) for r in cur.fetchall()]
            conn.close()
            return rows, columns, total, None
        else:
            import pymysql
            conn = pymysql.connect(
                host=db_info["db_host"],
                port=int(db_info.get("db_port", 3306)),
                user=db_info["db_user"],
                password=db_info["db_password"],
                database=db_info["db_name"],
                charset="utf8mb4",
            )
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM `{safe_table}`")
            total = cur.fetchone()[0]
            cur.execute(f"SELECT * FROM `{safe_table}` LIMIT %s OFFSET %s", (limit, offset))
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = [list(r) for r in cur.fetchall()]
            cur.close()
            conn.close()
            return rows, columns, total, None
    except Exception as exc:
        return [], [], 0, str(exc)
