"""
HostFlow — WSGI Entry Point
Run with: gunicorn -k eventlet -w 1 -b 0.0.0.0:5000 wsgi:application
"""

from app import create_app, socketio

application = create_app()

if __name__ == "__main__":
    socketio.run(application, host="0.0.0.0", port=5000, debug=False)
