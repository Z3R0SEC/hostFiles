"""
HostFlow — Notifications Utility
In-app notifications + SocketIO push.
"""

from utils.db import create_notification, get_unread_count


def notify(user_id: int, title: str, message: str, ntype: str = "info", link: str = None):
    """Create a notification and push it via SocketIO if connected."""
    create_notification(user_id, title, message, ntype, link)
    try:
        from app import socketio
        count = get_unread_count(user_id)
        socketio.emit("notification", {
            "title": title,
            "message": message,
            "type": ntype,
            "link": link,
            "unread_count": count,
        }, room=f"user_{user_id}")
    except Exception:
        pass


def notify_deploy_success(user_id: int, site_name: str, site_id: int):
    notify(
        user_id,
        "Deployment Successful",
        f"{site_name} was deployed successfully.",
        "success",
        f"/sites/{site_id}",
    )


def notify_deploy_failed(user_id: int, site_name: str, site_id: int):
    notify(
        user_id,
        "Deployment Failed",
        f"Deployment of {site_name} failed. Check the deployment log.",
        "error",
        f"/sites/{site_id}",
    )


def notify_backup_done(user_id: int, site_name: str, site_id: int):
    notify(
        user_id,
        "Backup Complete",
        f"A backup of {site_name} was created successfully.",
        "success",
        f"/backups/{site_id}",
    )


def notify_db_password_changed(user_id: int, db_name: str):
    notify(
        user_id,
        "Database Password Changed",
        f"The password for {db_name} has been reset.",
        "warning",
    )
