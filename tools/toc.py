#!/usr/bin/env python3
"""Add each PDF's real chapter list to book.json as `toc`.

Keeps only chapter-like outline entries; marks the narrated chapter loaded.
"""
import json, re
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
BOOKS = {
    "lifespan": ("/Users/timrosenberg/Downloads/TheLifeSpanHumanDevelopmentforHelpingProfessionals.pdf", r"^\d+\s"),
    "counseling": ("/Users/timrosenberg/Downloads/Theory and Practice of Counseling and Psychotherapy.pdf", r"^Chapter \d+"),
    "research-methods": ("/Users/timrosenberg/Downloads/ResearchMethodsClinPsych.pdf", r"^\d+\s"),
}

for slug, (pdf, pattern) in BOOKS.items():
    r = PdfReader(pdf)
    def walk(items, depth=0):
        out = []
        for it in items:
            if isinstance(it, list):
                if depth < 1:
                    out += walk(it, depth + 1)
            else:
                out.append((depth, it.title.replace("\xa0", " ").strip()))
        return out
    titles = [t for d, t in walk(r.outline) if d == 0 and re.match(pattern, t)]
    path = ROOT / "app" / "books" / slug / "book.json"
    book = json.loads(path.read_text())
    # the narrated chapter, e.g. "Chapter 1 · Organizing Themes in Development"
    loaded_key = book["chapter"].split("·")[-1].strip().lower()[:24]
    toc = [{"title": t, "loaded": loaded_key in t.lower()} for t in titles]
    book["toc"] = toc
    path.write_text(json.dumps(book, indent=1) + "\n")
    print(slug, len(toc), "chapters, loaded:", [t["title"][:40] for t in toc if t["loaded"]])
