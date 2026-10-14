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


COMPILE_SYSTEM = (
    "You are given several notes a cook jotted or dictated about ONE recipe, in the "
    "order they were written. They overlap, repeat, correct each other and ramble. "
    "Produce the single clean recipe they describe. Later notes win over earlier ones "
    "when they conflict. Keep the cook's quantities, ingredients, steps and wording; "
    "remove repetition and filler. Do not invent ingredients, amounts or steps that "
    "were not in the notes. Write the body as plain text, not markdown: an 'Ingredients' "
    "line, one ingredient per line, a blank line, then 'Steps' with numbered lines, and "
    "optionally a blank line and a short 'Notes' section for tips the cook gave. If a "
    "title hint is given, keep it unless it is empty or clearly wrong. Tags: 1 to 4 short "
    "lowercase words for the dish type or main ingredient."
)

REVISE_SYSTEM = (
    "You edit one highlighted span inside a plain-text recipe. You get the full recipe "
    "for context, the exact highlighted span, and the cook's instruction (which may be "
    "empty: then just tidy the span, fixing dictation errors, wording and formatting). "
    "Return ONLY the replacement for the highlighted span, in the same plain-text style "
    "as its surroundings, nothing else. Do not rewrite text outside the span. Do not "
    "invent ingredients or steps the cook did not ask for."
)


class Draft(BaseModel):
    title: str = Field(description="Short recipe name.")
    body: str = Field(description="Plain-text ingredients and numbered steps.")
    tags: list[str] = Field(description="1-4 short lowercase tags.")


class Revision(BaseModel):
    replacement: str = Field(description="Replacement text for the highlighted span only.")


def enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _run(system: str, user: str, schema, max_tokens: int = 2000):
    client = anthropic.Anthropic()
    return client.messages.parse(
        model=MODEL,
        max_tokens=max_tokens,
        output_config={"effort": "low"},
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=schema,
    )


def _parse(transcript: str, title_hint: str):
    user = f"Title hint: {title_hint}\n\n" if title_hint else ""
    user += f"Transcript:\n{transcript}"
    return _run(SYSTEM, user, Draft)


def _check(response):
    if response.stop_reason == "refusal":
        raise ValueError("The model declined to format this.")
    if response.parsed_output is None:
        raise ValueError("The model returned no draft.")
    return response.parsed_output


def draft_recipe(transcript: str, title_hint: str = "") -> Draft:
    """Raises anthropic.APIError on API failure; ValueError on a refusal or bad output."""
    return _check(_parse(transcript[:MAX_TRANSCRIPT_CHARS], title_hint.strip()[:200]))


MAX_NOTES_CHARS = 24000


def compile_recipe(notes: list[str], title_hint: str = "") -> Draft:
    """Merge every note on a page into one clean recipe."""
    user = f"Title hint: {title_hint}\n\n" if title_hint else ""
    body = "\n\n".join(f"--- note {i + 1} ---\n{n.strip()}" for i, n in enumerate(notes) if n.strip())
    user += f"Notes:\n{body[:MAX_NOTES_CHARS]}"
    return _check(_run(COMPILE_SYSTEM, user, Draft, max_tokens=3000))


def revise_span(text: str, start: int, end: int, instruction: str = "") -> str:
    """Return a replacement for text[start:end] following the instruction."""
    span = text[start:end]
    user = (
        f"Full recipe:\n{text[:MAX_NOTES_CHARS]}\n\n"
        f"Highlighted span (characters {start}-{end}):\n{span}\n\n"
        f"Instruction: {instruction.strip() or '(none: tidy the span)'}"
    )
    return _check(_run(REVISE_SYSTEM, user, Revision, max_tokens=1500)).replacement
