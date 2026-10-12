"""remy API — a small Flask + SQLAlchemy service.

Zero-config SQLite by default; set DATABASE_URL (+ optional DB_SCHEMA) to swap
to Postgres/Supabase, isolated inside its own schema so remy can share one
database with other apps without collisions. See remy_api/config.py and the
stackify-v1 skill for the pattern.
"""
import os

from dotenv import load_dotenv
from flask import Flask, request, send_from_directory
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text

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
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024   # uploads; routes cap assets at 8 MB

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
        _add_missing_columns()
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

    # The Whisper test page wants multithreaded WASM, which needs cross-origin
    # isolation. Scoped to that page: COEP would break the app's other embeds.
    @app.after_request
    def isolate_whisper_test(resp):
        if request.path == "/whisper-test.html":
            resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
            resp.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
        return resp

    return app


# Columns added after the first release. create_all() only creates missing
# *tables*, so an existing database keeps its old shape and the first query
# fails with UndefinedColumn. These are additive and safe to re-run: each is
# applied only when the inspector says the column is absent. Rows written
# before the column existed get the default; Recipe.block_list() already
# treats an empty `blocks` with a non-empty `body` as one legacy text block.
ADDED_COLUMNS = [
    ("recipes", "blocks", "TEXT NOT NULL DEFAULT '[]'"),
]


def _add_missing_columns() -> None:
    insp = inspect(db.engine)
    for table, column, ddl in ADDED_COLUMNS:
        if table not in insp.get_table_names():
            continue
        if column in {c["name"] for c in insp.get_columns(table)}:
            continue
        db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        db.session.commit()
