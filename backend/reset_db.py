"""Destructively rebuild remy's tables and reseed the default data.

Use this once after a schema change when there's nothing worth preserving —
`create_all()` only creates missing *tables*, it never alters an existing one,
so an existing Postgres/Supabase deploy keeps its stale schema and breaks. This
drops every remy table in the configured schema, recreates them from the
current models, and reseeds.

    cd backend
    DATABASE_URL="<postgres session-pooler url>" DB_SCHEMA="<schema>" \
        ./venv/bin/python reset_db.py --yes

Omit DATABASE_URL to rebuild the local SQLite database instead. It only ever
touches remy's own tables (inside DB_SCHEMA when set), never a neighbour app's.
Requires --yes because it deletes all existing rows.
"""
import sys

from remy_api import create_app, db
from remy_api.seed import seed_if_empty


def main() -> int:
    if "--yes" not in sys.argv:
        print("refusing to run without --yes — this DROPS all remy tables.")
        return 2

    app = create_app()
    with app.app_context():
        backend = app.config.get("REMY_BACKEND")
        schema = app.config.get("REMY_DB_SCHEMA") or "(search_path default)"
        print(f"remy: rebuilding tables — backend={backend} schema={schema}")

        db.drop_all()      # remy's tables only (create_all made them under this search_path)
        db.create_all()    # fresh from the current models
        seed_if_empty()
        db.session.commit()

        from remy_api.models import Recipe
        print(f"remy: reseeded {Recipe.query.count()} recipes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
