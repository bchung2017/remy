"""HTTP routes for the remy API, all under /api."""
from datetime import datetime, timezone

import anthropic
from flask import Blueprint, Response, current_app, jsonify, request
from sqlalchemy import or_

from . import db, llm, stt, youtube
from .models import MAX_STARS, NOTE_TYPES, Asset, Recipe, new_id, normalize_blocks

api = Blueprint("api", __name__, url_prefix="/api")

SORTS = {
    "updated": (Recipe.updated_at.desc(), Recipe.id.desc()),
    "created": (Recipe.created_at.desc(), Recipe.id.desc()),
    "title": (db.func.lower(Recipe.title), Recipe.id),
    "starred": (Recipe.starred_at.desc(), Recipe.updated_at.desc(), Recipe.id.desc()),
}
UNTITLED = "Untitled"
MAX_ASSET_BYTES = 8 * 1024 * 1024


def _validate(data: dict, partial: bool) -> tuple[dict, list | None, str | None]:
    """Pull title/tags/blocks (or legacy body) out of a JSON body.
    Returns (column values, blocks or None, error)."""
    values, blocks = {}, None
    if "title" in data or not partial:
        title = data.get("title", UNTITLED if not partial else None)
        if not isinstance(title, str):
            return {}, None, "title must be a string"
        values["title"] = title.strip()[:200] or UNTITLED
    if "tags" in data:
        tags = data["tags"]
        if tags is not None and not isinstance(tags, (list, str)):
            return {}, None, "tags must be a list of strings"
        values["tags"] = Recipe.pack_tags(tags)[:400]
    if "compiled" in data:
        if data["compiled"] is not None and not isinstance(data["compiled"], str):
            return {}, None, "compiled must be a string"
        values["compiled"] = (data["compiled"] or "")[:60000]
    if "blocks" in data:
        try:
            blocks = normalize_blocks(data["blocks"])
        except ValueError as e:
            return {}, None, str(e)
    elif "body" in data:   # legacy freeform body -> one text block
        if data["body"] is not None and not isinstance(data["body"], str):
            return {}, None, "body must be a string"
        blocks = [{"id": new_id(), "type": "text", "text": data["body"]}] if data["body"] else []
    return values, blocks, None


def _prune_assets(recipe: Recipe) -> None:
    """Drop this recipe's uploads that no block references any more."""
    used = {b.get("asset") for b in recipe.block_list() if b.get("asset")}
    for a in list(recipe.assets):
        if a.id not in used:
            db.session.delete(a)


@api.get("/health")
def health():
    return {
        "status": "ok",
        "backend": current_app.config.get("REMY_BACKEND"),
        "schema": current_app.config.get("REMY_DB_SCHEMA"),
        "draft": llm.enabled(),
        "voice": stt.enabled(),
    }


@api.get("/recipes")
def list_recipes():
    q = Recipe.query
    search = (request.args.get("q") or "").strip()
    if search:
        like = f"%{search}%"
        q = q.filter(or_(Recipe.title.ilike(like), Recipe.body.ilike(like), Recipe.compiled.ilike(like), Recipe.tags.ilike(like)))
    tag = (request.args.get("tag") or "").strip().lower()
    if tag:
        q = q.filter(Recipe.tags.like(f"%,{tag},%"))
    if request.args.get("starred"):
        q = q.filter(Recipe.starred_at.isnot(None))
    q = q.order_by(*SORTS.get(request.args.get("sort", "updated"), SORTS["updated"]))
    return jsonify([r.to_dict() for r in q.all()])


@api.get("/tags")
def list_tags():
    counts: dict[str, int] = {}
    for (tags,) in db.session.query(Recipe.tags).filter(Recipe.tags != "").all():
        for t in tags.split(","):
            if t:
                counts[t] = counts.get(t, 0) + 1
    return jsonify([{"tag": t, "count": n} for t, n in sorted(counts.items())])


@api.get("/recipes/<int:recipe_id>")
def get_recipe(recipe_id: int):
    recipe = db.session.get(Recipe, recipe_id)
    if recipe is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(recipe.to_dict())


# --- stars: up to MAX_STARS pages sit on the pass; a fourth star demotes the oldest ---

@api.post("/recipes/<int:recipe_id>/star")
def star_recipe(recipe_id: int):
    """Star a page. Over the limit, the oldest-starred page is demoted (never a reject).
    Returns {recipe, demoted: {id, title} | null}."""
    recipe = db.session.get(Recipe, recipe_id)
    if recipe is None:
        return jsonify({"error": "not found"}), 404
    demoted = None
    if recipe.starred_at is None:
        recipe.starred_at = datetime.now(timezone.utc)
        others = (Recipe.query.filter(Recipe.starred_at.isnot(None), Recipe.id != recipe.id)
                  .order_by(Recipe.starred_at.asc(), Recipe.id.asc()).all())
        for old in others[: max(0, len(others) + 1 - MAX_STARS)]:
            old.starred_at = None
            demoted = {"id": old.id, "title": old.title}
        db.session.commit()
    return jsonify({"recipe": recipe.to_dict(), "demoted": demoted})


