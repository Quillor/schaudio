#!/usr/bin/env python3
"""Unattended overnight run: ingest -> narrate -> verify -> deploy, per chapter.

Design rules, learned the hard way earlier in this project:
  * Two narration streams maximum. Four caused edge-tts auth failures.
  * Generation never blocks on deployment. If a deploy fails (size, network),
    audio still lands on disk and can be published later.
  * Each chapter is verified before it is published; a bad chapter is skipped,
    not shipped.
"""
import importlib.util, json, os, subprocess, sys, threading, time, traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import claim as C          # shared claim + single log, so other agents can join
LOG = C.LOG
spec = importlib.util.spec_from_file_location("ing", ROOT / "tools/ingest.py")
ing = importlib.util.module_from_spec(spec); spec.loader.exec_module(ing)
from pypdf import PdfReader

VOICE = "sam"                      # one voice; the second doubles cost for no new content
book_lock = threading.Lock()       # book.json is read-modify-write
deploy_lock = threading.Lock()
state = {"done": 0, "failed": [], "deploys": 0, "deploy_fail": 0}

def log(msg):
    C.log("claude", msg)

def queue():
    return C.pending(VOICE)


def ingest_full(slug, n):
    """Replace one chapter with its complete text. Other chapters untouched."""
    with book_lock:
        spec_b = next(b for b in ing.BOOKS if b["slug"] == slug)
        path = ROOT / f"app/books/{slug}/book.json"
        data = json.load(open(path))
        r = PdfReader(spec_b["pdf"])
        spans = ing.chapter_spans(r, spec_b["chapter_re"])
        title, a, b = spans[n - 1]
        raw = "\n\n".join(ing.clean_page(r.pages[j].extract_text() or "")
                          for j in range(a, min(b, len(r.pages))))
        body, bib = ing.split_bib(ing.to_paragraphs(raw))
        words = sum(len(p.split()) for p in body)
        ch = next(c for c in data["chapters"] if c["n"] == n)
        ch.update({"title": title, "paragraphs": body, "words": words,
                   "fullWords": words, "excerpt": False})
        # Bibliography rides along as its own skippable entry, n = 100 + parent
        # (unique for filenames, sorts after every real chapter; the label is
        # what the UI shows). Never narrated — see claim.pending().
        bn = 100 + n
        prev = next((c for c in data["chapters"] if c["n"] == bn), None)
        if bib:
            bw = sum(len(p.split()) for p in bib)
            entry = {"n": bn, "label": f"{n}-A", "bib": True,
                     "title": f"Chapter {n}-A: Bibliography",
                     "paragraphs": bib, "words": bw, "fullWords": bw, "excerpt": False}
            if prev: prev.update(entry)
            else: data["chapters"].insert(data["chapters"].index(ch) + 1, entry)
        elif prev:
            data["chapters"].remove(prev)
        json.dump(data, open(path, "w"), indent=1)
    # narrate.py skips a chapter that already has a manifest, so the stale
    # excerpt audio must go or the chapter silently keeps its old 2-paragraph
    # narration against the new full text.
    import shutil
    for v in ("sam", "morgan"):
        mf = ROOT / f"app/books/{slug}/manifests/{v}-ch{n:02d}.json"
        if mf.exists(): mf.unlink()
        shutil.rmtree(ROOT / f"app/books/{slug}/audio/{v}/ch{n:02d}", ignore_errors=True)
    return len(body), words

def verify(slug, n):
    base = ROOT / f"app/books/{slug}"
    mf = base / f"manifests/{VOICE}-ch{n:02d}.json"
    if not mf.exists(): return "no manifest"
    m = json.loads(mf.read_text())
    with book_lock:
        b = json.load(open(base / "book.json"))
    ch = next(c for c in b["chapters"] if c["n"] == n)
    if len(m["paragraphs"]) != len(ch["paragraphs"]):
        return f"paragraph mismatch {len(ch['paragraphs'])} vs {len(m['paragraphs'])}"
    for p in m["paragraphs"]:
        f = base / p["audio"]
        if not f.exists() or f.stat().st_size < 5000: return f"bad audio {p['audio']}"
        if not p["words"] or p["durationMs"] <= 0: return f"bad timings p{p['id']}"
    return None

def deploy(tag):
    """At most one deploy at a time; never fatal."""
    if not deploy_lock.acquire(blocking=False):
        log(f"deploy skipped ({tag}) — one already running"); return
    try:
        t0 = time.time()
        size = subprocess.run(["du", "-sh", str(ROOT / "app")], capture_output=True,
                              text=True).stdout.split()[0]
        r = subprocess.run(["npx", "-y", "vercel", "deploy", "--prod", "--yes"],
                           cwd=ROOT, capture_output=True, text=True, timeout=3600)
        ok = "ready" in (r.stdout + r.stderr).lower() and r.returncode == 0
        state["deploys" if ok else "deploy_fail"] += 1
        log(f"deploy {'OK' if ok else 'FAILED'} ({tag}) size={size} {time.time()-t0:.0f}s")
        if not ok:
            log("  " + (r.stderr or r.stdout)[-300:].replace("\n", " "))
    except Exception as e:
        state["deploy_fail"] += 1
        log(f"deploy EXCEPTION ({tag}): {e}")
    finally:
        deploy_lock.release()

def worker(items, name):
    for slug, n, _ in items:
        tag = f"{slug} ch{n}"
        if not C.claim(slug, n, f"claude-{name}"):
            log(f"{name} {tag}: already claimed by another worker — skipping")
            continue
        try:
            paras, words = ingest_full(slug, n)
            log(f"{name} {tag}: ingested {words:,} words / {paras} paragraphs — narrating")
            t0 = time.time()
            r = subprocess.run([str(ROOT / ".venv-tts/bin/python"), str(ROOT / "tools/narrate.py"),
                                VOICE, slug, str(n)], cwd=ROOT, capture_output=True, text=True)
            err = verify(slug, n)
            if err:
                state["failed"].append(f"{tag}: {err}")
                C.release(slug, n, ok=False)
                log(f"{name} {tag}: FAILED verification — {err}")
                log("  " + (r.stderr or "")[-300:].replace("\n", " "))
                continue
            state["done"] += 1
            log(f"{name} {tag}: done in {(time.time()-t0)/60:.0f} min  (total {state['done']} chapters)")
            deploy(tag)
        except Exception:
            C.release(slug, n, ok=False)
            state["failed"].append(tag)
            log(f"{name} {tag}: EXCEPTION\n{traceback.format_exc()[-500:]}")
    log(f"{name}: queue exhausted")

def main():
    q = queue()
    nw = int(os.environ.get("WORKERS", "2"))
    log(f"=== overnight run: {len(q)} chapters, {sum(w for _,_,w in q):,} words, {nw} workers ===")
    # Deal chapters round-robin so all streams finish the priority book together.
    lanes = [q[i::nw] for i in range(nw)]
    names = [chr(ord("A") + i) for i in range(nw)]
    ts = [threading.Thread(target=worker, args=(lane, nm), daemon=False)
          for lane, nm in zip(lanes, names)]
    for t in ts: t.start()
    for t in ts: t.join()
    deploy("final")
    log(f"=== finished: {state['done']} chapters, {len(state['failed'])} failed, "
        f"{state['deploys']} deploys ok / {state['deploy_fail']} failed ===")
    if state["failed"]: log("failed: " + "; ".join(state["failed"]))

if __name__ == "__main__":
    main()
