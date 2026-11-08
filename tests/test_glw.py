"""Tests for glw.py against the exoplanet example and broken copies of it. Run: python -m unittest -q"""
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
        r = resolve(EXAMPLE, "How does the trnasit method work?")
        self.assertEqual(r["status"], "resolved")
        self.assertEqual(r["corrections"], [{"from": "trnasit", "to": "transit"}])
        self.assertEqual(r["entity"], "wiki/concepts/transit-method.md")

    def test_near_planet_name_is_offered_never_fuzzed(self):
        r = resolve(EXAMPLE, "What is the radius of TRAPPIST-1g?")
        self.assertEqual(r["status"], "needs_clarification")
        self.assertEqual(r["corrections"], [])
        self.assertEqual(r["offered"], ["TRAPPIST-1e", "TRAPPIST-1f"])
        self.assertIsNone(r["entity"])
        r = resolve(EXAMPLE, "Kepler-452c period")
        self.assertEqual(r["offered"], ["Kepler-452b"])

    def test_letter_digit_shape_must_match(self):
        vocab = glw.Counter(["1e", "1f", "v1", "452b"])
        self.assertEqual(glw.digit_neighbours("1g", vocab), ["1e", "1f"])
        self.assertEqual(glw.digit_neighbours("t60", glw.Counter(["t55", "t65"])), ["t55", "t65"])

    def test_versioned_subject_asks_for_version(self):
        r = resolve(EXAMPLE, "What threshold does the light-curve pipeline use?")
        self.assertEqual(r["status"], "needs_clarification")
        self.assertIn("version", r["ask"][0])
        r = resolve(EXAMPLE, "light-curve pipeline v2 threshold")
        self.assertEqual(r["status"], "resolved")

    def test_partial_match_is_offered_not_chosen(self):
        r = resolve(EXAMPLE, "What is the goldilocks zone?")
        self.assertEqual(r["status"], "needs_clarification")
        self.assertIsNone(r["entity"])
        self.assertEqual(r["offered"], ["Habitable zone"])

    def test_alias_finds_entity(self):
        r = resolve(EXAMPLE, "What is transit photometry?")
        self.assertEqual(r["entity"], "wiki/concepts/transit-method.md")

    def test_unknown_words_are_a_gap(self):
        r = resolve(EXAMPLE, "What is a hot Jupiter?")
        self.assertEqual(r["status"], "gap")
        self.assertEqual(r["unknown_terms"], ["hot", "jupiter"])

    def test_applied_synonym_resolves(self):
        with Copy() as root:
            toml = root / "glw.toml"
            toml.write_text(toml.read_text(encoding="utf-8").replace(
                '"exo planet" = "exoplanet"',
                '"exo planet" = "exoplanet"\n"goldilocks zone" = "habitable zone"'), encoding="utf-8")
            r = resolve(root, "What is the goldilocks zone?")
            self.assertEqual(r["status"], "resolved")
            self.assertEqual(r["entity"], "wiki/concepts/habitable-zone.md")

    def test_gap_recorded_once_for_two_wordings(self):
        with Copy() as root:
            a = resolve(root, "rogue planet mass?", "--record-gap")
            b = resolve(root, "mass of a rogue planet", "--record-gap")
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
        self.assertIn('Read "goldilocks zone" as "habitable zone"', out)  # inner quotes survive
        code, out = run("gaps", "--root", EXAMPLE)
        self.assertIn("DUE", out)

    def test_question_about_two_subjects_returns_both(self):
        r = resolve(EXAMPLE, "Compare TRAPPIST-1e and TRAPPIST-1f")
        self.assertEqual(r["status"], "resolved")
        self.assertEqual(r["entities"], ["wiki/entities/trappist-1e.md", "wiki/entities/trappist-1f.md"])
        self.assertIsNone(r["entity"])

    def test_two_pages_with_the_same_name_ask_back(self):
        with Copy() as root:
            (root / "wiki/concepts/transit-timing.md").write_text(
                "---\ntitle: Transit timing\naliases: [transit photometry]\n---\n# Transit timing\n",
                encoding="utf-8")
            r = resolve(root, "What is transit photometry?")
            self.assertEqual(r["status"], "needs_clarification")
            self.assertIn("Transit method", r["ask"][0])
            self.assertIn("Transit timing", r["ask"][0])

    def test_a_number_is_not_a_version(self):
        r = resolve(EXAMPLE, "What does the light-curve pipeline flag at 7 sigma?")
        self.assertEqual(r["status"], "needs_clarification")
        self.assertIn("v1 or v2", r["ask"][0])

    def test_short_words_are_not_fuzzed(self):
        r = resolve(EXAMPLE, "TRAPPIST-1e mas")
        self.assertEqual(r["corrections"], [])
        self.assertEqual(r["unknown_terms"], ["mas"])
        self.assertEqual(r["status"], "resolved")  # unknown word beside a known subject: reported, not a gap
        self.assertEqual(glw.edit_budget("mass"), 0)
        self.assertEqual(glw.edit_budget("trnasit"), 1)

    def test_osa_counts_a_swap_as_one(self):
        self.assertEqual(glw.osa("trnasit", "transit", 2), 1)
        self.assertEqual(glw.osa("planet", "plant", 2), 1)

    def test_planet_names_are_not_numbers(self):
        self.assertEqual(glw.numbers_in("TRAPPIST-1 has seven planets; TRAPPIST-1e is 0.92 Earth radii"),
                         ["0.92"])

    def test_unquote_keeps_inner_quotes(self):
        self.assertEqual(glw.unquote('Read "a" as "b"'), 'Read "a" as "b"')
        self.assertEqual(glw.unquote('"plain"'), "plain")