@api.delete("/recipes/<int:recipe_id>/star")
def unstar_recipe(recipe_id: int):
    recipe = db.session.get(Recipe, recipe_id)
    if recipe is None:
        return jsonify({"error": "not found"}), 404
    recipe.starred_at = None
    db.session.commit()
    return jsonify({"recipe": recipe.to_dict(), "demoted": None})


@api.post("/recipes")
def create_recipe():
    values, blocks, err = _validate(request.get_json(silent=True) or {}, partial=False)
    if err:
        return jsonify({"error": err}), 400
    recipe = Recipe(**values)
    recipe.set_blocks(blocks or [])
    db.session.add(recipe)
    db.session.commit()
    return jsonify(recipe.to_dict()), 201


@api.put("/recipes/<int:recipe_id>")
def update_recipe(recipe_id: int):
    recipe = db.session.get(Recipe, recipe_id)
    if recipe is None:
        return jsonify({"error": "not found"}), 404
    values, blocks, err = _validate(request.get_json(silent=True) or {}, partial=True)
    if err:
        return jsonify({"error": err}), 400
    for attr, value in values.items():
        setattr(recipe, attr, value)
    if blocks is not None:
        recipe.set_blocks(blocks)
        _prune_assets(recipe)
    db.session.commit()
    return jsonify(recipe.to_dict())


@api.delete("/recipes/<int:recipe_id>")
def delete_recipe(recipe_id: int):
    recipe = db.session.get(Recipe, recipe_id)
    if recipe is None:
        return jsonify({"error": "not found"}), 404
    db.session.delete(recipe)
    db.session.commit()
    return "", 204


# --- assets (images, audio) --------------------------------------------------

def _read_upload(kinds: tuple[str, ...]):
    """Pull the multipart `file` field; return (data, content_type, filename) or an error response."""
    f = request.files.get("file")
    if f is None or not f.filename:
        return None, (jsonify({"error": "file is required"}), 400)
    ctype = (f.mimetype or "").split(";")[0].strip().lower()
    if not ctype.startswith(kinds):
        return None, (jsonify({"error": f"file must be {' or '.join(k.rstrip('/') for k in kinds)}"}), 415)
    data = f.read(MAX_ASSET_BYTES + 1)
    if len(data) > MAX_ASSET_BYTES:
        return None, (jsonify({"error": f"file larger than {MAX_ASSET_BYTES // (1024 * 1024)} MB"}), 413)
    if not data:
        return None, (jsonify({"error": "file is empty"}), 400)
    return (data, ctype, f.filename), None


@api.post("/recipes/<int:recipe_id>/assets")
def upload_asset(recipe_id: int):
    """Upload an image for an image block. The client then PUTs a block referencing the id."""
    recipe = db.session.get(Recipe, recipe_id)
    if recipe is None:
        return jsonify({"error": "not found"}), 404
    up, errresp = _read_upload(("image/",))
    if errresp:
        return errresp
    data, ctype, _ = up
    asset = Asset(recipe_id=recipe.id, content_type=ctype, size=len(data), data=data)
    db.session.add(asset)
    db.session.commit()
    return jsonify(asset.to_dict()), 201


@api.get("/assets/<asset_id>")
def get_asset(asset_id: str):
    asset = db.session.get(Asset, asset_id)
    if asset is None:
        return jsonify({"error": "not found"}), 404
    return Response(asset.data, content_type=asset.content_type,
                    headers={"Cache-Control": "private, max-age=31536000, immutable"})


# --- AI cell: audio chunk -> transcript (Groq Whisper) ------------------------

MAX_CHUNK_BYTES = 10 * 1024 * 1024


@api.post("/transcribe")
def transcribe_chunk():
    """One recorded chunk (multipart `file`, wav/webm/m4a) -> {text}. The client
    cuts a dictation into chunks at pauses and posts each as it closes, so the
    transcript builds while the cook is still talking. Optional `prompt` form
    field carries the previous chunk's text for continuity."""
    if not stt.enabled():
        return jsonify({"error": "transcription is off: GROQ_API_KEY is not set"}), 503
    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify({"error": "file is required"}), 400
    ctype = (f.mimetype or "").split(";")[0].strip().lower()
    if not (ctype.startswith("audio/") or ctype.startswith("video/")):
        return jsonify({"error": "file must be audio"}), 415
    data = f.read(MAX_CHUNK_BYTES + 1)
    if len(data) > MAX_CHUNK_BYTES:
        return jsonify({"error": "chunk larger than 10 MB"}), 413
    if not data:
        return jsonify({"error": "file is empty"}), 400
    try:
        text = stt.transcribe(data, ctype, f.filename, request.form.get("prompt", ""))
    except stt.SttError as e:
        return jsonify({"error": str(e)}), e.status
    return jsonify({"text": text})


