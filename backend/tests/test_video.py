"""Video cell: POST /api/video/transcript, the caption fetcher, and video blocks in Generate. YouTube mocked."""
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


def track(*texts):
    return SimpleNamespace(fetch=lambda: SimpleNamespace(snippets=[SimpleNamespace(text=t) for t in texts]))


class VideoId(unittest.TestCase):
    def test_url_shapes(self):
        from remy_api.youtube import video_id
        for url in (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://m.youtube.com/watch?feature=share&v=dQw4w9WgXcQ&t=30",
            "https://youtu.be/dQw4w9WgXcQ?si=abc",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
            "https://www.youtube.com/live/dQw4w9WgXcQ",
            "  youtube.com/watch?v=dQw4w9WgXcQ  ",
        ):
            self.assertEqual(video_id(url), "dQw4w9WgXcQ", url)
        for url in ("https://vimeo.com/123", "dQw4w9WgXcQ", "https://www.youtube.com/@chef", ""):
            self.assertIsNone(video_id(url), url)


class Fetcher(unittest.TestCase):
    def test_prefers_english_and_flattens_lines(self):
        from remy_api import youtube
        tracks = mock.MagicMock()
        tracks.find_transcript.return_value = track("two cloves\ngarlic", "  ", "[Music]  salt")
        with mock.patch("remy_api.youtube._api", return_value=mock.Mock(list=mock.Mock(return_value=tracks))):
            self.assertEqual(youtube.transcript("dQw4w9WgXcQ"), "two cloves garlic [Music] salt")
        self.assertEqual(tracks.find_transcript.call_args.args[0][0], "en")

    def test_falls_back_to_any_language(self):
        from youtube_transcript_api import NoTranscriptFound
        from remy_api import youtube
        tracks = mock.MagicMock()
        tracks.find_transcript.side_effect = NoTranscriptFound("vid", ["en"], None)
        tracks.__iter__.return_value = iter([track("dos dientes de ajo")])
        with mock.patch("remy_api.youtube._api", return_value=mock.Mock(list=mock.Mock(return_value=tracks))):
            self.assertEqual(youtube.transcript("dQw4w9WgXcQ"), "dos dientes de ajo")

    def test_errors_map_to_status(self):
        from youtube_transcript_api import IpBlocked, TranscriptsDisabled, VideoUnavailable
        from remy_api import youtube
        for exc, status in ((TranscriptsDisabled("v"), 422), (VideoUnavailable("v"), 404), (IpBlocked("v"), 502)):
            with mock.patch("remy_api.youtube._api", return_value=mock.Mock(list=mock.Mock(side_effect=exc))):
                with self.assertRaises(youtube.VideoError) as cm:
                    youtube.transcript("dQw4w9WgXcQ")
                self.assertEqual(cm.exception.status, status)

    def test_proxy_from_env(self):
        from remy_api import youtube
        with mock.patch.dict(os.environ, {"YOUTUBE_PROXY_URL": "http://u:p@proxy:8080"}):
            with mock.patch("remy_api.youtube.YouTubeTranscriptApi") as cls:
                youtube._api()
            cfg = cls.call_args.kwargs["proxy_config"]
            self.assertEqual(cfg.to_requests_dict(), {"http": "http://u:p@proxy:8080", "https": "http://u:p@proxy:8080"})


class Route(unittest.TestCase):
    def setUp(self):
        self.c = make_client()

    def test_returns_canonical_url_and_text(self):
        with mock.patch("remy_api.youtube.transcript", return_value="pound the garlic") as t:
            r = self.c.post("/api/video/transcript", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "text": "pound the garlic"})
        t.assert_called_once_with("dQw4w9WgXcQ")

    def test_bad_link_and_errors(self):
        from remy_api.youtube import VideoError
        self.assertEqual(self.c.post("/api/video/transcript", json={}).status_code, 400)
        self.assertEqual(self.c.post("/api/video/transcript", json={"url": "https://vimeo.com/1"}).status_code, 400)
        with mock.patch("remy_api.youtube.transcript", side_effect=VideoError("this video has no captions", 422)):
            r = self.c.post("/api/video/transcript", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
        self.assertEqual((r.status_code, r.get_json()["error"]), (422, "this video has no captions"))


@mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"})
class VideoBlocks(unittest.TestCase):
    def test_saved_and_read_by_generate(self):
        from remy_api.llm import Draft
        c = make_client()
        rid = c.post("/api/recipes", json={}).get_json()["id"]
        long = "word " * 6000   # 30k chars: over the text-cell cap, under the video cap
        r = c.put(f"/api/recipes/{rid}", json={"blocks": [
            {"id": "v", "type": "video", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "text": long},
            {"id": "t", "type": "text", "text": "less salt"},
        ]})
        self.assertEqual(r.status_code, 200, r.get_json())
        v = r.get_json()["blocks"][0]
        self.assertEqual((v["type"], v["url"], len(v["text"])), ("video", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", len(long)))
        draft = Draft(title="t", body="b", tags=[])
        with mock.patch("remy_api.llm._run", return_value=SimpleNamespace(stop_reason="end_turn", parsed_output=draft)) as run:
            self.assertEqual(c.post(f"/api/recipes/{rid}/compile").status_code, 200)
        user = run.call_args.args[1]
        self.assertIn("--- note 1 ---\nword word", user)
        self.assertIn("--- note 2 ---\nless salt", user)


if __name__ == "__main__":
    unittest.main()
