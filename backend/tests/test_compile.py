"""Compile (all cells -> one recipe) and revise (highlight -> replacement), model mocked."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def make_client():
    tmp = tempfile.mkdtemp()
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tmp, "test.db")
    os.environ.pop("DB_SCHEMA", None)
    from remy_api import create_app
    return create_app().test_client()


def ok(parsed):
    return SimpleNamespace(stop_reason="end_turn", parsed_output=parsed)


@mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"})
class Compile(unittest.TestCase):
    def setUp(self):
        self.c = make_client()
        self.rid = self.c.post("/api/recipes", json={}).get_json()["id"]

    def test_compiles_text_and_ai_cells_in_order(self):
        from remy_api.llm import Draft
        self.c.put(f"/api/recipes/{self.rid}", json={"blocks": [
            {"type": "text", "text": "garlic and salt, pound it"},
            {"type": "image", "asset": "x"},
            {"type": "ai", "text": "actually 2 cloves", "transcript": "two cloves"},
            {"type": "text", "text": "   "},
        ]})
        draft = Draft(title="Aioli", body="Ingredients\n2 cloves garlic\n\nSteps\n1. Pound.", tags=["sauce"])
        with mock.patch("remy_api.llm._run", return_value=ok(draft)) as run:
            r = self.c.post(f"/api/recipes/{self.rid}/compile")
        self.assertEqual(r.status_code, 200, r.get_json())
        rec = r.get_json()
        self.assertEqual(rec["compiled"], draft.body)
        self.assertEqual(rec["title"], "Aioli")
        self.assertEqual(rec["tags"], ["sauce"])
        user = run.call_args.args[1]
        self.assertIn("--- note 1 ---\ngarlic and salt", user)
        self.assertIn("--- note 2 ---\nactually 2 cloves", user)
        self.assertNotIn("note 3", user)                       # blank cell skipped, image ignored
        self.assertNotIn("Title hint", user)                   # untitled: no hint
        self.assertEqual(self.c.get(f"/api/recipes/{self.rid}").get_json()["compiled"], draft.body)   # persisted

    def test_keeps_existing_title_and_passes_hint(self):
        from remy_api.llm import Draft
        self.c.put(f"/api/recipes/{self.rid}", json={"title": "Mom's aioli", "tags": ["family"], "blocks": [{"type": "text", "text": "x"}]})
        with mock.patch("remy_api.llm._run", return_value=ok(Draft(title="Other", body="b", tags=["z"]))) as run:
            rec = self.c.post(f"/api/recipes/{self.rid}/compile").get_json()
        self.assertIn("Title hint: Mom's aioli", run.call_args.args[1])
        self.assertEqual(rec["title"], "Mom's aioli")
        self.assertEqual(rec["tags"], ["family"])

    def test_no_text_is_400_and_missing_is_404(self):
        self.assertEqual(self.c.post(f"/api/recipes/{self.rid}/compile").status_code, 400)
        self.assertEqual(self.c.post("/api/recipes/999/compile").status_code, 404)

    def test_compiled_is_editable_and_searchable(self):
        r = self.c.put(f"/api/recipes/{self.rid}", json={"compiled": "Ingredients\nsaffron"})
        self.assertEqual(r.get_json()["compiled"], "Ingredients\nsaffron")
        self.assertEqual([x["id"] for x in self.c.get("/api/recipes?q=saffron").get_json()], [self.rid])
        self.assertEqual(self.c.put(f"/api/recipes/{self.rid}", json={"compiled": 3}).status_code, 400)


@mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"})
class Revise(unittest.TestCase):
    def setUp(self):
        self.c = make_client()

    def test_returns_replacement_for_span(self):
        from remy_api.llm import Revision
        text = "Steps\n1. Bake at 250F for 90 min."
        with mock.patch("remy_api.llm._run", return_value=ok(Revision(replacement="Bake at 275F for 90 min."))) as run:
            r = self.c.post("/api/recipes/revise", json={"text": text, "start": 9, "end": len(text), "instruction": "it's 275"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {"replacement": "Bake at 275F for 90 min."})
        user = run.call_args.args[1]
        self.assertIn("Highlighted span (characters 9-", user)
        self.assertIn("Instruction: it's 275", user)

    def test_validation(self):
        self.assertEqual(self.c.post("/api/recipes/revise", json={"text": "abc", "start": 2, "end": 1}).status_code, 400)
        self.assertEqual(self.c.post("/api/recipes/revise", json={"text": "abc", "start": 0, "end": 9}).status_code, 400)
        self.assertEqual(self.c.post("/api/recipes/revise", json={"start": 0, "end": 1}).status_code, 400)

    def test_off_without_key(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            self.assertEqual(self.c.post("/api/recipes/revise", json={"text": "abc", "start": 0, "end": 1}).status_code, 503)


class PromptsShareRules(unittest.TestCase):
    def test_generate_and_fix_carry_the_same_recipe_rules(self):
        from remy_api import llm
        for prompt in (llm.COMPILE_SYSTEM, llm.REVISE_SYSTEM):
            self.assertIn(llm.RECIPE_RULES, prompt)
            for must in ("## 🧂 Ingredients", "## 🔪 Steps", "## 📝 Notes", "as bought from the store", "never in the body"):
                self.assertIn(must, prompt)
        self.assertIn("Return ONLY the replacement", llm.REVISE_SYSTEM)
        self.assertNotIn("Return ONLY the replacement", llm.COMPILE_SYSTEM)


class OldDbGetsCompiled(unittest.TestCase):
    def test_column_added_at_boot(self):
        c = make_client()   # fresh db has it via create_all; the ADDED_COLUMNS path is covered by test_migration
        self.assertEqual(c.post("/api/recipes", json={}).get_json()["compiled"], "")


if __name__ == "__main__":
    unittest.main()