@api.post("/video/transcript")
def video_transcript():
    """{url} -> {url, text}: the YouTube video's captions, for a video cell.
    Nothing is saved; the client writes the result into a `video` block."""
    data = request.get_json(silent=True) or {}
    url = data.get("url")
    vid = youtube.video_id(url) if isinstance(url, str) else None
    if not vid:
        return jsonify({"error": "paste a YouTube video link"}), 400
    try:
        text = youtube.transcript(vid)
    except youtube.VideoError as e:
        return jsonify({"error": str(e)}), e.status
    return jsonify({"url": f"https://www.youtube.com/watch?v={vid}", "text": text})


# --- Recipe tab: all cells -> one clean recipe; highlight -> revise ------------

def _llm_errors(fn):
    """Run fn(); map SDK / refusal errors to a JSON response, else return (result, None)."""
    try:
        return fn(), None
    except anthropic.RateLimitError:
        return None, (jsonify({"error": "rate limited, try again in a minute"}), 429)
    except anthropic.APIConnectionError:
        return None, (jsonify({"error": "could not reach the model"}), 502)
    except anthropic.APIStatusError as e:
        return None, (jsonify({"error": f"model error ({e.status_code})"}), 502)
    except ValueError as e:
        return None, (jsonify({"error": str(e)}), 422)


@api.post("/recipes/<int:recipe_id>/compile")
def compile_recipe(recipe_id: int):
    """Read every text/voice/video cell in order and write one clean recipe into `compiled`.
    An untitled page takes the drafted title; empty tags take the drafted tags."""
    if not llm.enabled():
        return jsonify({"error": "drafting is off: ANTHROPIC_API_KEY is not set"}), 503
    recipe = db.session.get(Recipe, recipe_id)
    if recipe is None:
        return jsonify({"error": "not found"}), 404
    notes = [b["text"] for b in recipe.block_list() if b["type"] in NOTE_TYPES and b.get("text", "").strip()]
    if not notes:
        return jsonify({"error": "no text to compile yet"}), 400
    title_hint = "" if recipe.title == UNTITLED else recipe.title
    draft, errresp = _llm_errors(lambda: llm.compile_recipe(notes, title_hint))
    if errresp:
        return errresp
    recipe.compiled = draft.body.strip()[:60000]
    recipe.compiled_hash = recipe.notes_hash()
    if recipe.title == UNTITLED and draft.title.strip():
        recipe.title = draft.title.strip()[:200]
    if not recipe.tags:
        recipe.tags = Recipe.pack_tags(draft.tags)[:400]
    db.session.commit()
    return jsonify(recipe.to_dict())


@api.post("/recipes/revise")
def revise_recipe():
    """{text, start, end, instruction?} -> {replacement} for text[start:end]. Nothing saved."""
    if not llm.enabled():
        return jsonify({"error": "drafting is off: ANTHROPIC_API_KEY is not set"}), 503
    data = request.get_json(silent=True) or {}
    text, start, end = data.get("text"), data.get("start"), data.get("end")
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "text is required"}), 400
    if not (isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text)):
        return jsonify({"error": "start/end must select a span of the text"}), 400
    instruction = data.get("instruction") if isinstance(data.get("instruction"), str) else ""
    replacement, errresp = _llm_errors(lambda: llm.revise_span(text, start, end, instruction))
    if errresp:
        return errresp
    return jsonify({"replacement": replacement})


# --- AI cell: transcript -> Haiku draft ---------------------------------------

@api.post("/recipes/draft")
def draft_recipe():
    """Format a dictated/typed transcript into {title, body, tags}. Nothing is
    saved; the client writes the result into an `ai` block and PUTs the page."""
    if not llm.enabled():
        return jsonify({"error": "drafting is off: ANTHROPIC_API_KEY is not set"}), 503
    data = request.get_json(silent=True) or {}
    transcript = data.get("transcript")
    if not isinstance(transcript, str) or not transcript.strip():
        return jsonify({"error": "transcript is required"}), 400
    title_hint = data.get("title") if isinstance(data.get("title"), str) else ""
    try:
        draft = llm.draft_recipe(transcript.strip(), title_hint)
    except anthropic.RateLimitError:
        return jsonify({"error": "rate limited, try again in a minute"}), 429
    except anthropic.APIConnectionError:
        return jsonify({"error": "could not reach the model"}), 502
    except anthropic.APIStatusError as e:
        return jsonify({"error": f"model error ({e.status_code})"}), 502
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    return jsonify({
        "title": draft.title.strip()[:200],
        "body": draft.body.strip(),
        "tags": [t for t in Recipe.pack_tags(draft.tags).split(",") if t],
    })
