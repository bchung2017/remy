"""Image uploads, asset serving, pruning on block removal, and the voice endpoint."""
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

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


class Voice(unittest.TestCase):
    def post_voice(self, client, rid, ctype="audio/webm"):
        return client.post(f"/api/recipes/{rid}/voice",
                           data={"file": (io.BytesIO(b"RIFF" + b"\x00" * 100), "memo.webm", ctype)},
                           content_type="multipart/form-data")

    def test_503_when_either_key_missing(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}):
            os.environ.pop("OPENAI_API_KEY", None)
            c = make_client()
            rid = c.post("/api/recipes", json={}).get_json()["id"]
            self.assertFalse(c.get("/api/health").get_json()["voice"])
            self.assertEqual(self.post_voice(c, rid).status_code, 503)

    @mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k", "OPENAI_API_KEY": "k"})
    def test_transcribes_drafts_and_appends_block(self):
        from remy_api.llm import Draft
        c = make_client()
        self.assertTrue(c.get("/api/health").get_json()["voice"])
        rid = c.post("/api/recipes", json={}).get_json()["id"]   # Untitled, no tags
        draft = Draft(title="Aioli", body="Ingredients\ngarlic\n\nSteps\n1. Pound.", tags=["sauce"])
        with mock.patch("remy_api.stt.transcribe", return_value="um garlic pound it") as t, \
             mock.patch("remy_api.llm._parse", return_value=SimpleNamespace(stop_reason="end_turn", parsed_output=draft)) as p:
            r = self.post_voice(c, rid)
        self.assertEqual(r.status_code, 201, r.get_json())
        rec = r.get_json()
        self.assertEqual(t.call_args.args[1], "audio/webm")
        p.assert_called_once_with("um garlic pound it", "")        # no title hint while Untitled
        self.assertEqual(rec["title"], "Aioli")
        self.assertEqual(rec["tags"], ["sauce"])
        blk = rec["blocks"][-1]
        self.assertEqual(blk["type"], "ai")
        self.assertEqual(blk["transcript"], "um garlic pound it")
        self.assertTrue(blk["text"].startswith("Ingredients"))
        self.assertEqual(c.get(f"/api/assets/{blk['asset']}").content_type, "audio/webm")   # audio kept

        # a second memo keeps the existing title/tags and passes the title as a hint
        with mock.patch("remy_api.stt.transcribe", return_value="more"), \
             mock.patch("remy_api.llm._parse", return_value=SimpleNamespace(stop_reason="end_turn", parsed_output=Draft(title="Other", body="b", tags=["x"]))) as p:
            rec = self.post_voice(c, rid, ctype="video/mp4").get_json()
        p.assert_called_once_with("more", "Aioli")
        self.assertEqual(rec["title"], "Aioli")
        self.assertEqual(rec["tags"], ["sauce"])
        self.assertEqual(len(rec["blocks"]), 2)

    @mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k", "OPENAI_API_KEY": "k"})
    def test_stt_errors_and_bad_uploads(self):
        from remy_api.stt import SttError
        c = make_client()
        rid = c.post("/api/recipes", json={}).get_json()["id"]
        with mock.patch("remy_api.stt.transcribe", side_effect=SttError("no speech found in the audio", 422)):
            self.assertEqual(self.post_voice(c, rid).status_code, 422)
        with mock.patch("remy_api.stt.transcribe", side_effect=SttError("down", 502)):
            self.assertEqual(self.post_voice(c, rid).status_code, 502)
        self.assertEqual(self.post_voice(c, rid, ctype="image/png").status_code, 415)
        self.assertEqual(self.post_voice(c, 999).status_code, 404)
        self.assertEqual(len(c.get(f"/api/recipes/{rid}").get_json()["blocks"]), 0)   # nothing appended on failure


class SttClient(unittest.TestCase):
    @mock.patch.dict(os.environ, {"OPENAI_API_KEY": "k"})
    def test_posts_multipart_and_reads_text(self):
        from remy_api import stt
        ok = SimpleNamespace(status_code=200, json=lambda: {"text": "  hello  "})
        with mock.patch("remy_api.stt.requests.post", return_value=ok) as post:
            self.assertEqual(stt.transcribe(b"abc", "audio/webm", "m.webm"), "hello")
        kw = post.call_args.kwargs
        self.assertEqual(kw["headers"]["Authorization"], "Bearer k")
        self.assertEqual(kw["files"]["file"], ("m.webm", b"abc", "audio/webm"))
        self.assertEqual(kw["data"]["model"], "whisper-1")
        for status, want in ((429, 429), (500, 502)):
            with mock.patch("remy_api.stt.requests.post", return_value=SimpleNamespace(status_code=status, json=dict)):
                with self.assertRaises(stt.SttError) as cm:
                    stt.transcribe(b"abc", "audio/webm")
                self.assertEqual(cm.exception.status, want)
        with mock.patch("remy_api.stt.requests.post", return_value=SimpleNamespace(status_code=200, json=lambda: {"text": " "})):
            with self.assertRaises(stt.SttError) as cm:
                stt.transcribe(b"abc", "audio/webm")
            self.assertEqual(cm.exception.status, 422)


if __name__ == "__main__":
    unittest.main()
