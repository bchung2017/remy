"""WSGI entry point. Run directly for development (`python wsgi.py`) or point a
production server at `wsgi:app` (e.g. `gunicorn wsgi:app`)."""
import os

from remy_api import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
