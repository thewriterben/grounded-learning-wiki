"""Tests for glw.py against the sourdough example and broken copies of it. Run: python -m unittest -q"""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXAMPLE = HERE.parent / "example"
sys.path.insert(0, str(HERE.parent / "skill" / "grounded-learning-wiki"))
import glw  # noqa: E402


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = glw.main([str(a) for a in argv])
    return code, out.getvalue()


def resolve(root, question, *extra):
    code, out = run("resolve", "--root", root, *extra, "--", question)
    return json.loads(out)


class Copy:
    """A throwaway copy of the example wiki."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "wiki-root"
        shutil.copytree(EXAMPLE, self.root)
        return self.root

    def __exit__(self, *exc):
        self.tmp.cleanup()


def append(path, text):
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


class Example(unittest.TestCase):
    def test_example_is_clean(self):
        code, out = run("check", "--root", EXAMPLE, "--strict")
        self.assertEqual(code, 0, out)
        self.assertIn("0 error(s), 0 warning(s)", out)

    def test_typo_is_repaired_and_reported(self):
        r = resolve(EXAMPLE, "When does a levian peak?")
        self.assertEqual(r["status"], "resolved")
        self.assertEqual(r["corrections"], [{"from": "levian", "to": "levain"}])
        self.assertEqual(r["entity"], "wiki/concepts/levain.md")

    def test_digit_token_is_offered_never_fuzzed(self):
        r = resolve(EXAMPLE, "What is the ash content of T60 flour?")
        self.assertEqual(r["status"], "needs_clarification")
        self.assertEqual(r["corrections"], [])
        self.assertIn("t55", r["ask"][0])
        self.assertIn("t65", r["ask"][0])
        self.assertIsNone(r["entity"])

    def test_versioned_subject_asks_for_version(self):
        r = resolve(EXAMPLE, "What hydration is the house loaf?")
        self.assertEqual(r["status"], "needs_clarification")
        self.assertIn("version", r["ask"][0])
        r = resolve(EXAMPLE, "house loaf v2 hydration")
        self.assertEqual(r["status"], "resolved")

    def test_partial_match_is_offered_not_chosen(self):
        r = resolve(EXAMPLE, "What is rye flour?")
        self.assertEqual(r["status"], "needs_clarification")
        self.assertIsNone(r["entity"])
        self.assertEqual(sorted(r["offered"]), ["T55 flour", "T65 flour"])

    def test_alias_finds_entity(self):
        r = resolve(EXAMPLE, "How do I feed my starter?")
        self.assertEqual(r["entity"], "wiki/concepts/levain.md")

    def test_unknown_word_is_a_gap_until_synonym_applied(self):
        self.assertEqual(resolve(EXAMPLE, "What is leaven?")["status"], "gap")
        with Copy() as root:
            toml = root / "glw.toml"
            toml.write_text(toml.read_text(encoding="utf-8").replace(
                '"sour dough" = "sourdough"', '"sour dough" = "sourdough"\n"leaven" = "levain"'), encoding="utf-8")
            r = resolve(root, "What is leaven?")
            self.assertEqual(r["status"], "resolved")
            self.assertEqual(r["entity"], "wiki/concepts/levain.md")

    def test_gap_recorded_once_for_two_wordings(self):
        with Copy() as root:
            a = resolve(root, "croissant lamination?", "--record-gap")
            b = resolve(root, "lamination of a croissant", "--record-gap")
            self.assertEqual(a["status"], "gap")
            self.assertEqual(a["gap_page"], b["gap_page"])
            self.assertTrue((root / a["gap_page"]).is_file())
            code, out = run("gaps", "--root", root)
            self.assertIn("2 gap(s)", out)

    def test_status_commands(self):
        self.assertEqual(run("learn-status", "--root", EXAMPLE, "--strict")[0], 0)
        code, out = run("proposals", "--root", EXAMPLE)
        self.assertEqual(code, 0)
        self.assertIn("1 pending, 1 rejected", out)
        code, out = run("gaps", "--root", EXAMPLE)
        self.assertIn("DUE", out)

    def test_question_about_two_subjects_returns_both(self):
        r = resolve(EXAMPLE, "difference between T55 and T65 flour")
        self.assertEqual(r["status"], "resolved")
        self.assertEqual(r["entities"], ["wiki/entities/t55-flour.md", "wiki/entities/t65-flour.md"])
        self.assertIsNone(r["entity"])

    def test_two_pages_with_the_same_name_ask_back(self):
        with Copy() as root:
            (root / "wiki/concepts/yeast-starter.md").write_text(
                "---\ntitle: Yeast starter\naliases: [starter]\n---\n# Yeast starter\n", encoding="utf-8")
            r = resolve(root, "How do I feed my starter?")
            self.assertEqual(r["status"], "needs_clarification")
            self.assertIn("Levain", r["ask"][0])
            self.assertIn("Yeast starter", r["ask"][0])

    def test_a_number_is_not_a_version(self):
        r = resolve(EXAMPLE, "How do I bake a house loaf at 70 percent?")
        self.assertEqual(r["status"], "needs_clarification")
        self.assertIn("v1 or v2", r["ask"][0])

    def test_short_words_are_not_fuzzed(self):
        r = resolve(EXAMPLE, "feed starter 1:5:5")
        self.assertEqual(r["corrections"], [])
        self.assertEqual(r["unknown_terms"], ["feed"])
        self.assertEqual(r["status"], "resolved")  # unknown word beside a known subject: reported, not a gap
        self.assertEqual(glw.edit_budget("feed"), 0)
        self.assertEqual(glw.edit_budget("levian"), 1)

    def test_osa_counts_a_swap_as_one(self):
        self.assertEqual(glw.osa("levian", "levain", 2), 1)
        self.assertEqual(glw.osa("leaven", "levain", 2), 2)


class BrokenCopies(unittest.TestCase):
    def check(self, root, *flags):
        return run("check", "--root", root, *flags)

    def test_altered_quote_fails(self):
        with Copy() as root:
            page = root / "wiki/entities/t65-flour.md"
            page.write_text(page.read_text(encoding="utf-8").replace(
                '"T65 flour has an ash content of 0.62 to 0.75 percent"',
                '"T65 flour has an ash content of 0.62 to 0.80 percent"'), encoding="utf-8")
            code, out = self.check(root)
            self.assertEqual(code, 1)
            self.assertIn("not in raw/flour-types-note.md word for word", out)

    def test_number_not_in_quote_fails(self):
        with Copy() as root:
            page = root / "wiki/entities/t65-flour.md"
            page.write_text(page.read_text(encoding="utf-8").replace(
                "- Ash content: 0.62 to 0.75 percent.[^ash]",
                "- Ash content: 0.62 to 0.78 percent.[^ash]"), encoding="utf-8")
            code, out = self.check(root)
            self.assertEqual(code, 1)
            self.assertIn("0.78 is not in any quote", out)

    def test_wiki_citing_wiki_fails(self):
        with Copy() as root:
            append(root / "wiki/entities/t55-flour.md",
                   '\nSee also.[^x]\n\n[^x]: wiki/entities/t65-flour.md "A French bread flour"\n')
            code, out = self.check(root)
            self.assertEqual(code, 1)
            self.assertIn("one-way rule 1", out)

    def test_link_into_learning_fails(self):
        with Copy() as root:
            append(root / "wiki/concepts/levain.md", "\nExplained in [[daily-2026-11-06]].\n")
            code, out = self.check(root)
            self.assertEqual(code, 1)
            self.assertIn("one-way rule 2", out)

    def test_uncited_number_warns_then_fails_strict(self):
        with Copy() as root:
            append(root / "wiki/concepts/levain.md", "\nKeep it at 4 degrees overnight.\n")
            code, out = self.check(root)
            self.assertEqual(code, 0)
            self.assertIn("uncited number(s) 4", out)
            self.assertEqual(self.check(root, "--strict")[0], 1)

    def test_missing_source_file_fails(self):
        with Copy() as root:
            (root / "raw/house-loaf-log.md").unlink()
            code, out = self.check(root)
            self.assertEqual(code, 1)
            self.assertIn("does not exist", out)

    def test_day_without_learning_page(self):
        with Copy() as root:
            append(root / "wiki/log.md", "\n## [2026-11-08] lint | nothing new\n")
            code, out = run("learn-status", "--root", root, "--strict")
            self.assertEqual(code, 1)
            self.assertIn("MISSING learning page for 2026-11-08", out)

    def test_repeat_of_rejected_proposal_flagged(self):
        with Copy() as root:
            (root / "wiki/proposals/again.md").write_text(
                "---\ntitle: again\nkind: synonym\nkey: yeast=levain\nstatus: proposed\n---\n", encoding="utf-8")
            code, out = run("proposals", "--root", root)
            self.assertEqual(code, 1)
            self.assertIn("REPEAT", out)


if __name__ == "__main__":
    unittest.main()
