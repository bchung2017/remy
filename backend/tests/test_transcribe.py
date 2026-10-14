"""POST /api/transcribe and the Groq client, with HTTP mocked."""
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def make_client():
    tmp = tempfile.mkdtemp()
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tmp, "test.db")
    os.environ.pop("DB_SCHEMA", None)
    from remy_api import create_app
    return create_app().test_client()


def post_chunk(c, data=b"RIFF" + b"\x00" * 100, ctype="audio/wav", prompt=None):
    form = {"file": (io.BytesIO(data), "chunk.wav", ctype)}
    if prompt is not None:
        form["prompt"] = prompt
    return c.post("/api/transcribe", data=form, content_type="multipart/form-data")


class TranscribeOff(unittest.TestCase):
    def test_503_without_key(self):
        os.environ.pop("GROQ_API_KEY", None)
        c = make_client()
        self.assertFalse(c.get("/api/health").get_json()["voice"])
        self.assertEqual(post_chunk(c).status_code, 503)


@mock.patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test"})
class TranscribeOn(unittest.TestCase):
    def setUp(self):
        self.client = make_client()

    def test_returns_text_and_forwards_prompt(self):
        self.assertTrue(self.client.get("/api/health").get_json()["voice"])
        with mock.patch("remy_api.stt.transcribe", return_value="two cloves of garlic") as t:
            r = post_chunk(self.client, prompt="pound with salt")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {"text": "two cloves of garlic"})
        self.assertEqual(t.call_args.args[1], "audio/wav")
        self.assertEqual(t.call_args.args[3], "pound with salt")

    def test_bad_uploads(self):
        self.assertEqual(self.client.post("/api/transcribe", data={}, content_type="multipart/form-data").status_code, 400)
        self.assertEqual(post_chunk(self.client, ctype="image/png").status_code, 415)
        self.assertEqual(post_chunk(self.client, data=b"").status_code, 400)
        self.assertEqual(post_chunk(self.client, data=b"x" * (10 * 1024 * 1024 + 1)).status_code, 413)

    def test_stt_errors_map_to_status(self):
        from remy_api.stt import SttError
        for exc, status in ((SttError("rate limited", 429), 429), (SttError("down", 502), 502)):
            with mock.patch("remy_api.stt.transcribe", side_effect=exc):
                self.assertEqual(post_chunk(self.client).status_code, status)


class GroqClient(unittest.TestCase):
    @mock.patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test"})
    def test_posts_multipart_and_reads_text(self):
        from remy_api import stt
        ok = SimpleNamespace(status_code=200, json=lambda: {"text": "  hello  "})
        with mock.patch("remy_api.stt.requests.post", return_value=ok) as post:
            self.assertEqual(stt.transcribe(b"abc", "audio/wav", "c.wav", "ctx"), "hello")
        kw = post.call_args.kwargs
        self.assertEqual(post.call_args.args[0], "https://api.groq.com/openai/v1/audio/transcriptions")
        self.assertEqual(kw["headers"]["Authorization"], "Bearer gsk_test")
        self.assertEqual(kw["files"]["file"], ("c.wav", b"abc", "audio/wav"))
        self.assertEqual(kw["data"]["model"], "whisper-large-v3-turbo")
        self.assertEqual(kw["data"]["language"], "en")
        self.assertEqual(kw["data"]["prompt"], "ctx")
        for status, want in ((429, 429), (401, 502), (500, 502)):
            with mock.patch("remy_api.stt.requests.post", return_value=SimpleNamespace(status_code=status, json=dict)):
                with self.assertRaises(stt.SttError) as cm:
                    stt.transcribe(b"abc", "audio/wav")
                self.assertEqual(cm.exception.status, want)
        with mock.patch("remy_api.stt.requests.post", return_value=SimpleNamespace(status_code=200, json=lambda: {"text": " "})):
            self.assertEqual(stt.transcribe(b"abc", "audio/wav"), "")   # silence is not an error


if __name__ == "__main__":
    unittest.main()
