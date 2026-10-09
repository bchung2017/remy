"""SQLAlchemy models for remy. to_dict() emits camelCase keys so the frontend
can match the API shape 1:1."""
from datetime import datetime, timezone

from . import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Recipe(db.Model):
    __tablename__ = "recipes"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False, default="")      # freeform text
    tags = db.Column(db.String(400), nullable=False, default="")  # ",a,b," — padded for LIKE matching
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

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

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "tags": self.tag_list(),
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
