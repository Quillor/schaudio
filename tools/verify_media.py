#!/usr/bin/env python3
"""Read-only verification for Schaudio chapter manifests and audio files.

Usage:
  .venv-tts/bin/python tools/verify_media.py <voice> <slug> [chapter]

The verifier never repairs or rewrites media.  It exits nonzero when any
requested, non-bibliography chapter is incomplete or internally inconsistent.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parent.parent
BOOKS_ROOT = ROOT / "app" / "books"
MIN_AUDIO_BYTES = 5_000
VALID_VOICES = ("sam", "morgan")
EXPECTED_VOICE_NAMES = {
    "sam": "en-US-AndrewMultilingualNeural",
    "morgan": "en-US-BrianMultilingualNeural",
}
SAFE_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass
class VerificationResult:
    voice: str
    slug: str
    chapters: int = 0
    paragraphs: int = 0
    total_ms: float = 0
    bib_skipped: list[int] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.failures


def _is_nonnegative_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _load_json(path: Path, label: str, failures: list[str]) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        failures.append(f"{label}: missing file {path}")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        failures.append(f"{label}: cannot parse {path}: {exc}")
    return None


def _resolve_audio(book_dir: Path, audio_reference: Any) -> tuple[Path | None, str | None]:
    if not isinstance(audio_reference, str) or not audio_reference:
        return None, "audio must be a non-empty relative path"

    audio_path = (book_dir / audio_reference).resolve()
    try:
        audio_path.relative_to(book_dir.resolve())
    except ValueError:
        return None, f"audio path escapes book directory: {audio_reference!r}"
    return audio_path, None


def _verify_paragraph(
    paragraph: Any,
    paragraph_index: int,
    expected_start_ms: float,
    book_dir: Path,
    chapter_label: str,
    voice: str,
    chapter_number: int,
    failures: list[str],
) -> float | None:
    label = f"{chapter_label} paragraph {paragraph_index}"
    if not isinstance(paragraph, dict):
        failures.append(f"{label}: expected object, got {type(paragraph).__name__}")
        return None

    paragraph_id = paragraph.get("id")
    if paragraph_id != paragraph_index:
        failures.append(f"{label}: id {paragraph_id!r} != expected {paragraph_index}")

    start_ms = paragraph.get("startMs")
    if not _is_nonnegative_number(start_ms):
        failures.append(f"{label}: startMs must be a nonnegative finite number, got {start_ms!r}")
    elif start_ms != expected_start_ms:
        failures.append(
            f"{label}: startMs {start_ms} != cumulative expected {expected_start_ms}"
        )

    duration_ms = paragraph.get("durationMs")
    if not _is_nonnegative_number(duration_ms) or duration_ms <= 0:
        failures.append(f"{label}: durationMs must be > 0, got {duration_ms!r}")
        valid_duration = None
    else:
        valid_duration = duration_ms

    audio_reference = paragraph.get("audio")
    expected_audio_reference = (
        f"audio/{voice}/ch{chapter_number:02d}/p{paragraph_index:02d}.mp3"
    )
    if audio_reference != expected_audio_reference:
        failures.append(
            f"{label}: audio {audio_reference!r} != expected {expected_audio_reference!r}"
        )
    audio_path, audio_error = _resolve_audio(book_dir, audio_reference)
    if audio_error:
        failures.append(f"{label}: {audio_error}")
    elif audio_path is not None:
        try:
            audio_size = audio_path.stat().st_size
        except FileNotFoundError:
            failures.append(f"{label}: missing MP3 {paragraph.get('audio')}")
        except OSError as exc:
            failures.append(f"{label}: cannot inspect MP3 {paragraph.get('audio')}: {exc}")
        else:
            if not audio_path.is_file():
                failures.append(f"{label}: audio reference is not a file: {paragraph.get('audio')}")
            elif audio_size <= MIN_AUDIO_BYTES:
                failures.append(
                    f"{label}: MP3 {paragraph.get('audio')} is {audio_size} bytes; "
                    f"must exceed {MIN_AUDIO_BYTES}"
                )

    words = paragraph.get("words")
    if not isinstance(words, list) or not words:
        failures.append(f"{label}: words must be a non-empty list")
        return valid_duration

    previous_start_ms = -1.0
    previous_end_ms = -1.0
    for word_index, word in enumerate(words):
        word_label = f"{label} word {word_index}"
        if not isinstance(word, dict):
            failures.append(f"{word_label}: expected object, got {type(word).__name__}")
            continue

        word_start_ms = word.get("startMs")
        word_end_ms = word.get("endMs")
        if not _is_nonnegative_number(word_start_ms):
            failures.append(
                f"{word_label}: startMs must be a nonnegative finite number, got {word_start_ms!r}"
            )
            continue
        if not _is_nonnegative_number(word_end_ms):
            failures.append(
                f"{word_label}: endMs must be a nonnegative finite number, got {word_end_ms!r}"
            )
            continue
        if word_end_ms < word_start_ms:
            failures.append(
                f"{word_label}: endMs {word_end_ms} precedes startMs {word_start_ms}"
            )
        if word_start_ms < previous_start_ms or word_end_ms < previous_end_ms:
            failures.append(
                f"{word_label}: non-monotonic timing "
                f"({word_start_ms}, {word_end_ms}) after "
                f"({previous_start_ms}, {previous_end_ms})"
            )
        if valid_duration is not None and word_end_ms > valid_duration:
            failures.append(
                f"{word_label}: endMs {word_end_ms} exceeds paragraph durationMs {valid_duration}"
            )
        previous_start_ms = word_start_ms
        previous_end_ms = word_end_ms

    return valid_duration


def _verify_chapter(
    voice: str,
    slug: str,
    chapter: dict[str, Any],
    book_dir: Path,
    result: VerificationResult,
) -> None:
    chapter_number = chapter.get("n")
    chapter_label = f"{slug} {voice} ch{chapter_number}"
    manifest_path = book_dir / "manifests" / f"{voice}-ch{chapter_number:02d}.json"
    manifest = _load_json(manifest_path, chapter_label, result.failures)
    if manifest is None:
        return
    if not isinstance(manifest, dict):
        result.failures.append(f"{chapter_label}: manifest root must be an object")
        return

    if manifest.get("chapter") != chapter_number:
        result.failures.append(
            f"{chapter_label}: manifest chapter {manifest.get('chapter')!r} != {chapter_number}"
        )

    expected_voice_name = EXPECTED_VOICE_NAMES[voice]
    if manifest.get("voice") != expected_voice_name:
        result.failures.append(
            f"{chapter_label}: manifest voice {manifest.get('voice')!r} "
            f"!= expected {expected_voice_name!r}"
        )

    text_paragraphs = chapter.get("paragraphs")
    manifest_paragraphs = manifest.get("paragraphs")
    if not isinstance(text_paragraphs, list):
        result.failures.append(f"{chapter_label}: book.json paragraphs must be a list")
        return
    if not isinstance(manifest_paragraphs, list):
        result.failures.append(f"{chapter_label}: manifest paragraphs must be a list")
        return
    if len(manifest_paragraphs) != len(text_paragraphs):
        result.failures.append(
            f"{chapter_label}: paragraph count {len(manifest_paragraphs)} "
            f"!= book.json {len(text_paragraphs)}"
        )

    cumulative_duration_ms = 0.0
    for paragraph_index, paragraph in enumerate(manifest_paragraphs):
        duration_ms = _verify_paragraph(
            paragraph,
            paragraph_index,
            cumulative_duration_ms,
            book_dir,
            chapter_label,
            voice,
            chapter_number,
            result.failures,
        )
        if duration_ms is not None:
            cumulative_duration_ms += duration_ms

    total_ms = manifest.get("totalMs")
    if not _is_nonnegative_number(total_ms):
        result.failures.append(
            f"{chapter_label}: totalMs must be a nonnegative finite number, got {total_ms!r}"
        )
    elif total_ms != cumulative_duration_ms:
        delta_ms = total_ms - cumulative_duration_ms
        result.failures.append(
            f"{chapter_label}: totalMs {total_ms} != summed durationMs "
            f"{cumulative_duration_ms} (delta {delta_ms:+g}ms)"
        )

    result.chapters += 1
    result.paragraphs += len(manifest_paragraphs)
    if _is_nonnegative_number(total_ms):
        result.total_ms += total_ms


def verify_book(
    voice: str,
    slug: str,
    chapter_number: int | None = None,
    books_root: Path = BOOKS_ROOT,
) -> VerificationResult:
    """Verify requested media and return all discovered failures without mutation."""
    result = VerificationResult(voice=voice, slug=slug)
    if voice not in VALID_VOICES:
        result.failures.append(
            f"unknown voice {voice!r}; expected one of: {', '.join(VALID_VOICES)}"
        )
        return result
    if not SAFE_SLUG.fullmatch(slug):
        result.failures.append(f"invalid slug {slug!r}; expected lowercase kebab-case")
        return result

    book_dir = books_root / slug
    book = _load_json(book_dir / "book.json", f"{slug} book", result.failures)
    if book is None:
        return result
    if not isinstance(book, dict) or not isinstance(book.get("chapters"), list):
        result.failures.append(f"{slug} book: book.json must contain a chapters list")
        return result

    chapters = book["chapters"]
    if chapter_number is not None:
        chapters = [
            chapter
            for chapter in chapters
            if isinstance(chapter, dict) and chapter.get("n") == chapter_number
        ]
        if not chapters:
            result.failures.append(f"{slug}: chapter {chapter_number} not found in book.json")
            return result

    for chapter in chapters:
        if not isinstance(chapter, dict):
            result.failures.append(
                f"{slug}: chapter entry must be an object, got {type(chapter).__name__}"
            )
            continue
        chapter_number_value = chapter.get("n")
        if not isinstance(chapter_number_value, int) or isinstance(chapter_number_value, bool):
            result.failures.append(f"{slug}: chapter n must be an integer, got {chapter_number_value!r}")
            continue
        if chapter.get("bib") is True:
            result.bib_skipped.append(chapter_number_value)
            continue
        _verify_chapter(voice, slug, chapter, book_dir, result)

    return result


def _print_result(result: VerificationResult) -> None:
    for chapter_number in result.bib_skipped:
        print(f"SKIP {result.slug} ch{chapter_number}: bibliography entry")
    for failure in result.failures:
        print(f"FAIL {failure}", file=sys.stderr)

    minutes = result.total_ms / 60_000
    status = "PASS" if result.is_valid else "FAIL"
    print(
        f"{status} {result.voice} {result.slug}: {result.chapters} chapters, "
        f"{result.paragraphs} paragraphs, {minutes:.2f} audio minutes, "
        f"{len(result.bib_skipped)} bibliography entries skipped"
    )


def main(argv: Sequence[str] | None = None, books_root: Path = BOOKS_ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("voice", choices=VALID_VOICES)
    parser.add_argument("slug")
    parser.add_argument("chapter", nargs="?", type=int)
    args = parser.parse_args(argv)

    result = verify_book(args.voice, args.slug, args.chapter, books_root)
    _print_result(result)
    return 0 if result.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
