"""Image uploads, asset serving, and pruning on block removal."""
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def make_client():
    tmp = tempfile.mkdtemp()
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tmp, "test.db")
    os.environ.pop("DB_SCHEMA", None)
    from remy_api import create_app
    return create_app().test_client()


class Assets(unittest.TestCase):
    def setUp(self):
        self.client = make_client()
        self.rid = self.client.post("/api/recipes", json={"title": "Pan"}).get_json()["id"]

    def upload(self, data=PNG, ctype="image/png", name="a.png", rid=None):
        return self.client.post(f"/api/recipes/{rid or self.rid}/assets",
                                data={"file": (io.BytesIO(data), name, ctype)},
                                content_type="multipart/form-data")

    def test_upload_and_serve(self):
        r = self.upload()
        self.assertEqual(r.status_code, 201)
        a = r.get_json()
        self.assertEqual(a["contentType"], "image/png")
        self.assertEqual(a["size"], len(PNG))
        got = self.client.get(a["url"])
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.data, PNG)
        self.assertEqual(got.content_type, "image/png")
        self.assertIn("immutable", got.headers["Cache-Control"])

    def test_rejects_non_image_missing_and_oversize(self):
        self.assertEqual(self.upload(ctype="audio/webm", name="a.webm").status_code, 415)
        r = self.client.post(f"/api/recipes/{self.rid}/assets", data={}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.upload(data=b"x" * (8 * 1024 * 1024 + 1)).status_code, 413)
        self.assertEqual(self.upload(rid=999).status_code, 404)

    def test_unreferenced_assets_pruned_on_block_save_and_on_delete(self):
        keep = self.upload().get_json()["id"]
        drop = self.upload().get_json()["id"]
        r = self.client.put(f"/api/recipes/{self.rid}", json={"blocks": [{"type": "image", "asset": keep}]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get(f"/api/assets/{keep}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/assets/{drop}").status_code, 404)
        self.client.delete(f"/api/recipes/{self.rid}")
        self.assertEqual(self.client.get(f"/api/assets/{keep}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
