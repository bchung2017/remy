"""Turn a spoken recipe dump into a tidy draft with Claude (Haiku 5.5).

Off unless ANTHROPIC_API_KEY is set; the route reports that as 503 and the
frontend hides the button. Output stays plain text so the freeform body needs
no markdown renderer.
"""
import os

import anthropic
from pydantic import BaseModel, Field

MODEL = "claude-haiku-5-5"
MAX_TRANSCRIPT_CHARS = 8000   # bounds cost per request; a recipe never needs more

SYSTEM = (
    "You turn a cook's spoken, rambling recipe dump into a clean recipe. "
    "Keep the cook's own quantities, ingredients, steps and wording; fix dictation "
    "errors and remove filler. Do not invent ingredients, amounts or steps that were "
    "not said. Write the body as plain text, not markdown: an 'Ingredients' line, one "
    "ingredient per line, a blank line, then 'Steps' with numbered lines. If a title "
    "hint is given, keep it unless it is empty or clearly wrong. Tags: 1 to 4 short "
    "lowercase words for the dish type or main ingredient."
)


class Draft(BaseModel):
    title: str = Field(description="Short recipe name.")
    body: str = Field(description="Plain-text ingredients and numbered steps.")
    tags: list[str] = Field(description="1-4 short lowercase tags.")


def enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _parse(transcript: str, title_hint: str):
    client = anthropic.Anthropic()
    user = f"Title hint: {title_hint}\n\n" if title_hint else ""
    user += f"Transcript:\n{transcript}"
    return client.messages.parse(
        model=MODEL,
        max_tokens=2000,
        output_config={"effort": "low"},
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_format=Draft,
    )


def draft_recipe(transcript: str, title_hint: str = "") -> Draft:
    """Raises anthropic.APIError on API failure; ValueError on a refusal or bad output."""
    response = _parse(transcript[:MAX_TRANSCRIPT_CHARS], title_hint.strip()[:200])
    if response.stop_reason == "refusal":
        raise ValueError("The model declined to format this.")
    if response.parsed_output is None:
        raise ValueError("The model returned no draft.")
    return response.parsed_output
