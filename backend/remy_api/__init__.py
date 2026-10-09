"""remy API — a small Flask + SQLAlchemy service.

Zero-config SQLite by default; set DATABASE_URL (+ optional DB_SCHEMA) to swap
to Postgres/Supabase, isolated inside its own schema so remy can share one
database with other apps without collisions. See remy_api/config.py and the
stackify-v1 skill for the pattern.
"""
import os

from dotenv import load_dotenv
from flask import Flask, send_from_directory
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

from .config import resolve_config

db = SQLAlchemy()

# repo root (…/remy); the static frontend lives in web/, brand tokens in brand/
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WEB_DIR = os.path.join(REPO_ROOT, "web")
BRAND_DIR = os.path.join(REPO_ROOT, "brand")


def create_app() -> Flask:
    load_dotenv()

    app = Flask(
        __name__,
        instance_relative_config=True,
        static_folder=WEB_DIR,
        static_url_path="",
    )
    os.makedirs(app.instance_path, exist_ok=True)

    cfg = resolve_config(app.instance_path)
    app.config["SQLALCHEMY_DATABASE_URI"] = cfg["uri"]
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = cfg["engine_options"]
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["REMY_BACKEND"] = cfg["backend"]
    app.config["REMY_DB_SCHEMA"] = cfg["schema"]

    db.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    from .routes import api
    app.register_blueprint(api)

    with app.app_context():
        # On Postgres, create the app's schema first (idempotent) so the
        # unqualified CREATE TABLEs below land in it — search_path is already
        # pinned to it on the connection. (stackify-v1 rule 4)
        schema = cfg["schema"]
        if cfg["backend"] == "postgres" and schema and schema != "public":
            db.session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
            db.session.commit()

        # Escape hatch for a schema that create_all() can't migrate in place (it
        # only creates missing *tables*, never alters an existing one). Set
        # REMY_DB_RESET=1 to drop remy's tables and rebuild them from the current
        # models at boot. DESTRUCTIVE: wipes all rows every boot it's set, so
        # remove the env var again once the new schema is live.
        if os.environ.get("REMY_DB_RESET", "").strip().lower() in ("1", "true", "yes"):
            app.logger.warning(
                "REMY_DB_RESET set — dropping ALL remy tables and rebuilding from "
                "the current models (remove the env var once the schema is live)."
            )
            db.drop_all()

        db.create_all()
        from .seed import seed_if_empty
        seed_if_empty()

    # The frontend is plain HTML/JS/CSS in web/ (no build step); brand tokens
    # come from brand/tokens.css so the two stay one file.
    @app.route("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.route("/tokens.css")
    def tokens_css():
        return send_from_directory(BRAND_DIR, "tokens.css")

    return app
