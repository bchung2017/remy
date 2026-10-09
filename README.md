# remy

A **Flask + SQLite** JSON API that swaps to **Postgres/Supabase** via
`DATABASE_URL`, isolated in its own schema so it can share one database with
other apps without colliding. Deploys to Render as a Docker web service.

## Stack

- **[Flask](https://flask.palletsprojects.com/)** — JSON API under `/api`
- **[Flask-SQLAlchemy](https://flask-sqlalchemy.palletsprojects.com/)** over **SQLite** by default
- **Postgres/Supabase** when `DATABASE_URL` is set, pinned to `DB_SCHEMA`
  (the `stackify-v1` no-collision schema pattern)
- **gunicorn** in the container; Render Blueprint in `render.yaml`

## Getting started

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python wsgi.py            # http://localhost:5000
```

On first run it creates `backend/instance/remy.db` and seeds one placeholder
item. `GET /api/health` reports the active backend + schema.

To use a different database, copy `backend/.env.example` to `backend/.env` and
set `DATABASE_URL`, or export it in the shell.

### Sharing one Postgres/Supabase project (no-collision schema)

```bash
# Supabase SESSION pooler host (port :5432 — required, see below)
export DATABASE_URL='postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres'
export DB_SCHEMA=remy        # remy's tables live here; default is public
```

- **`DB_SCHEMA` is validated** as a bare SQL identifier
  (`^[A-Za-z_][A-Za-z0-9_]*$`) before it's interpolated, then created
  idempotently (`CREATE SCHEMA IF NOT EXISTS`) on first boot.
- **`search_path` is pinned per connection** via libpq `options`, so every
  unqualified query resolves inside remy's namespace.
- **Session pooler required.** Pinning `search_path` needs a session-mode
  connection; the transaction pooler (`:6543`) would drop it.
- **`postgres://` URLs are normalized** to `postgresql+psycopg://` (psycopg 3).
- **Unset `DATABASE_URL` → SQLite, unset `DB_SCHEMA` → `public`.**

Migrate an existing SQLite database into the shared schema (refuses to run into
non-empty tables):

```bash
cd backend
python scripts/migrate_sqlite_to_pg.py [path/to/remy.db]
```

Rebuild the tables from the current models after a schema change (destructive):

```bash
cd backend
python reset_db.py --yes
```

Additional env vars: `DATABASE_SSL=disable` (local plaintext Postgres only),
`PGPOOL_MAX` (max pool connections, default 3), `REMY_DB_RESET=1` (drop +
recreate tables at boot — remove once the schema is live). See
`backend/.env.example`.

Tests:

```bash
cd backend && python -m unittest discover -s tests
```

## Deploy (Render Blueprint)

1. Push to GitHub.
2. In Render: **New → Blueprint**, point it at this repo. It reads `render.yaml`
   and creates one Docker web service.
3. Set the secret **`DATABASE_URL`** in the service's Environment tab — the
   Supabase **Session pooler** URL (`:5432`). `DB_SCHEMA` defaults to `remy`.
   Leave `DATABASE_URL` unset to run on ephemeral SQLite (data resets on deploy).
4. Deploy. Health check is `/api/health`.

Build the image locally the same way Render does:

```bash
docker build -t remy .
docker run -p 5000:5000 -e DATABASE_URL=... -e DB_SCHEMA=remy remy
```

## API

Base path `/api`. Fields use camelCase keys.

| Method   | Path          | Purpose                                  |
| -------- | ------------- | ---------------------------------------- |
| `GET`    | `/health`     | liveness + active backend/schema         |
| `GET`    | `/items`      | list items                               |
| `POST`   | `/items`      | create an item `{name, note?, position?}` |
| `GET`    | `/items/:id`  | read one item                            |
| `PUT`    | `/items/:id`  | update an item's fields                  |
| `DELETE` | `/items/:id`  | delete an item                           |

`Item` is a placeholder model to prove the stack end to end — replace it in
`backend/remy_api/models.py` once the real domain is decided.

## Layout

```
Dockerfile              python:3.11-slim + gunicorn
render.yaml             Render Blueprint (one Docker web service)
backend/
  wsgi.py               dev entry / WSGI app (wsgi:app)
  requirements.txt
  .env.example
  reset_db.py           drop + recreate + reseed (destructive, needs --yes)
  remy_api/
    __init__.py         create_app factory, db init, schema creation
    config.py           backend selection + no-collision schema isolation
    models.py           Item (to_dict → camelCase JSON)
    routes.py           /api blueprint
    seed.py             one-time seed when the table is empty
  scripts/
    migrate_sqlite_to_pg.py   one-shot SQLite → Postgres copier (guarded)
  tests/
    test_config.py      backend-selection + schema-isolation unit tests
    test_routes.py      item CRUD tests on throwaway SQLite
```
