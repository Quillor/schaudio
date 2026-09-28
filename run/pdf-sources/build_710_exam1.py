#!/usr/bin/env python3
"""Build the 710 Exam 1 Study Guide (Google Docs export) into Schaudio book data.

Chapters come from the PDF outline's level-1 entries (Chapter 1-7, plus the
Summers reading); each level-2 heading starts a new paragraph group. Each
top-level bullet (with its sub-bullets folded in) becomes one paragraph.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
PDF = Path("/Users/timrosenberg/Downloads/710 Exam 1 Study Guide.pdf")
SLUG = "710-exam-1-study-guide"

TOP_BULLET = "●"
SUB_BULLETS = "○■◆▪•"


def clean(s: str) -> str:
    s = s.replace("​", "").replace("\xa0", " ")
    s = re.sub(r"\s*→\s*", " — ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,.;:)])", r"\1", s)
    s = re.sub(r"\(\s+", "(", s)
    return s.strip(" —")


def join(parts: list[str]) -> str:
    out = ""
    for p in parts:
        p = clean(p)
        if not p:
            continue
        if out and not re.search(r"[.!?:;—]$", out):
            out += "."
        out = f"{out} {p}" if out else p
    return out


def main() -> None:
    doc = pymupdf.open(PDF)
    toc = [(lvl, clean(t)) for lvl, t, _ in doc.get_toc()]
    toc = [(lvl, t) for lvl, t in toc if t]
    lines = [ln for page in doc for ln in page.get_text().splitlines()]

    # Locate every outline heading in order (long headings may wrap, so match on a prefix).
    marks, i = [], 0
    for lvl, title in toc:
        key = title[:28]
        while i < len(lines) and not clean(lines[i]).startswith(key):
            i += 1
        if i == len(lines):
            raise ValueError(f"heading not found: {title!r}")
        span = 1
        while clean(" ".join(lines[i:i + span])) != title and span < 4 and len(clean(" ".join(lines[i:i + span]))) < len(title):
            span += 1
        marks.append((lvl, title, i, i + span))
        i += span

    chapters, cur = [], None
    for k, (lvl, title, start, body) in enumerate(marks):
        end = marks[k + 1][2] if k + 1 < len(marks) else len(lines)
        if lvl == 1:
            cur = {"title": title, "paras": []}
            chapters.append(cur)
            continue
        if title.startswith("Summers"):
            cur = {"title": "Summers, Chapter 1: The Counselor — Becoming a Culturally Responsive Counselor", "paras": []}
            chapters.append(cur)
            heading = None
        else:
            heading = title
        # Group body lines into bullets.
        groups: list[list[str]] = []
        for raw in lines[body:end]:
            s = raw.replace("​", "").strip()
            if not s:
                if cur["title"].startswith("Summers") and groups and groups[-1]:
                    groups.append([])
                continue
            if s[0] == TOP_BULLET or not groups or not groups[-1]:
                if groups and not groups[-1]:
                    groups.pop()
                groups.append([s.lstrip(TOP_BULLET).strip()])
            elif s[0] in SUB_BULLETS:
                groups[-1].append(s.lstrip(SUB_BULLETS).strip())
            elif re.match(r"^\d+\.\s", s) and not cur["title"].startswith("Summers"):
                groups.append([s])
            elif re.match(r"^(?:[a-h]|[ivx]+)\.\s", s):
                groups[-1].append(re.sub(r"^(?:[a-h]|[ivx]+)\.\s+", "", s))
            else:
                groups[-1][-1] += " " + s
        paras = [join(g) for g in groups]
        paras = [p for p in paras if p]
        if heading:
            if paras and paras[0].lower().startswith(heading.rstrip(":").lower()):
                pass
            elif paras:
                paras[0] = f"{heading}. {paras[0]}" if not heading.endswith(":") else f"{heading} {paras[0]}"
            else:
                paras = [heading]
        cur["paras"].extend(paras)

    out_chapters = []
    for n, ch in enumerate(chapters, 1):
        words = sum(len(p.split()) for p in ch["paras"])
        title = ch["title"]
        out_chapters.append({"n": n, "title": title, "paragraphs": ch["paras"],
                             "words": words, "fullWords": words, "excerpt": False})

    out = ROOT / "app" / "books" / SLUG
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "slug": SLUG,
        "title": "710 Exam 1 Study Guide",
        "subtitle": "Lifespan Development · Chapters 1–7 and Summers",
        "author": "Course study guide",
        "accent": "teal",
        "chapters": out_chapters,
    }
    (out / "book.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    page = doc[0]
    pix = page.get_pixmap(matrix=pymupdf.Matrix(480 / page.rect.width, 480 / page.rect.width), alpha=False)
    pix.save(out / "cover.png")
    for c in out_chapters:
        print(c["n"], c["title"], len(c["paragraphs"]), c["words"])
    print("total words", sum(c["words"] for c in out_chapters))


if __name__ == "__main__":
    main()
