"""SQLAlchemy models for remy. to_dict() emits camelCase keys so the frontend
can match the API shape 1:1.

A recipe is a notebook page: an ordered list of blocks stored as JSON.
Block shapes (all carry a client-or-server-assigned `id`):
  {"id", "type": "text",  "text": str}
  {"id", "type": "image", "asset": str, "caption": str}
  {"id", "type": "ai",    "text": str, "transcript": str}   (output, and the dictated input)
`body` is derived from the text of text/ai blocks so search and list previews
stay cheap; it is never written directly once blocks exist.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone

from . import db

BLOCK_TYPES = {"text", "image", "ai"}
MAX_BLOCKS = 200
MAX_BLOCK_TEXT = 20000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


def normalize_blocks(raw) -> list[dict]:
    """Validate an incoming block list; raise ValueError with a message."""
    if not isinstance(raw, list):
        raise ValueError("blocks must be a list")
    if len(raw) > MAX_BLOCKS:
        raise ValueError(f"at most {MAX_BLOCKS} blocks")
    out = []
    for b in raw:
        if not isinstance(b, dict) or b.get("type") not in BLOCK_TYPES:
            raise ValueError("each block needs a type of text, image or ai")
        bid = b.get("id")
        bid = bid if isinstance(bid, str) and 0 < len(bid) <= 40 else new_id()
        blk = {"id": bid, "type": b["type"]}
        if b["type"] in ("text", "ai"):
            text = b.get("text", "")
            if not isinstance(text, str):
                raise ValueError("text must be a string")
            blk["text"] = text[:MAX_BLOCK_TEXT]
        if b["type"] == "ai":
            tr = b.get("transcript", "")
            blk["transcript"] = tr[:MAX_BLOCK_TEXT] if isinstance(tr, str) else ""
        if b["type"] == "image":
            asset = b.get("asset")
            if not (isinstance(asset, str) and asset and len(asset) <= 40):
                raise ValueError("image blocks need an asset")
            blk["asset"] = asset
            cap = b.get("caption", "")
            blk["caption"] = cap[:400] if isinstance(cap, str) else ""
        out.append(blk)
    return out


def blocks_text(blocks: list[dict]) -> str:
    return "\n\n".join(b["text"].strip() for b in blocks if b["type"] in ("text", "ai") and b.get("text", "").strip())


class Recipe(db.Model):
    __tablename__ = "recipes"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    blocks = db.Column(db.Text, nullable=False, default="[]")      # JSON list, see module doc
    body = db.Column(db.Text, nullable=False, default="")          # derived: text of all text/ai blocks
    compiled = db.Column(db.Text, nullable=False, default="")      # the one clean recipe built from the cells (Recipe tab)
    compiled_hash = db.Column(db.String(64), nullable=False, default="")   # hash of the notes the recipe was generated from
    tags = db.Column(db.String(400), nullable=False, default="")  # ",a,b," — padded for LIKE matching
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    # ORM-side cascade (no passive_deletes): SQLite doesn't enforce FK cascades by default
    assets = db.relationship("Asset", backref="recipe", cascade="all, delete-orphan")

    @staticmethod
    def pack_tags(tags) -> str:
        """Normalize a list (or comma string) of tags to the padded storage form."""
        if isinstance(tags, str):
            tags = tags.split(",")
        seen, out = set(), []
        for t in tags or []:
            t = str(t).strip().lower()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
        return f",{','.join(out)}," if out else ""

    def tag_list(self) -> list[str]:
        return [t for t in self.tags.split(",") if t]

    def block_list(self) -> list[dict]:
        try:
            blocks = json.loads(self.blocks or "[]")
        except ValueError:
            blocks = []
        if not blocks and self.body:   # row written before blocks existed
            return [{"id": "legacy", "type": "text", "text": self.body}]
        return blocks

    def set_blocks(self, blocks: list[dict]) -> None:
        self.blocks = json.dumps(blocks)
        self.body = blocks_text(blocks)

    def notes_hash(self) -> str:
        """Fingerprint of what Generate reads: the text of text/voice cells, in order."""
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()

    def notes_changed(self) -> bool:
        """True when there is a generated recipe and the notes differ from what it was built from."""
        return bool(self.compiled) and self.notes_hash() != (self.compiled_hash or "")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "compiled": self.compiled or "",
            "notesChanged": self.notes_changed(),
            "blocks": self.block_list(),
            "tags": self.tag_list(),
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class Asset(db.Model):
    """An uploaded image, stored in the database so it survives Render's
    ephemeral disk. Small personal-scale; cap uploads in the route."""
    __tablename__ = "assets"

    id = db.Column(db.String(32), primary_key=True, default=new_id)
    recipe_id = db.Column(db.Integer, db.ForeignKey("recipes.id", ondelete="CASCADE"), nullable=True, index=True)
    content_type = db.Column(db.String(100), nullable=False)
    size = db.Column(db.Integer, nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    def to_dict(self) -> dict:
        return {"id": self.id, "contentType": self.content_type, "size": self.size, "url": f"/api/assets/{self.id}"}
