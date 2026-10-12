"""Speech-to-text for the AI block. Claude has no audio input, so audio goes to
a transcription provider first; the text then goes to llm.draft_recipe().

Provider: OpenAI's audio transcription endpoint (set OPENAI_API_KEY; model via
STT_MODEL, default whisper-1). Swap the body of transcribe() for Deepgram,
AssemblyAI, etc. if you'd rather hold a different key.
"""
import os

import requests

URL = "https://api.openai.com/v1/audio/transcriptions"
TIMEOUT = 120


class SttError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def enabled() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def transcribe(data: bytes, content_type: str, filename: str = "audio") -> str:
    model = os.environ.get("STT_MODEL", "whisper-1")
    try:
        r = requests.post(
            URL,
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            files={"file": (filename, data, content_type)},
            data={"model": model, "response_format": "json"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        raise SttError(f"could not reach the transcription service: {e.__class__.__name__}") from e
    if r.status_code == 429:
        raise SttError("transcription rate limited, try again in a minute", 429)
    if r.status_code >= 400:
        raise SttError(f"transcription failed ({r.status_code})")
    text = (r.json() or {}).get("text", "")
    if not isinstance(text, str) or not text.strip():
        raise SttError("no speech found in the audio", 422)
    return text.strip()
