"""Boot against a database created before `blocks` existed: the column is added
in place and old rows read back as one legacy text block."""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class AddMissingColumns(unittest.TestCase):
    def test_old_recipes_table_is_upgraded_in_place(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "old.db")
        con = sqlite3.connect(path)
        con.executescript("""
            CREATE TABLE recipes (
              id INTEGER PRIMARY KEY, title VARCHAR(200) NOT NULL, body TEXT NOT NULL DEFAULT '',
              tags VARCHAR(400) NOT NULL DEFAULT '', created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL);
            INSERT INTO recipes (title, body, tags, created_at, updated_at)
              VALUES ('Old soup', 'Boil it.', ',soup,', '2026-01-01 00:00:00', '2026-01-01 00:00:00');
        """)
        con.commit(); con.close()

        os.environ["DATABASE_URL"] = "sqlite:///" + path
        os.environ.pop("DB_SCHEMA", None)
        from remy_api import create_app
        c = create_app().test_client()          # must not raise on the first query

        cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(recipes)")}
        self.assertIn("blocks", cols)
        self.assertIn("compiled", cols)
        rows = c.get("/api/recipes").get_json()
        self.assertEqual([r["title"] for r in rows], ["Old soup"])       # not reseeded: table wasn't empty
        self.assertEqual(rows[0]["blocks"], [{"id": "legacy", "type": "text", "text": "Boil it."}])
        self.assertEqual(c.get("/api/assets/x").status_code, 404)         # assets table created alongside

        create_app()   # second boot is a no-op


if __name__ == "__main__":
    unittest.main()
