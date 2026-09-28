import asyncio
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "render_chapter_parallel", REPO_ROOT / "run" / "render_chapter_parallel.py"
)
renderer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = renderer
SPEC.loader.exec_module(renderer)


class RenderChapterParallelTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.books_root = Path(self.temp_dir.name)
        self.slug = "fixture-book"
        self.book_dir = self.books_root / self.slug
        self.book_dir.mkdir(parents=True)
        self.chapter = {
            "n": 2,
            "title": "Fixture",
            "paragraphs": ["first", "second", "third"],
        }
        self._write_book([self.chapter])

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_book(self, chapters):
        (self.book_dir / "book.json").write_text(
            json.dumps({"slug": self.slug, "chapters": chapters}), encoding="utf-8"
        )

    def _manifest_path(self):
        return self.book_dir / "manifests" / "sam-ch02.json"

    async def test_out_of_order_completion_keeps_source_order_and_exact_offsets(self):
        release_events = {text: asyncio.Event() for text in self.chapter["paragraphs"]}
        completion_order = []
        end_times = {"first": 100, "second": 250, "third": 50}

        async def fake_synth(text, cfg, out_path):
            await release_events[text].wait()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(text.encode("utf-8"))
            completion_order.append(text)
            return [{"text": text, "startMs": 0, "endMs": end_times[text]}]

        async def release_out_of_order():
            for text in ("third", "first", "second"):
                release_events[text].set()
                await asyncio.sleep(0)

        with mock.patch.object(renderer.narrate, "synth", side_effect=fake_synth):
            release_task = asyncio.create_task(release_out_of_order())
            total_ms = await renderer.render_chapter(
                "sam", self.slug, 2, 3, books_root=self.books_root
            )
            await release_task

        manifest = json.loads(self._manifest_path().read_text(encoding="utf-8"))
        self.assertEqual(completion_order, ["third", "first", "second"])
        self.assertEqual(manifest["chapter"], 2)
        self.assertEqual([paragraph["id"] for paragraph in manifest["paragraphs"]], [0, 1, 2])
        self.assertEqual(
            [paragraph["audio"] for paragraph in manifest["paragraphs"]],
            [
                "audio/sam/ch02/p00.mp3",
                "audio/sam/ch02/p01.mp3",
                "audio/sam/ch02/p02.mp3",
            ],
        )
        self.assertEqual(
            [paragraph["startMs"] for paragraph in manifest["paragraphs"]],
            [0, 400, 950],
        )
        self.assertEqual(
            [paragraph["durationMs"] for paragraph in manifest["paragraphs"]],
            [400, 550, 350],
        )
        self.assertEqual(
            [paragraph["words"] for paragraph in manifest["paragraphs"]],
            [
                [{"text": "first", "startMs": 0, "endMs": 100}],
                [{"text": "second", "startMs": 0, "endMs": 250}],
                [{"text": "third", "startMs": 0, "endMs": 50}],
            ],
        )
        self.assertEqual(manifest["voice"], renderer.narrate.VOICES["sam"]["voice"])
        self.assertEqual(manifest["totalMs"], 1_300)
        self.assertEqual(total_ms, 1_300)

    async def test_semaphore_never_exceeds_requested_concurrency(self):
        active = 0
        maximum_active = 0
        two_started = asyncio.Event()

        async def fake_synth(text, cfg, out_path):
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            if maximum_active == 2:
                two_started.set()
            await two_started.wait()
            await asyncio.sleep(0)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"audio")
            active -= 1
            return [{"text": text, "startMs": 0, "endMs": 10}]

        with mock.patch.object(renderer.narrate, "synth", side_effect=fake_synth):
            await renderer.render_chapter("sam", self.slug, 2, 2, books_root=self.books_root)

        self.assertEqual(maximum_active, 2)

    async def test_synth_failure_leaves_no_manifest_or_successful_audio(self):
        async def fake_synth(text, cfg, out_path):
            if text == "second":
                await asyncio.sleep(0)
                raise RuntimeError("synthetic failure")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"successful audio")
            await asyncio.sleep(0)
            return [{"text": text, "startMs": 0, "endMs": 10}]

        with mock.patch.object(renderer.narrate, "synth", side_effect=fake_synth):
            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                await renderer.render_chapter(
                    "sam", self.slug, 2, 3, books_root=self.books_root
                )

        self.assertFalse(self._manifest_path().exists())
        self.assertEqual(list((self.book_dir / "audio").rglob("*.mp3")), [])

    async def test_existing_manifest_is_refused_before_synthesis(self):
        self._manifest_path().parent.mkdir(parents=True)
        self._manifest_path().write_text("existing", encoding="utf-8")

        with mock.patch.object(renderer.narrate, "synth") as synth:
            with self.assertRaisesRegex(renderer.RenderError, "manifest already exists"):
                await renderer.render_chapter(
                    "sam", self.slug, 2, 3, books_root=self.books_root
                )

        synth.assert_not_called()
        self.assertEqual(self._manifest_path().read_text(encoding="utf-8"), "existing")

    async def test_bibliography_chapter_is_refused(self):
        self._write_book([{"n": 2, "bib": True, "paragraphs": ["reference"]}])

        with self.assertRaisesRegex(renderer.RenderError, "bibliography entry"):
            await renderer.render_chapter("sam", self.slug, 2, 1, books_root=self.books_root)


class RenderChapterParallelCliValidationTest(unittest.TestCase):
    def test_invalid_cli_values_exit_before_rendering(self):
        invalid_argv = [
            ["other", "fixture-book", "2", "1"],
            ["sam", "../escape", "2", "1"],
            ["sam", "fixture-book", "0", "1"],
            ["sam", "fixture-book", "2", "0"],
            ["sam", "fixture-book", "2", "11"],
        ]
        for argv in invalid_argv:
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        renderer.main(argv)
                self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
