#!/usr/bin/env python3
"""Shared work-claiming + logging for parallel Schaudio narration workers.

Any number of workers may run at once. The ONLY rule is that two processes must
never narrate the same chapter — they would write the same MP3s and corrupt each
other's output. Claiming is an atomic mkdir, which is safe across processes.

Usage from a worker:
    from claim import claim, release, log, pending
"""
import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLAIMS = ROOT / "run/claims"
LOG = ROOT / "run/schaudio-run.log"
STALE_SECONDS = 3 * 60 * 60          # a claim older than this is assumed dead

CLAIMS.mkdir(parents=True, exist_ok=True)
LOG.parent.mkdir(parents=True, exist_ok=True)


def log(worker, msg):
    """Append one line to the single shared log. Append mode is atomic enough
    for line-sized writes, so workers never clobber each other."""
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{worker}] {msg}\n"
    with open(LOG, "a") as f:
        f.write(line)
        f.flush()
    print(line.rstrip(), flush=True)


def claim(slug, n, worker):
    """Atomically claim one chapter. Returns True if it is yours to narrate."""
    d = CLAIMS / f"{slug}-ch{n:02d}"
    try:
        os.mkdir(d)                                   # atomic: fails if it exists
    except FileExistsError:
        try:                                          # reclaim if the owner died
            age = time.time() - d.stat().st_mtime
            if age > STALE_SECONDS:
                log(worker, f"reclaiming stale claim {slug} ch{n} (age {age/3600:.1f}h)")
            else:
                return False
        except FileNotFoundError:
            return False
    (d / "owner").write_text(f"{worker} pid={os.getpid()} at={time.time()}\n")
    return True


def release(slug, n, ok=True):
    """Leave the claim in place on success (so nobody redoes it); remove it on
    failure so another worker can retry."""
    d = CLAIMS / f"{slug}-ch{n:02d}"
    if not ok:
        for f in d.glob("*"):
            f.unlink(missing_ok=True)
        d.rmdir()


def pending(voice="sam"):
    """Chapters with no usable narration yet, unclaimed, priority-ordered."""
    out = []
    # Priority order is owner-set: The Life Span first (2026-08-27), then the
    # remainder of counseling, then research-methods.
    for slug in ("lifespan", "counseling", "research-methods"):
        bp = ROOT / f"app/books/{slug}/book.json"
        if not bp.exists():
            continue
        book = json.loads(bp.read_text())
        for c in book["chapters"]:
            if c.get("bib"):
                continue          # bibliographies are kept as text, not narrated
            mf = ROOT / f"app/books/{slug}/manifests/{voice}-ch{c['n']:02d}.json"
            ok = False
            if mf.exists():
                try:
                    ok = len(json.loads(mf.read_text())["paragraphs"]) == len(c["paragraphs"])
                except Exception:
                    ok = False
            if not ok and not (CLAIMS / f"{slug}-ch{c['n']:02d}").exists():
                out.append((slug, c["n"], c.get("fullWords", c["words"])))
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        p = pending()
        claimed = sorted(x.name for x in CLAIMS.iterdir()) if CLAIMS.exists() else []
        print(f"claimed: {len(claimed)}")
        for c in claimed[-8:]:
            print("   ", c)
        print(f"unclaimed & unfinished: {len(p)} chapters, {sum(w for _,_,w in p):,} words")
        for s, n, w in p[:8]:
            print(f"    {s} ch{n}  {w:,}w")
