"""Seed the database with starter rows. Runs once, only when the table is empty."""
from . import db
from .models import Item

ITEMS = [
    dict(name="first item", note="replace me with real data", position=0),
]


def seed_if_empty() -> None:
    if Item.query.first() is not None:
        return
    db.session.add_all(Item(**row) for row in ITEMS)
    db.session.commit()
