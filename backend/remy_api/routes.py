"""HTTP routes for the remy API, all under /api."""
from flask import Blueprint, current_app, jsonify, request

from . import db
from .models import Item

api = Blueprint("api", __name__, url_prefix="/api")

# Mutable item fields: incoming camelCase JSON key -> model attribute.
ITEM_FIELDS = {"name": "name", "note": "note", "position": "position"}


def _field_error(key: str, value) -> str | None:
    """Validate a single item field value; return an error message or None."""
    if key == "name" and not (isinstance(value, str) and value.strip()):
        return "name must be a non-empty string"
    if key == "note" and value is not None and not isinstance(value, str):
        return "note must be a string or null"
    if key == "position" and (isinstance(value, bool) or not isinstance(value, int)):
        return "position must be an integer"
    return None


@api.get("/health")
def health():
    return {
        "status": "ok",
        "backend": current_app.config.get("REMY_BACKEND"),
        "schema": current_app.config.get("REMY_DB_SCHEMA"),
    }


@api.get("/items")
def list_items():
    rows = Item.query.order_by(Item.position, Item.id).all()
    return jsonify([i.to_dict() for i in rows])


@api.get("/items/<int:item_id>")
def get_item(item_id: int):
    item = db.session.get(Item, item_id)
    if item is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(item.to_dict())


@api.post("/items")
def create_item():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip() if isinstance(data.get("name"), str) else ""
    if not name:
        return jsonify({"error": "name is required"}), 400

    values = {}
    for key in ITEM_FIELDS:
        if key == "name" or key not in data:
            continue
        err = _field_error(key, data[key])
        if err:
            return jsonify({"error": err}), 400
        values[ITEM_FIELDS[key]] = data[key]

    if "position" not in values:
        max_pos = db.session.query(db.func.max(Item.position)).scalar()
        values["position"] = (max_pos or 0) + 1

    item = Item(name=name[:120], **values)
    db.session.add(item)
    db.session.commit()
    return jsonify(item.to_dict()), 201


@api.put("/items/<int:item_id>")
def update_item(item_id: int):
    item = db.session.get(Item, item_id)
    if item is None:
        return jsonify({"error": "not found"}), 404

    data = request.get_json(silent=True) or {}
    for key, attr in ITEM_FIELDS.items():
        if key not in data:
            continue
        err = _field_error(key, data[key])
        if err:
            return jsonify({"error": err}), 400
        value = data[key].strip()[:120] if key == "name" else data[key]
        setattr(item, attr, value)
    db.session.commit()
    return jsonify(item.to_dict())


@api.delete("/items/<int:item_id>")
def delete_item(item_id: int):
    item = db.session.get(Item, item_id)
    if item is None:
        return jsonify({"error": "not found"}), 404
    db.session.delete(item)
    db.session.commit()
    return "", 204
