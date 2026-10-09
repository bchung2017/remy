"""Backend selection + the no-collision schema isolation (stackify-v1 pattern).

SQLite by default (zero config); Postgres/Supabase when DATABASE_URL is set,
isolated inside its own schema so remy can share one database with other apps
without their tables ever colliding.
"""
import os
import re

# The schema name is interpolated into DDL and the connection `options` string —
# places bind parameters don't reach — so validate it as a bare SQL identifier
# or refuse to start. (stackify-v1 rule 1)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def pg_schema(environ=os.environ) -> str:
    """The Postgres schema (namespace) for this app's tables. Default `public`
    means isolation is opt-in and unset behaves like an ordinary app."""
    s = environ.get("DB_SCHEMA", "public")
    if not _IDENT.match(s):
        raise ValueError(
            f'Invalid DB_SCHEMA "{s}" — must be a bare SQL identifier '
            r"([A-Za-z_][A-Za-z0-9_]*)."
        )
    return s


def normalize_database_url(url: str) -> str:
    """Normalize a connection string to a SQLAlchemy + psycopg (v3) URL.

    Providers hand out bare ``postgres://`` URLs; SQLAlchemy needs the
    ``postgresql://`` scheme, and we pin the psycopg 3 driver explicitly.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+psycopg" not in url.split("://", 1)[0]:
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def postgres_engine_options(schema: str, environ=os.environ) -> dict:
    """SQLAlchemy engine options that pin ``search_path`` to the app's schema
    for the whole life of every pooled connection (stackify-v1 rules 2 & 3).

    This rides the libpq startup ``options`` param, so it requires a
    *session-mode* connection — on Supabase, the Session pooler (:5432). A
    transaction pooler would reset session state and silently drop the path.
    """
    ssl = environ.get("DATABASE_SSL")
    sslmode = "disable" if ssl == "disable" else "require"
    pool_max = int(environ.get("PGPOOL_MAX", "3"))  # keep small behind the pooler
    return {
        "pool_size": pool_max,
        "pool_pre_ping": True,
        "connect_args": {
            "options": f"-c search_path={schema}",  # <-- the crux
            "sslmode": sslmode,
        },
    }


def resolve_config(instance_path: str, environ=os.environ) -> dict:
    """Choose the backend by env: a Postgres DATABASE_URL → schema-isolated
    Postgres; any other DATABASE_URL (e.g. an explicit ``sqlite:///`` path) is
    used as-is; unset → a zero-config on-disk SQLite file."""
    raw = environ.get("DATABASE_URL")
    if raw:
        uri = normalize_database_url(raw)
        if uri.startswith("postgresql"):
            schema = pg_schema(environ)
            return {
                "backend": "postgres",
                "uri": uri,
                "schema": schema,
                "engine_options": postgres_engine_options(schema, environ),
            }
        # a non-Postgres URL (SQLite, etc.): no schema isolation, no pg options
        return {
            "backend": "sqlite" if uri.startswith("sqlite") else "other",
            "uri": uri,
            "schema": None,
            "engine_options": {},
        }
    return {
        "backend": "sqlite",
        "uri": "sqlite:///" + os.path.join(instance_path, "remy.db"),
        "schema": None,
        "engine_options": {},
    }
