"""Tests for the item routes, using a throwaway on-disk SQLite app."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def make_client():
    tmp = tempfile.mkdtemp()
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tmp, "test.db")
    os.environ.pop("DB_SCHEMA", None)
    # import after env is set so create_app picks it up
    from remy_api import create_app
    app = create_app()
    return app.test_client()


class Health(unittest.TestCase):
    def test_reports_backend(self):
        r = make_client().get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["backend"], "sqlite")
        self.assertIsNone(r.get_json()["schema"])


class Items(unittest.TestCase):
    def setUp(self):
        self.client = make_client()

    def test_seeded_on_first_boot(self):
        rows = self.client.get("/api/items").get_json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "first item")

    def test_create_read_update_delete(self):
        r = self.client.post("/api/items", json={"name": "ratatouille", "note": "the dish"})
        self.assertEqual(r.status_code, 201)
        item = r.get_json()
        self.assertEqual(item["name"], "ratatouille")
        self.assertEqual(item["position"], 1)  # appended after the seed row

        r = self.client.get(f"/api/items/{item['id']}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["note"], "the dish")

        r = self.client.put(f"/api/items/{item['id']}", json={"note": "revised", "position": 5})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["note"], "revised")
        self.assertEqual(r.get_json()["position"], 5)

        self.assertEqual(self.client.delete(f"/api/items/{item['id']}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/items/{item['id']}").status_code, 404)

    def test_name_required(self):
        self.assertEqual(self.client.post("/api/items", json={}).status_code, 400)
        self.assertEqual(self.client.post("/api/items", json={"name": "  "}).status_code, 400)

    def test_bad_values_are_400(self):
        self.assertEqual(self.client.put("/api/items/1", json={"name": ""}).status_code, 400)
        self.assertEqual(self.client.put("/api/items/1", json={"position": "x"}).status_code, 400)
        self.assertEqual(self.client.post("/api/items", json={"name": "a", "note": 3}).status_code, 400)

    def test_unknown_keys_ignored(self):
        r = self.client.put("/api/items/1", json={"bogus": 1, "id": 99, "note": "ok"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["id"], 1)
        self.assertEqual(r.get_json()["note"], "ok")

    def test_missing_is_404(self):
        self.assertEqual(self.client.get("/api/items/999").status_code, 404)
        self.assertEqual(self.client.put("/api/items/999", json={"note": "x"}).status_code, 404)
        self.assertEqual(self.client.delete("/api/items/999").status_code, 404)


if __name__ == "__main__":
    unittest.main()
