#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import claim as C

WORKER = "agent2-B"


def verify(slug, n):
    book_dir = ROOT / "app" / "books" / slug
    book = json.loads((book_dir / "book.json").read_text())
    chapter = next(ch for ch in book["chapters"] if ch["n"] == n)
    manifest_path = book_dir / "manifests" / f"sam-ch{n:02d}.json"
    manifest = json.loads(manifest_path.read_text())
    paragraphs = manifest["paragraphs"]
    if len(paragraphs) != len(chapter["paragraphs"]):
        raise ValueError(
            f"paragraph count {len(paragraphs)} != source {len(chapter['paragraphs'])}"
        )
    total_ms = 0
    for i, paragraph in enumerate(paragraphs):
        audio_path = book_dir / paragraph["audio"]
        if not audio_path.is_file():
            raise ValueError(f"p{i}: missing MP3 {audio_path}")
        size = audio_path.stat().st_size
        if size <= 5 * 1024:
            raise ValueError(f"p{i}: MP3 only {size} bytes")
        if not paragraph.get("words"):
            raise ValueError(f"p{i}: empty words")
        duration = paragraph.get("durationMs", 0)
        if not isinstance(duration, (int, float)) or duration <= 0:
            raise ValueError(f"p{i}: invalid durationMs {duration!r}")
        total_ms += duration
    return len(paragraphs), total_ms


def main():
    C.log(WORKER, "starting")
    completed = 0
    failed = 0
    total_ms = 0
    while True:
        claimed = None
        for slug, n, words in C.pending("sam"):
            if C.claim(slug, n, WORKER):
                claimed = (slug, n, words)
                break
        if claimed is None:
            C.log(WORKER, f"finished: {completed} chapters, {total_ms / 3600000:.3f} audio hours, {failed} failed")
            return 0

        slug, n, words = claimed
        C.log(WORKER, f"{slug} ch{n}: claimed ({words:,} words)")
        try:
            result = subprocess.run(
                [str(ROOT / ".venv-tts/bin/python"), str(ROOT / "tools/narrate.py"), "sam", slug, str(n)],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            if result.returncode:
                detail = (result.stderr or result.stdout or "no output").strip().replace("\n", " | ")
                raise RuntimeError(f"narrate exit {result.returncode}: {detail[-1000:]}")
            paragraph_count, chapter_ms = verify(slug, n)
        except Exception as exc:
            failed += 1
            C.release(slug, n, ok=False)
            C.log(WORKER, f"{slug} ch{n}: FAIL {type(exc).__name__}: {exc}")
            continue

        C.release(slug, n, ok=True)
        completed += 1
        total_ms += chapter_ms
        C.log(
            WORKER,
            f"{slug} ch{n}: done; paragraphs={paragraph_count}; audio_minutes={chapter_ms / 60000:.3f}; PASS",
        )


if __name__ == "__main__":
    raise SystemExit(main())
