"""HTTP routes for the remy API, all under /api."""
import anthropic
from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import or_

from . import db, llm
from .models import Recipe

api = Blueprint("api", __name__, url_prefix="/api")

SORTS = {
    "updated": (Recipe.updated_at.desc(), Recipe.id.desc()),
    "created": (Recipe.created_at.desc(), Recipe.id.desc()),
    "title": (db.func.lower(Recipe.title), Recipe.id),
}


def _validate(data: dict, partial: bool) -> tuple[dict, str | None]:
    """Pull title/body/tags out of a JSON body; return (values, error)."""
    values = {}
    if "title" in data or not partial:
        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            return {}, "title is required"
        values["title"] = title.strip()[:200]
    if "body" in data:
        if data["body"] is not None and not isinstance(data["body"], str):
            return {}, "body must be a string"
        values["body"] = data["body"] or ""
    if "tags" in data:
        tags = data["tags"]
        if tags is not None and not isinstance(tags, (list, str)):
            return {}, "tags must be a list of strings"
        values["tags"] = Recipe.pack_tags(tags)[:400]
    return values, None


@api.get("/health")
def health():
    return {
        "status": "ok",
        "backend": current_app.config.get("REMY_BACKEND"),
        "schema": current_app.config.get("REMY_DB_SCHEMA"),
        "draft": llm.enabled(),
    }


@api.post("/recipes/draft")
def draft_recipe():
    """Tidy a dictated/raw transcript into {title, body, tags} without saving it."""
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


@api.get("/recipes")
def list_recipes():
    q = Recipe.query
    search = (request.args.get("q") or "").strip()
    if search:
        like = f"%{search}%"
        q = q.filter(or_(Recipe.title.ilike(like), Recipe.body.ilike(like), Recipe.tags.ilike(like)))
    tag = (request.args.get("tag") or "").strip().lower()
    if tag:
        q = q.filter(Recipe.tags.like(f"%,{tag},%"))
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


@api.post("/recipes")
def create_recipe():
    values, err = _validate(request.get_json(silent=True) or {}, partial=False)
    if err:
        return jsonify({"error": err}), 400
    recipe = Recipe(**values)
    db.session.add(recipe)
    db.session.commit()
    return jsonify(recipe.to_dict()), 201


@api.put("/recipes/<int:recipe_id>")
def update_recipe(recipe_id: int):
    recipe = db.session.get(Recipe, recipe_id)
    if recipe is None:
        return jsonify({"error": "not found"}), 404
    values, err = _validate(request.get_json(silent=True) or {}, partial=True)
    if err:
        return jsonify({"error": err}), 400
    for attr, value in values.items():
        setattr(recipe, attr, value)
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
