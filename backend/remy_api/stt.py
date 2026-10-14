"""Speech-to-text for the AI cell: audio chunks go to Groq's Whisper endpoint
(OpenAI-compatible multipart API). Set GROQ_API_KEY to enable; the model is
whisper-large-v3-turbo at $0.04 per hour of audio unless STT_MODEL overrides.
"""
import os

import requests

URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_MODEL = "whisper-large-v3-turbo"
TIMEOUT = 60


class SttError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def enabled() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))


def transcribe(data: bytes, content_type: str, filename: str = "chunk.wav", prompt: str = "") -> str:
    """Return the transcript text for one audio chunk ('' when nothing was said)."""
    form = {"model": os.environ.get("STT_MODEL", DEFAULT_MODEL), "language": "en", "response_format": "json", "temperature": "0"}
    if prompt:
        form["prompt"] = prompt[:500]   # carries context across chunks (names, spellings)
    try:
        r = requests.post(
            URL,
            headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
            files={"file": (filename, data, content_type)},
            data=form,
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        raise SttError(f"could not reach the transcription service: {e.__class__.__name__}") from e
    if r.status_code == 429:
        raise SttError("transcription rate limited, try again in a minute", 429)
    if r.status_code in (401, 403):
        raise SttError("transcription key rejected", 502)
    if r.status_code >= 400:
        raise SttError(f"transcription failed ({r.status_code})")
    text = (r.json() or {}).get("text", "")
    return text.strip() if isinstance(text, str) else ""
