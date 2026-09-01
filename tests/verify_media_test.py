import copy
import contextlib
import io
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_media", REPO_ROOT / "tools" / "verify_media.py"
)
verify_media = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = verify_media
SPEC.loader.exec_module(verify_media)


class VerifyMediaTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.books_root = Path(self.temp_dir.name)
        self.slug = "fixture-book"
        self.book_dir = self.books_root / self.slug
        (self.book_dir / "manifests").mkdir(parents=True)
        (self.book_dir / "audio" / "sam" / "ch01").mkdir(parents=True)

        self.book = {
            "slug": self.slug,
            "chapters": [
                {"n": 1, "title": "Chapter", "paragraphs": ["one", "two"]},
                {"n": 101, "title": "Bibliography", "bib": True, "paragraphs": ["ref"]},
            ],
        }
        self.manifest = {
            "chapter": 1,
            "voice": "en-US-AndrewMultilingualNeural",
            "paragraphs": [
                {
                    "id": 0,
                    "audio": "audio/sam/ch01/p00.mp3",
                    "startMs": 0,
                    "durationMs": 1_000,
                    "words": [{"text": "one", "startMs": 0, "endMs": 700}],
                },
                {
                    "id": 1,
                    "audio": "audio/sam/ch01/p01.mp3",
                    "startMs": 1_000,
                    "durationMs": 2_000,
                    "words": [
                        {"text": "two", "startMs": 0, "endMs": 700},
                        {"text": "words", "startMs": 800, "endMs": 1_500},
                    ],
                },
            ],
            "totalMs": 3_000,
        }
        self._write_fixture(self.manifest)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_fixture(self, manifest, audio_size=5_001):
        (self.book_dir / "book.json").write_text(json.dumps(self.book), encoding="utf-8")
        (self.book_dir / "manifests" / "sam-ch01.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        for index in range(2):
            (self.book_dir / "audio" / "sam" / "ch01" / f"p{index:02d}.mp3").write_bytes(
                b"a" * audio_size
            )

    def _verify(self):
        return verify_media.verify_book("sam", self.slug, books_root=self.books_root)

    def test_valid_media_passes_and_bibliography_is_skipped(self):
        result = self._verify()

        self.assertTrue(result.is_valid, result.failures)
        self.assertEqual(result.chapters, 1)
        self.assertEqual(result.paragraphs, 2)
        self.assertEqual(result.total_ms, 3_000)
        self.assertEqual(result.bib_skipped, [101])

    def test_paragraph_count_mismatch_fails(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["paragraphs"].pop()
        manifest["totalMs"] = 1_000
        self._write_fixture(manifest)

        result = self._verify()

        self.assertFalse(result.is_valid)
        self.assertTrue(any("paragraph count 1 != book.json 2" in error for error in result.failures))

    def test_small_and_missing_mp3_fail(self):
        self._write_fixture(self.manifest, audio_size=5_000)
        (self.book_dir / "audio" / "sam" / "ch01" / "p01.mp3").unlink()

        result = self._verify()

        self.assertFalse(result.is_valid)
        self.assertTrue(any("is 5000 bytes" in error for error in result.failures))
        self.assertTrue(any("missing MP3" in error for error in result.failures))

    def test_empty_words_fail(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["paragraphs"][0]["words"] = []
        self._write_fixture(manifest)

        result = self._verify()

        self.assertFalse(result.is_valid)
        self.assertTrue(any("words must be a non-empty list" in error for error in result.failures))

    def test_non_monotonic_word_timings_fail(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["paragraphs"][1]["words"][1] = {
            "text": "words",
            "startMs": 600,
            "endMs": 650,
        }
        self._write_fixture(manifest)

        result = self._verify()

        self.assertFalse(result.is_valid)
        self.assertTrue(any("non-monotonic timing" in error for error in result.failures))

    def test_wrong_voice_and_cross_voice_audio_path_fail(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["voice"] = "en-US-BrianMultilingualNeural"
        manifest["paragraphs"][0]["audio"] = "audio/morgan/ch01/p00.mp3"
        (self.book_dir / "audio" / "morgan" / "ch01").mkdir(parents=True)
        (self.book_dir / "audio" / "morgan" / "ch01" / "p00.mp3").write_bytes(
            b"m" * 5_001
        )
        self._write_fixture(manifest)

        result = self._verify()

        self.assertFalse(result.is_valid)
        self.assertTrue(any("manifest voice" in error for error in result.failures))
        self.assertTrue(any("audio/morgan" in error and "!= expected" in error for error in result.failures))

    def test_cli_contract_returns_nonzero_for_malformed_fixture(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["paragraphs"][0]["words"] = []
        self._write_fixture(manifest)

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            exit_code = verify_media.main(
                ["sam", self.slug, "1"], books_root=self.books_root
            )

        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
