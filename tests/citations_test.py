import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from citations import prepare_narration
import narrate


class CitationTest(unittest.TestCase):
    def test_parenthetical_and_multi_source_keep_exact_source_tokens(self):
        text = "An exorcism (Braddock & Parish, 2001) occurred (Smith et al., 2019; Jones, 2020a)."
        spoken, meta = prepare_narration(text, True)
        self.assertEqual(spoken, "An exorcism occurred.")
        self.assertEqual(len(meta["narrationTokens"]), len(text.split()))
        self.assertEqual(meta["narrationTokens"][-1], ".")
        self.assertEqual(len(meta["omittedCitationSpans"]), 2)

    def test_narrative_author_retained(self):
        self.assertEqual(prepare_narration("Smith et al. (2019) found support.", True)[0],
                         "Smith et al. found support.")

    def test_oxford_comma_and_lowercase_surname_prefix(self):
        self.assertEqual(prepare_narration("Supported (Smith, Jones, & van Sonderen, 2019).", True)[0], "Supported.")

    def test_initials_organizations_and_possessives(self):
        self.assertEqual(prepare_narration("A finding (G. A. King, Zwaigenbaum, et al., 2006, p. 358).", True)[0], "A finding.")
        self.assertEqual(prepare_narration("Used (World Health Organization [WHO], 1992, 1993).", True)[0], "Used.")
        self.assertEqual(prepare_narration("Fredrickson et al.'s (2000) model.", True)[0], "Fredrickson et al.'s model.")
        self.assertEqual(prepare_narration("Holmbeck et al. (2002; see also Vermaes, Gerris, & Janssens, 2007) examined it.", True)[0], "Holmbeck et al. examined it.")

    def test_mixed_parenthetical_preserves_scale_and_prose(self):
        self.assertEqual(prepare_narration("Measured (CES-D; Radloff, 1977) carefully.", True)[0], "Measured (CES-D ) carefully.")
        self.assertEqual(prepare_narration("Here (r = .04; Smith, Jones, & Doe, 2019).", True)[0], "Here (r = .04 ).")

    def test_meaningful_parenthetical_and_dates_retained(self):
        text = "This began in 2019 (after treatment), lasted (2019–2020), and helped (n = 20)."
        self.assertEqual(prepare_narration(text, True)[0], text)

    def test_opt_in_only(self):
        text = "This works (Smith, 2019)."
        self.assertEqual(prepare_narration(text), (text, {}))

    def test_citation_only_fails_before_synthesis(self):
        with self.assertRaises(ValueError):
            prepare_narration("(Smith, 2019).", True)

    def test_numeric_style_omits_reference_numbers_only_when_declared(self):
        text = "Guidelines from the APA (29, 30) and NICE (31) support CBT (18–21), see Orwin (63)."
        spoken, meta = prepare_narration(text, True, numeric=True)
        self.assertEqual(spoken, "Guidelines from the APA and NICE support CBT, see Orwin.")
        self.assertEqual(len(meta["narrationTokens"]), len(text.split()))
        self.assertEqual(prepare_narration("Reviews (74– 82) differ.", True, numeric=True)[0], "Reviews differ.")
        # Author-date books keep bare numbers: they are codes and counts, not references.
        coded = "Scored as present (2), absent (0), or partial (1)."
        self.assertEqual(prepare_narration(coded, True)[0], coded)
        # Statistics and counts in brackets are never reference lists.
        kept = "Dropout (n = 30) was lower (p < .05) at week (12 weeks)."
        self.assertEqual(prepare_narration(kept, True, numeric=True)[0], kept)

    def test_reader_repeated_author_does_not_desynchronize(self):
        text = "Support (Support, 2019) Support continued."
        spoken, meta = prepare_narration(text, True)
        self.assertEqual(spoken, "Support Support continued.")
        app = (ROOT / "app" / "app.js").read_text()
        start = app.index("function alignTokens(")
        end = app.index("/* ---------------- boot", start)
        words = [{"text": t, "startMs": i * 100, "endMs": (i + 1) * 100}
                 for i, t in enumerate(["Support", "Support", "continued"])]
        script = app[start:end] + "\nconsole.log(JSON.stringify(alignTokens(" + ",".join(
            json.dumps(v) for v in [text, words, meta["narrationTokens"]]) + ")));"
        result = subprocess.run(["node", "-e", script], text=True, capture_output=True, check=True)
        aligned = json.loads(result.stdout)
        self.assertEqual([t["endMs"] for t in aligned], [100, 100, 100, 200, 300])
        self.assertEqual([t["text"] for t in aligned], text.split())


class NarrationIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_both_renderers_speak_identical_text_and_write_alignment(self):
        spec = importlib.util.spec_from_file_location("citation_renderer", ROOT / "run" / "render_chapter_parallel.py")
        renderer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(renderer)
        text = "Support (Support, 2019) Support continued."
        chapter = {"n": 1, "paragraphs": [text]}
        book = {"chapters": [chapter], "narration": {"omitInTextCitations": True}}
        calls = []

        async def synth(spoken, cfg, path):
            calls.append(spoken)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
            return [{"text": "Support", "startMs": 0, "endMs": 100}]

        with tempfile.TemporaryDirectory() as directory:
            books_root = Path(directory)
            book_dir = books_root / "fixture"
            book_dir.mkdir()
            (book_dir / "book.json").write_text(json.dumps(book))
            with mock.patch.object(narrate, "synth", side_effect=synth):
                await narrate.narrate_chapter(book_dir, chapter, "sam")
                await renderer.render_chapter("morgan", "fixture", 1, 2, books_root=books_root)
            self.assertEqual(calls, ["Support Support continued."] * 2)
            for voice in ("sam", "morgan"):
                manifest = json.loads((book_dir / "manifests" / f"{voice}-ch01.json").read_text())
                self.assertEqual(manifest["paragraphs"][0]["narrationTokens"],
                                 prepare_narration(text, True)[1]["narrationTokens"])
            self.assertEqual(json.loads((book_dir / "book.json").read_text()), book)


if __name__ == "__main__":
    unittest.main()
