"""Video cell: a YouTube URL -> the video's caption track as plain text.

No API key: youtube-transcript-api reads the captions YouTube already made
(manual or auto-generated), so nothing is transcribed here. YouTube blocks most
cloud IPs, Render's included; set YOUTUBE_PROXY_URL (an http(s) proxy, e.g. a
rotating residential one) to route the requests through it.
"""
import os
import re

from youtube_transcript_api import (
    CouldNotRetrieveTranscript,
    InvalidVideoId,
    IpBlocked,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)
from youtube_transcript_api.proxies import GenericProxyConfig

MAX_TEXT = 40000   # ~45 min of speech; longer videos are cut
ENGLISH = ["en", "en-US", "en-GB", "en-CA", "en-AU"]
_ID = re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/|live/|v/)|youtu\.be/)([A-Za-z0-9_-]{11})")


class VideoError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def video_id(url: str) -> str | None:
    m = _ID.search(url.strip())
    return m.group(1) if m else None


def _api() -> YouTubeTranscriptApi:
    proxy = os.environ.get("YOUTUBE_PROXY_URL")
    return YouTubeTranscriptApi(proxy_config=GenericProxyConfig(http_url=proxy, https_url=proxy) if proxy else None)


def transcript(vid: str) -> str:
    """English captions if there are any, else the first track in whatever language."""
    try:
        tracks = _api().list(vid)
        try:
            track = tracks.find_transcript(ENGLISH)
        except NoTranscriptFound:
            track = next(iter(tracks), None)
            if track is None:
                raise VideoError("this video has no captions", 422)
        snippets = track.fetch().snippets
    except (TranscriptsDisabled, NoTranscriptFound):
        raise VideoError("this video has no captions", 422)
    except (VideoUnavailable, InvalidVideoId):
        raise VideoError("video not found or unavailable", 404)
    except (RequestBlocked, IpBlocked):
        raise VideoError("YouTube is blocking this server; set YOUTUBE_PROXY_URL", 502)
    except CouldNotRetrieveTranscript as e:
        raise VideoError(f"could not get captions ({e.__class__.__name__})", 502)
    text = " ".join(" ".join(s.text.split()) for s in snippets if s.text.strip())
    return text[:MAX_TEXT]
