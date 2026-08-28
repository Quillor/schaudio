#!/usr/bin/env python3
"""Deployment chief: consume RENDERED handoffs from the render worker, verify
both voices deeply, publish to R2 on PASS, quarantine on FAIL.

Verification is the chief's whole job: paragraph counts against book.json,
every MP3 present and non-trivial, monotonic word timings, and a list-integrity
spot check (the reason this backfill exists).
"""
import json, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import claim as C

LOG = ROOT / "run/schaudio-run.log"
SEEN = ROOT / "run/chief-published.txt"
SEEN.parent.mkdir(exist_ok=True)
LIST_RE = re.compile(r"^(\d{1,2})[.)]\s")

def verify(slug, n):
    bd = ROOT / f"app/books/{slug}"
    book = json.loads((bd / "book.json").read_text())
    ch = next(c for c in book["chapters"] if c["n"] == n)
    for voice in ("sam", "morgan"):
        mp = bd / "manifests" / f"{voice}-ch{n:02d}.json"
        if not mp.exists():
            return f"{voice}: no manifest"
        m = json.loads(mp.read_text())
        if len(m["paragraphs"]) != len(ch["paragraphs"]):
            return f"{voice}: paras {len(m['paragraphs'])} != {len(ch['paragraphs'])}"
        for p in m["paragraphs"]:
            f = bd / p["audio"]
            if not f.exists() or f.stat().st_size < 500:
                return f"{voice}: bad {p['audio']}"
            last = -1
            for w in p["words"]:
                if w["startMs"] < last:
                    return f"{voice}: non-monotonic timings in {p['audio']}"
                last = w["startMs"]
    # list integrity: within runs of numbered items, flag skips of exactly one
    nums = [int(LIST_RE.match(p).group(1)) for p in ch["paragraphs"] if LIST_RE.match(p)]
    gaps = sum(1 for a, b in zip(nums, nums[1:]) if b - a > 1 and b > a)
    if gaps > 3:
        return f"text: {gaps} numbered-list gaps survived re-ingest"
    return None

def publish():
    r = subprocess.run([str(ROOT / ".venv-tts/bin/python"), str(ROOT / "tools/publish_r2.py"), "books"],
                       cwd=ROOT, capture_output=True, text=True, timeout=1800)
    return r.returncode == 0, (r.stdout.strip().splitlines() or [""])[-1]

def main():
    seen = set(SEEN.read_text().split()) if SEEN.exists() else set()
    while True:
        text = LOG.read_text()
        for m in re.finditer(r"(\w[\w-]*) ch(\d+): RENDERED both voices", text):
            slug, n = ("counseling", int(m.group(2))) if "counseling" in m.group(0) else (None, None)
            # slug is embedded in the line; parse robustly
        for line in text.splitlines():
            mm = re.search(r"(\w[\w-]*) ch(\d+): RENDERED both voices", line)
            if not mm: continue
            slug_m = re.search(r"(counseling|lifespan|research-methods)", line)
            if not slug_m: continue
            slug, n = slug_m.group(1), int(mm.group(2))
            key = f"{slug}-ch{n:02d}"
            if key in seen: continue
            err = verify(slug, n)
            if err:
                C.log("chief", f"{slug} ch{n}: VERIFY FAIL — {err}; releasing for re-render")
                C.release(slug, n, ok=False)
                seen.add(key)   # don't re-fail the same signal; worker re-claims
            else:
                ok, msg = publish()
                if ok:
                    C.log("chief", f"{slug} ch{n}: VERIFIED both voices + PUBLISHED to R2 ({msg})")
                    seen.add(key)
                else:
                    C.log("chief", f"{slug} ch{n}: verified but R2 publish failed; will retry next tick")
            SEEN.write_text("\n".join(sorted(seen)))
        time.sleep(120)

main()
