"""
HostFlow — Activity Logger
"""

from flask import request, session
from utils.db import log_activity


def log(action: str, entity_type: str = None, entity_id: int = None, detail: str = None):
    """Log an action for the currently logged-in user."""
    user_id = session.get("user_id")
    ip = request.remote_addr if request else None
    log_activity(user_id, action, entity_type, entity_id, detail, ip)
