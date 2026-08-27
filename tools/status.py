#!/usr/bin/env python3
"""One-glance progress across every book, voice and worker."""
import json, pathlib, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
VOICE = sys.argv[1] if len(sys.argv) > 1 else "sam"


def chapter_rows(book_dir):
    book = json.loads((book_dir / "book.json").read_text())
    for c in book["chapters"]:
        words = len(" ".join(c["paragraphs"]).split())
        made = len(list((book_dir / "audio" / VOICE / f"ch{c['n']:02d}").glob("*.mp3")))
        yield {
            "n": c["n"],
            "words": words,
            "paras": len(c["paragraphs"]),
            "made": made,
            "done": (book_dir / "manifests" / f"{VOICE}-ch{c['n']:02d}.json").exists(),
        }


def main():
    live = subprocess.run(["ps", "-eo", "command"], capture_output=True, text=True).stdout
    workers = [l.split("narrate.py")[1].strip() for l in live.splitlines() if "narrate.py" in l and "status.py" not in l]
    claims = sorted(p.name for p in (ROOT / "run/claims").iterdir()) if (ROOT / "run/claims").exists() else []

    total_left = 0
    for book_dir in sorted((ROOT / "app/books").iterdir()):
        if not (book_dir / "book.json").exists():
            continue
        rows = list(chapter_rows(book_dir))
        done = [r for r in rows if r["done"]]
        left = sum(r["words"] for r in rows if not r["done"])
        total_left += left
        print(f"\n{book_dir.name}: {len(done)}/{len(rows)} chapters   {left:,} words left")
        for r in rows:
            if r["done"]:
                mark, bar = "done", ""
            elif r["made"]:
                pct = r["made"] / r["paras"] * 100
                mark, bar = "  ..", f"  {r['made']}/{r['paras']} paragraphs ({pct:.0f}%)"
            else:
                mark, bar = "    ", ""
            if not r["done"]:
                print(f"  ch{r['n']:02d}  {mark}  {r['words']:>6,} words{bar}")

    print(f"\n{len(workers)} narrator processes live: {', '.join(workers) or 'none'}")
    print(f"claims held: {', '.join(claims) or 'none'}")
    print(f"total remaining: {total_left:,} words")


main()
