#!/usr/bin/env python3
"""Re-ingest every chapter of a book with the current ingest code (full text,
list-item fix, bibliography split). Skips chapters that are claimed (someone is
narrating against the existing text) or already narrated (changing their text
would break audio<->text alignment until re-narrated)."""
import importlib.util, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
spec = importlib.util.spec_from_file_location("ing", ROOT / "tools/ingest.py")
ing = importlib.util.module_from_spec(spec); spec.loader.exec_module(ing)
import claim as C
from pypdf import PdfReader

slug = sys.argv[1]
force = "--force" in sys.argv           # also redo narrated chapters (backfill)
spec_b = next(b for b in ing.BOOKS if b["slug"] == slug)
path = ROOT / f"app/books/{slug}/book.json"
data = json.load(open(path))
r = PdfReader(spec_b["pdf"])
spans = (ing.section_spans(r, spec_b) if spec_b.get("mode") == "sections"
         else ing.chapter_spans(r, spec_b["chapter_re"]))

for ch in [c for c in data["chapters"] if not c.get("bib") and c["n"] <= len(spans)]:
    n = ch["n"]
    claimed = (C.CLAIMS / f"{slug}-ch{n:02d}").exists()
    narrated = (ROOT / f"app/books/{slug}/manifests/sam-ch{n:02d}.json").exists()
    if claimed or (narrated and not force):
        print(f"ch{n:02d}: SKIP ({'claimed' if claimed else 'narrated'})")
        continue
    title, a, b = spans[n - 1]
    raw = "\n\n".join(ing.clean_page(r.pages[j].extract_text() or "")
                      for j in range(a, min(b, len(r.pages))))
    body, bib = ing.split_bib(ing.to_paragraphs(raw))
    words = sum(len(p.split()) for p in body)
    ch.update({"title": title, "paragraphs": body, "words": words,
               "fullWords": words, "excerpt": False})
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
    print(f"ch{n:02d}: {words:,} body words / {len(body)} paras"
          + (f" + bib {len(bib)} paras" if bib else ""))

data["chapters"].sort(key=lambda c: (c["n"] if c["n"] < 100 else (c["n"] - 100 + 0.5)))
json.dump(data, open(path, "w"), indent=1)
C.log("claude", f"reingest {slug}: done")
