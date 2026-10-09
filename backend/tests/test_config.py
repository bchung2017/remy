"""Tests for the backend-selection + schema-isolation config (stackify-v1).

Pure-logic tests — no live database needed. Run with:
    python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from remy_api.config import (  # noqa: E402
    normalize_database_url,
    pg_schema,
    postgres_engine_options,
    resolve_config,
)


class SchemaValidation(unittest.TestCase):
    def test_defaults_to_public(self):
        self.assertEqual(pg_schema({}), "public")

    def test_accepts_bare_identifier(self):
        self.assertEqual(pg_schema({"DB_SCHEMA": "remy"}), "remy")
        self.assertEqual(pg_schema({"DB_SCHEMA": "_x9"}), "_x9")

    def test_rejects_injection_attempts(self):
        for bad in ["public; drop table", "a b", "1abc", "sch-ema", 'x"', ""]:
            with self.assertRaises(ValueError):
                pg_schema({"DB_SCHEMA": bad})


class UrlNormalization(unittest.TestCase):
    def test_bare_postgres_scheme_upgraded(self):
        self.assertEqual(
            normalize_database_url("postgres://u:p@h:5432/db"),
            "postgresql+psycopg://u:p@h:5432/db",
        )

    def test_postgresql_gets_psycopg_driver(self):
        self.assertEqual(
            normalize_database_url("postgresql://u:p@h:5432/db"),
            "postgresql+psycopg://u:p@h:5432/db",
        )

    def test_explicit_driver_left_alone(self):
        url = "postgresql+psycopg://u:p@h:5432/db"
        self.assertEqual(normalize_database_url(url), url)


class EngineOptions(unittest.TestCase):
    def test_pins_search_path(self):
        opts = postgres_engine_options("remy", {})
        self.assertEqual(opts["connect_args"]["options"], "-c search_path=remy")

    def test_ssl_required_by_default_disable_opt_in(self):
        self.assertEqual(postgres_engine_options("remy", {})["connect_args"]["sslmode"], "require")
        self.assertEqual(
            postgres_engine_options("remy", {"DATABASE_SSL": "disable"})["connect_args"]["sslmode"],
            "disable",
        )

    def test_pool_max_configurable(self):
        self.assertEqual(postgres_engine_options("remy", {"PGPOOL_MAX": "7"})["pool_size"], 7)


class BackendSelection(unittest.TestCase):
    def test_sqlite_when_no_url(self):
        cfg = resolve_config("/tmp/inst", {})
        self.assertEqual(cfg["backend"], "sqlite")
        self.assertTrue(cfg["uri"].startswith("sqlite:///"))
        self.assertIsNone(cfg["schema"])
        self.assertEqual(cfg["engine_options"], {})

    def test_postgres_when_url_present(self):
        cfg = resolve_config("/tmp/inst", {
            "DATABASE_URL": "postgres://u:p@h:5432/db",
            "DB_SCHEMA": "remy",
        })
        self.assertEqual(cfg["backend"], "postgres")
        self.assertEqual(cfg["uri"], "postgresql+psycopg://u:p@h:5432/db")
        self.assertEqual(cfg["schema"], "remy")
        self.assertEqual(cfg["engine_options"]["connect_args"]["options"], "-c search_path=remy")

    def test_explicit_sqlite_url_is_not_treated_as_postgres(self):
        cfg = resolve_config("/tmp/inst", {"DATABASE_URL": "sqlite:////tmp/x.db"})
        self.assertEqual(cfg["backend"], "sqlite")
        self.assertEqual(cfg["uri"], "sqlite:////tmp/x.db")
        self.assertIsNone(cfg["schema"])
        self.assertEqual(cfg["engine_options"], {})


if __name__ == "__main__":
    unittest.main()
