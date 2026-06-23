"""
HostFlow — Development Runner
Run: python3 run_dev.py  (or ./start.sh dev)
"""
from app import create_app, socketio

app = create_app()

if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        allow_unsafe_werkzeug=True
        debug=True,
        use_reloader=False,   # Reloader causes double-init with SocketIO + eventlet
    )