class BrokenCopies(unittest.TestCase):
    def check(self, root, *flags):
        return run("check", "--root", root, *flags)

    def edit(self, page, old, new):
        text = page.read_text(encoding="utf-8")
        self.assertIn(old, text)
        page.write_text(text.replace(old, new), encoding="utf-8")

    def test_altered_quote_fails(self):
        with Copy() as root:
            self.edit(root / "wiki/entities/trappist-1e.md",
                      '"TRAPPIST-1e has a radius of about 0.92', '"TRAPPIST-1e has a radius of about 0.95')
            code, out = self.check(root)
            self.assertEqual(code, 1)
            self.assertIn("not in raw/trappist-1-note.md word for word", out)

    def test_number_not_in_quote_fails(self):
        with Copy() as root:
            self.edit(root / "wiki/entities/trappist-1e.md", "- Radius: about 0.92", "- Radius: about 0.95")
            code, out = self.check(root)
            self.assertEqual(code, 1)
            self.assertIn("0.95 is not in any quote", out)

    def test_wiki_citing_wiki_fails(self):
        with Copy() as root:
            append(root / "wiki/entities/trappist-1f.md",
                   '\nSee also.[^x]\n\n[^x]: wiki/entities/trappist-1e.md "A rocky planet"\n')
            code, out = self.check(root)
            self.assertEqual(code, 1)
            self.assertIn("one-way rule 1", out)

    def test_link_into_learning_fails(self):
        with Copy() as root:
            append(root / "wiki/concepts/transit-method.md", "\nExplained in [[daily-2026-11-06]].\n")
            code, out = self.check(root)
            self.assertEqual(code, 1)
            self.assertIn("one-way rule 2", out)

    def test_uncited_number_warns_then_fails_strict(self):
        with Copy() as root:
            append(root / "wiki/entities/trappist-1e.md", "\nIt is about 40 light years away.\n")
            code, out = self.check(root)
            self.assertEqual(code, 0)
            self.assertIn("uncited number(s) 40", out)
            self.assertEqual(self.check(root, "--strict")[0], 1)

    def test_missing_source_file_fails(self):
        with Copy() as root:
            (root / "raw/pipeline-log.md").unlink()
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
                "---\ntitle: again\nkind: synonym\nkey: eclipse=transit\nstatus: proposed\n---\n",
                encoding="utf-8")
            code, out = run("proposals", "--root", root)
            self.assertEqual(code, 1)
            self.assertIn("REPEAT", out)


if __name__ == "__main__":
    unittest.main()
