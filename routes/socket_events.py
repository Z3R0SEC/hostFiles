"""
HostFlow — SocketIO Events
Real-time deployment progress, notifications, live activity feed.
"""

from flask import session
from flask_socketio import join_room, leave_room, emit

from app import socketio


@socketio.on("connect")
def handle_connect():
    user_id = session.get("user_id")
    if user_id:
        join_room(f"user_{user_id}")
        emit("connected", {"status": "ok", "user_id": user_id})


@socketio.on("disconnect")
def handle_disconnect():
    user_id = session.get("user_id")
    if user_id:
        leave_room(f"user_{user_id}")


@socketio.on("join_deployment")
def join_deployment(data):
    dep_id = data.get("dep_id")
    if dep_id:
        join_room(f"deploy_{dep_id}")


@socketio.on("leave_deployment")
def leave_deployment(data):
    dep_id = data.get("dep_id")
    if dep_id:
        leave_room(f"deploy_{dep_id}")


@socketio.on("subscribe_activity")
def subscribe_activity(data):
    """Admin subscribes to live activity feed."""
    user_id = session.get("user_id")
    from utils.db import get_user_by_id
    if user_id:
        user = get_user_by_id(user_id)
        if user and user["role"] in ("admin", "super_admin"):
            join_room("admin_activity")
