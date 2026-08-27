#!/usr/bin/env python3
"""Synthesize narration for every chapter of every book, per voice.

Per paragraph: one MP3 plus measured word timings from edge-tts
WordBoundary events. Writes manifests/<voice>-chNN.json — the app's
single source of truth for audio<->text sync.

Usage:
  narrate.py                 # every voice, every book, every chapter
  narrate.py morgan          # one voice
  narrate.py morgan lifespan # one voice, one book
"""

import asyncio
import json
import sys
from pathlib import Path

import edge_tts

ROOT = Path(__file__).resolve().parent.parent

# Named narrators. Both are community-rated among the most natural
# edge-tts voices (rany2/edge-tts #340); Morgan is the deeper, slower read.
VOICES = {
    "sam":    {"voice": "en-US-AndrewMultilingualNeural", "rate": "-6%", "pitch": "+0Hz", "tail_ms": 300},
    "morgan": {"voice": "en-US-BrianMultilingualNeural",  "rate": "-8%", "pitch": "-2Hz", "tail_ms": 500},
}


async def synth(text, cfg, out_path, tries=4):
    for attempt in range(tries):
        try:
            return await _synth_once(text, cfg, out_path)
        except Exception:
            if attempt == tries - 1:
                raise
            await asyncio.sleep(2 * (attempt + 1))


async def _synth_once(text, cfg, out_path):
    stream = edge_tts.Communicate(text, cfg["voice"], rate=cfg["rate"], pitch=cfg["pitch"],
                                  boundary="WordBoundary")
    audio = bytearray()
    words = []
    async for chunk in stream.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            words.append({
                "text": chunk["text"],
                "startMs": round(chunk["offset"] / 10_000),
                "endMs": round((chunk["offset"] + chunk["duration"]) / 10_000),
            })
    if not audio or not words:
        raise RuntimeError(f"no audio/timings for {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bytes(audio))
    return words


async def narrate_chapter(book_dir, chapter, voice_id):
    cfg = VOICES[voice_id]
    n = chapter["n"]
    manifest_path = book_dir / "manifests" / f"{voice_id}-ch{n:02d}.json"
    if manifest_path.exists():
        return None
    rel_dir = f"audio/{voice_id}/ch{n:02d}"
    manifest = {"chapter": n, "voice": cfg["voice"], "paragraphs": []}
    offset = 0
    for i, text in enumerate(chapter["paragraphs"]):
        words = await synth(text, cfg, book_dir / rel_dir / f"p{i:02d}.mp3")
        duration = words[-1]["endMs"] + cfg["tail_ms"]
        manifest["paragraphs"].append({
            "id": i,
            "audio": f"{rel_dir}/p{i:02d}.mp3",
            "startMs": offset,
            "durationMs": duration,
            "words": words,
        })
        offset += duration
    manifest["totalMs"] = offset
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest) + "\n")
    return offset


async def main():
    only_voice = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] != "-" else None
    only_slug = sys.argv[2] if len(sys.argv) > 2 else None
    # Optional chapter filter so independent runs can work on different
    # chapters without racing each other onto the same files.
    only_chapter = int(sys.argv[3]) if len(sys.argv) > 3 else None
    voices = [only_voice] if only_voice else list(VOICES)
    for v in voices:
        if v not in VOICES:
            raise SystemExit(f"unknown voice {v}; have: {', '.join(VOICES)}")

    for book_dir in sorted((ROOT / "app" / "books").iterdir()):
        if only_slug and book_dir.name != only_slug:
            continue
        book_json = book_dir / "book.json"
        if not book_json.exists():
            continue
        book = json.loads(book_json.read_text())
        for voice_id in voices:
            for chapter in book["chapters"]:
                if only_chapter is not None and chapter["n"] != only_chapter:
                    continue
                ms = await narrate_chapter(book_dir, chapter, voice_id)
                if ms is None:
                    print(f"skip {book_dir.name} {voice_id} ch{chapter['n']:02d}")
                else:
                    print(f"{book_dir.name} {voice_id} ch{chapter['n']:02d}: {ms/60000:.1f} min")


if __name__ == "__main__":
    asyncio.run(main())
