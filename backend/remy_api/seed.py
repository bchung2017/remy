"""Seed the database with a starter recipe. Runs once, only when the table is empty."""
from . import db
from .models import Recipe, new_id

RECIPES = [
    dict(
        title="Ratatouille",
        text=(
            "1 eggplant, 2 zucchini, 2 yellow squash, 4 roma tomatoes, 1 red pepper, "
            "1 onion, 3 cloves garlic, thyme, olive oil, salt.\n\n"
            "Sweat the onion, pepper and garlic in oil until soft; add two chopped tomatoes "
            "and cook down to a sauce. Spread in a shallow dish.\n\n"
            "Slice everything else thin. Shingle the slices over the sauce in a tight spiral, "
            "alternating colors. Oil, salt, thyme. Cover with parchment.\n\n"
            "Bake at 275F for about 90 minutes, until the vegetables are tender but hold their shape."
        ),
        tags=Recipe.pack_tags(["vegetable", "bake"]),
    ),
]


def seed_if_empty() -> None:
    if Recipe.query.first() is not None:
        return
    for row in RECIPES:
        r = Recipe(title=row["title"], tags=row["tags"])
        r.set_blocks([{"id": new_id(), "type": "text", "text": row["text"]}])
        db.session.add(r)
    db.session.commit()
