"""One-shot SQLite → Postgres copier (stackify-v1 migration guard).

Applies the schema idempotently into the target's isolated namespace, then
*refuses to run if the target tables already hold rows* so a second accidental
run can't double-insert. Rows copy verbatim.

Usage:
    export DATABASE_URL='postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres'
    export DB_SCHEMA=remy
    python scripts/migrate_sqlite_to_pg.py [path/to/remy.db]
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, func, select, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from remy_api import db  # noqa: E402  (registers models on db.metadata)
from remy_api.config import (  # noqa: E402
    normalize_database_url,
    pg_schema,
    postgres_engine_options,
)
from remy_api.models import Item  # noqa: E402

TABLES = [Item.__table__]


def main() -> None:
    load_dotenv()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL is not set — nothing to migrate to.")
    schema = pg_schema()

    default_sqlite = Path(__file__).resolve().parent.parent / "instance" / "remy.db"
    src_path = sys.argv[1] if len(sys.argv) > 1 else str(default_sqlite)
    if not Path(src_path).exists():
        sys.exit(f"source SQLite file not found: {src_path}")

    src = create_engine("sqlite:///" + src_path)
    dst = create_engine(normalize_database_url(dsn), **postgres_engine_options(schema))

    # schema first, then unqualified tables — search_path places them
    with dst.begin() as conn:
        if schema != "public":
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
    db.metadata.create_all(dst)

    with src.connect() as sconn, dst.begin() as dconn:
        for table in TABLES:
            existing = dconn.execute(select(func.count()).select_from(table)).scalar_one()
            if existing:
                sys.exit(
                    f"refusing to run: {table.name} already has {existing} rows "
                    f"in schema {schema}"
                )
        for table in TABLES:
            rows = [dict(r._mapping) for r in sconn.execute(select(table))]
            if rows:
                dconn.execute(table.insert(), rows)
            print(f"copied {len(rows)} rows into {schema}.{table.name}")


if __name__ == "__main__":
    main()
