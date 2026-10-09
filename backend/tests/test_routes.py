"""Tests for the recipe routes, using a throwaway on-disk SQLite app."""
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

    def test_serves_frontend_and_tokens(self):
        c = make_client()
        self.assertIn(b"<title>remy</title>", c.get("/").data)
        self.assertEqual(c.get("/app.js").status_code, 200)
        self.assertIn(b"--copper", c.get("/tokens.css").data)


class Recipes(unittest.TestCase):
    def setUp(self):
        self.client = make_client()

    def test_seeded_on_first_boot(self):
        rows = self.client.get("/api/recipes").get_json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Ratatouille")
        self.assertEqual(rows[0]["tags"], ["vegetable", "bake"])

    def test_create_read_update_delete(self):
        r = self.client.post("/api/recipes", json={"title": "Omelette", "body": "3 eggs. Butter.", "tags": "Eggs, breakfast, eggs"})
        self.assertEqual(r.status_code, 201)
        rec = r.get_json()
        self.assertEqual(rec["tags"], ["eggs", "breakfast"])  # normalized, deduped

        r = self.client.get(f"/api/recipes/{rec['id']}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["body"], "3 eggs. Butter.")

        r = self.client.put(f"/api/recipes/{rec['id']}", json={"body": "4 eggs.", "tags": ["brunch"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["body"], "4 eggs.")
        self.assertEqual(r.get_json()["tags"], ["brunch"])
        self.assertEqual(r.get_json()["title"], "Omelette")  # partial update keeps title

        self.assertEqual(self.client.delete(f"/api/recipes/{rec['id']}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/recipes/{rec['id']}").status_code, 404)

    def test_search_tag_and_sort(self):
        self.client.post("/api/recipes", json={"title": "Bread", "body": "flour water salt yeast", "tags": ["bake"]})
        self.client.post("/api/recipes", json={"title": "Aioli", "body": "garlic, oil, egg yolk"})

        titles = [r["title"] for r in self.client.get("/api/recipes?q=garlic").get_json()]
        self.assertEqual(sorted(titles), ["Aioli", "Ratatouille"])   # body match, case-insensitive

        titles = [r["title"] for r in self.client.get("/api/recipes?tag=bake").get_json()]
        self.assertEqual(sorted(titles), ["Bread", "Ratatouille"])

        titles = [r["title"] for r in self.client.get("/api/recipes?sort=title").get_json()]
        self.assertEqual(titles, ["Aioli", "Bread", "Ratatouille"])

        titles = [r["title"] for r in self.client.get("/api/recipes?sort=created").get_json()]
        self.assertEqual(titles[0], "Aioli")  # newest first

        tags = self.client.get("/api/tags").get_json()
        self.assertEqual(tags, [{"tag": "bake", "count": 2}, {"tag": "vegetable", "count": 1}])

    def test_validation(self):
        self.assertEqual(self.client.post("/api/recipes", json={}).status_code, 400)
        self.assertEqual(self.client.post("/api/recipes", json={"title": "  "}).status_code, 400)
        self.assertEqual(self.client.post("/api/recipes", json={"title": "x", "body": 3}).status_code, 400)
        self.assertEqual(self.client.post("/api/recipes", json={"title": "x", "tags": 3}).status_code, 400)
        self.assertEqual(self.client.put("/api/recipes/1", json={"title": ""}).status_code, 400)

    def test_missing_is_404(self):
        self.assertEqual(self.client.get("/api/recipes/999").status_code, 404)
        self.assertEqual(self.client.put("/api/recipes/999", json={"body": "x"}).status_code, 404)
        self.assertEqual(self.client.delete("/api/recipes/999").status_code, 404)


if __name__ == "__main__":
    unittest.main()
