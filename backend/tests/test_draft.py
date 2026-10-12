"""Tests for the dictation -> draft endpoint, with the model call mocked."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import anthropic
import httpx2 as httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def make_client():
    tmp = tempfile.mkdtemp()
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tmp, "test.db")
    os.environ.pop("DB_SCHEMA", None)
    from remy_api import create_app
    return create_app().test_client()


def fake_response(parsed, stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed)


class DraftOff(unittest.TestCase):
    def test_503_without_key_and_health_reports_it(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            c = make_client()
            self.assertFalse(c.get("/api/health").get_json()["draft"])
            self.assertEqual(c.post("/api/recipes/draft", json={"transcript": "x"}).status_code, 503)


@mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
class DraftOn(unittest.TestCase):
    def setUp(self):
        self.client = make_client()

    def test_formats_transcript(self):
        from remy_api.llm import Draft
        draft = Draft(title="Omelette", body="Ingredients\n3 eggs\n\nSteps\n1. Beat.", tags=["Eggs", "eggs", "Breakfast"])
        with mock.patch("remy_api.llm._parse", return_value=fake_response(draft)) as p:
            r = self.client.post("/api/recipes/draft", json={"transcript": "uh so three eggs beat them", "title": "Om"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {"title": "Omelette", "body": "Ingredients\n3 eggs\n\nSteps\n1. Beat.", "tags": ["eggs", "breakfast"]})
        p.assert_called_once_with("uh so three eggs beat them", "Om")
        self.assertTrue(self.client.get("/api/health").get_json()["draft"])

    def test_transcript_required(self):
        self.assertEqual(self.client.post("/api/recipes/draft", json={}).status_code, 400)
        self.assertEqual(self.client.post("/api/recipes/draft", json={"transcript": "  "}).status_code, 400)

    def test_transcript_is_capped(self):
        from remy_api.llm import MAX_TRANSCRIPT_CHARS, Draft
        with mock.patch("remy_api.llm._parse", return_value=fake_response(Draft(title="t", body="b", tags=[]))) as p:
            self.client.post("/api/recipes/draft", json={"transcript": "a" * (MAX_TRANSCRIPT_CHARS + 500)})
        self.assertEqual(len(p.call_args.args[0]), MAX_TRANSCRIPT_CHARS)

    def test_refusal_is_422(self):
        with mock.patch("remy_api.llm._parse", return_value=fake_response(None, stop_reason="refusal")):
            r = self.client.post("/api/recipes/draft", json={"transcript": "x"})
        self.assertEqual(r.status_code, 422)

    def test_api_errors_map_to_status(self):
        req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        cases = [
            (anthropic.RateLimitError("slow", response=httpx.Response(429, request=req), body=None), 429),
            (anthropic.APIConnectionError(request=req), 502),
            (anthropic.InternalServerError("boom", response=httpx.Response(500, request=req), body=None), 502),
        ]
        for exc, status in cases:
            with mock.patch("remy_api.llm._parse", side_effect=exc):
                r = self.client.post("/api/recipes/draft", json={"transcript": "x"})
            self.assertEqual(r.status_code, status, exc)


if __name__ == "__main__":
    unittest.main()
