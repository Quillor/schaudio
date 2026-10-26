#!/usr/bin/env python3
"""Build the 2026-10-26 journal-article batch into Schaudio books.

Three two-column journal PDFs that tools/build_book.py cannot structure on its own (column
order, full-page rotated tables, numbered references). Per paper this script:

  - crops every figure and table (caption + graphic + notes) to figures/<id>.png and records it
    in the chapter's "visuals" list, anchored after the paragraph that first mentions it.
    Visuals are display-only: their text never enters "paragraphs", so it is never narrated.
  - reads the remaining text column by column, drops running heads, affiliations and back matter,
    splits it at the article's own section headings and splits off the reference list as the
    usual text-only bibliography chapter.
  - turns on narration.omitInTextCitations, so "(21–24)" and "(Smith, 2019)" stay on screen but
    are not spoken.
  - runs tools/build_book.py's quality gates over the result.

  .venv-tts/bin/python run/batch-2026-10-26-papers/build.py [slug ...]    -> app/books/<slug>/
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import build_book as BB  # noqa: E402
from ingest import HYPHEN_PREFIXES, normalise  # noqa: E402

BATCH = Path(__file__).resolve().parent
BOOKS = Path(os.environ.get("SCHAUDIO_BOOKS", ROOT / "app" / "books"))
SRC = Path.home() / "Desktop" / "today"
ZOOM = 3  # 216 dpi crops: sharp on retina at reading width, ~100-400 KB each

# Visual spec: label, page (1-based), span ("full" | "left" | "right"), until ("body" = stop at
# the first running-text line or next caption below, "page" = to the bottom margin, or a y in
# points), optional top (points; default = caption top), optional rotate (degrees clockwise to
# upright, for landscape tables), optional appendix (shown in a text-only Appendix chapter).
# Book keys: body_font/body_min say what running text looks like; margins are the running head
# and foot bands; clip_x1 keeps a vertical side watermark out of crops.
ROT = {"span": "full", "top": 47, "until": 752, "rotate": 90}
SPECS = {
    "dutra-2008": {
        "pdf": SRC / "2008-a-meta-analytic-review-of-psychosocial-interventions-for-substance-use-disorders.pdf",
        "title": "A Meta-Analytic Review of Psychosocial Interventions for Substance Use Disorders",
        "subtitle": "American Journal of Psychiatry, 2008",
        "author": "Lissa Dutra, Georgia Stathopoulou, Shawnee L. Basden, Teresa M. Leyro, Mark B. Powers, Michael W. Otto",
        "accent": "teal", "citation_style": "numeric",
        "body_font": r"Utopia", "body_min": 7.5, "margins": (44, 742),
        "heading_font": r"MyriadMM_512_800_|OceanSansMM_512_800_",
        "drop_fonts": [r"OceanSansMM_512_475_", r"OceanSansMM_403_800_"],   # author list, title-page footnote
        "drop_lines": [r"^\(Am J Psychiatry 2008; 165:179"],
        "sections": [("Abstract", r"^Objective: Despite"), ("Introduction", r"^In the last 30 years"),
                     ("Method", r"^Method$"), ("Results", r"^Results$"), ("Discussion", r"^Discussion$"),
                     ("References", r"^References$")],
        "visuals": [
            {"label": "Table 1", "page": 2, "span": "full", "until": "body"},
            {"label": "Table 1 (continued)", "page": 3, "span": "full", "top": 60, "until": "body"},
            {"label": "Figure 1", "page": 6, "span": "left", "until": "body"},
            {"label": "Figure 2", "page": 6, "span": "right", "until": "body"},
        ],
    },
    "brownley-2016": {
        "pdf": SRC / "brownley-et-al-2016-binge-eating-disorder-in-adults.pdf",
        "title": "Binge-Eating Disorder in Adults",
        "subtitle": "A Systematic Review and Meta-analysis · Annals of Internal Medicine, 2016",
        "author": "Kimberly A. Brownley, Nancy D. Berkman, Christine M. Peat, Kathleen N. Lohr, Katherine E. Cullen, Carla M. Bann, Cynthia M. Bulik",
        "accent": "violet", "citation_style": "numeric",
        "body_font": r"AvenirNextLTPro-(Regular|It|Medium|Demi)", "body_min": 9, "margins": (50, 742),
        "heading_font": r"GeorgiaPro-Bold|Acta-BoldItalic|GeorgiaPro-BoldItalic",
        "drop_fonts": [r"^Avenir-", r"AvenirNextLTPro-Bold$"],          # "See also" box, author list
        "drop_lines": [r"^Ann Intern Med\. 2016;165", r"^For author affiliations, see", r"^This article was published at"],
        "drop_between": [(r"^From University of North Carolina at Chapel Hill", r"^References$"),
                         (r"^Current Author Addresses", None)],
        "last_page": 13,
        "sections": [("Abstract", r"^Background: The best treatment"), ("Introduction", r"^Binge-eating disorder \(BED\), the most common"),
                     ("Methods", r"^METHODS$"), ("Results", r"^RESULTS$"), ("Discussion", r"^DISCUSSION$"),
                     ("References", r"^References$")],
        "visuals": [
            {"label": "Table 1", "page": 2, "span": "full", "until": "body"},
            {"label": "Table 2", "page": 5, "span": "full", "until": "page"},
            {"label": "Table 2 (continued)", "page": 6, "span": "full", "until": "body"},
            {"label": "Figure 1", "page": 7, "span": "full", "until": "body"},
            {"label": "Figure 2", "page": 7, "span": "full", "until": "body"},
            {"label": "Appendix Table 1", "page": 13, "span": "right", "until": "page", "appendix": True},
            {"label": "Appendix Figure 1", "page": 14, "span": "full", "until": "body", "appendix": True},
            {"label": "Appendix Table 2", "page": 14, "span": "full", "until": "page", "appendix": True},
            {"label": "Appendix Figure 2", "page": 15, "span": "full", "until": "page", "appendix": True},
            {"label": "Appendix Table 3", "page": 16, "span": "full", "until": "page", "appendix": True},
            {"label": "Appendix Table 3 (continued)", "page": 17, "span": "full", "until": "page", "appendix": True},
            {"label": "Appendix Table 3 (continued)", "page": 18, "span": "full", "until": "page", "appendix": True},
            {"label": "Appendix Table 4", "page": 19, "span": "full", "until": "page", "appendix": True},
        ],
    },
    "harrop-2021": {
        "pdf": SRC / "Intl J Eating Disorders - 2021 - Harrop - Restrictive eating disorders in higher weight persons  A systematic review of.pdf",
        "title": "Restrictive eating disorders in higher weight persons: A systematic review of atypical anorexia nervosa prevalence and consecutive admission literature",
        "subtitle": "International Journal of Eating Disorders, 2021",
        "author": "Erin N. Harrop, Janell L. Mensinger, Megan Moore, Taryn Lindhorst",
        "accent": "orange",
        # caption text shares the body font here, so every visual gives its bottom explicitly
        "body_font": r"AdvTTa9c1b374", "body_min": 7.9, "margins": (33, 757), "clip_x1": 572,
        "heading_font": r"AdvTT6071803a\.B", "para_by_indent": True,
        "drop_lines": [r"^DOI: 10\.1002/eat", r"Wiley Periodicals LLC", r"^R E V I E W$"],
        "drop_between": [(r"^Erin N\. Harrop1,2", r"^Abstract$"),
                         (r"^Resumen$", r"^The growth of anorexia nervosa"),
                         (r"^ACKNOWLEDGMENTS$", r"^REFERENCES$"),
                         (r"^How to cite this article", None), (r"^SUPPORTING INFORMATION", None)],
        "refs": "hanging",   # the Spanish "Resumen" duplicates the English abstract: dropped, per Tim
        "sections": [("Abstract", r"^Abstract$"), ("Introduction", r"^The growth of anorexia nervosa"),
                     ("The Current Study", r"^1 \| THE CURRENT STUDY$"), ("Methods", r"^2 \| METHODS$"),
                     ("Results", r"^3 \| RESULTS$"), ("Discussion", r"^4 \| DISCUSSION$"),
                     ("Limitations and Implications", r"^5 \| LIMITATIONS$"), ("Conclusion", r"^8 \| CONCLUSION$"),
                     ("References", r"^REFERENCES$")],
        "visuals": [
            {"label": "Figure 1", "page": 5, "span": "full", "top": 48, "until": 615},
            {"label": "Table 1", "page": 7, **ROT},
            {"label": "Table 1 (continued)", "page": 8, **ROT},
            {"label": "Table 2", "page": 9, **ROT},
            *({"label": "Table 2 (continued)", "page": p, **ROT} for p in (10, 11, 12, 13)),
            {"label": "Figure 2", "page": 14, "span": "full", "top": 48, "until": 330},
            {"label": "Table 3", "page": 15, **ROT},
            {"label": "Table 3 (continued)", "page": 16, **ROT},
            {"label": "Figure 3", "page": 17, "span": "full", "top": 48, "until": 262},
            {"label": "Table 4", "page": 18, "span": "full", "top": 46, "until": 752},
            *({"label": "Table 4 (continued)", "page": p, "span": "full", "top": 46, "until": 752} for p in (19, 20, 21)),
            {"label": "Table 4 (continued)", "page": 22, "span": "full", "top": 46, "until": 206},
        ],
    },
}

CAPTION = re.compile(r"^(?:Appendix\s+)?(FIGURE|Figure|TABLE|Table)\s+(\d+)\b")


# ---------------------------------------------------------------- geometry

def page_lines(page, pno):
    """Text lines with geometry and font, unsorted."""
    out = []
    for bi, block in enumerate(page.get_text("dict")["blocks"]):
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = normalise("".join(s["text"] for s in line["spans"])).replace("​", "").replace("\xa0", " ")
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                continue
            chars = sum(len(s["text"]) for s in spans)
            font = Counter()
            for s in spans:
                font[(s["font"], round(s["size"], 1))] += len(s["text"])
            (fname, size), _ = font.most_common(1)[0]
            bold = sum(len(s["text"]) for s in spans if s["flags"] & 16 or "Bold" in s["font"]) / chars > 0.6
            out.append({"p": pno, "bbox": pymupdf.Rect(line["bbox"]), "bblock": pymupdf.Rect(block["bbox"]),
                        "text": text, "font": fname, "size": size, "bold": bold, "block": (pno, bi),
                        "dir": tuple(round(v) for v in line["dir"])})
    return out


def is_body(l, spec):
    """Running text, as opposed to table cells, axis labels and captions."""
    return bool(re.search(spec["body_font"], l["font"])) and l["size"] >= spec["body_min"]


def columns(page):
    w = page.rect.width
    return {"full": (0, w), "left": (0, w / 2), "right": (w / 2, w)}


def caption_line(lines, spec):
    want = re.match(r"(?:Appendix\s+)?(Figure|Table)\s+(\d+)", spec["label"], re.I)
    kind, num = want.group(1).lower(), want.group(2)
    for l in sorted(lines, key=lambda l: (l["bbox"].y0, l["bbox"].x0)):
        m = CAPTION.match(l["text"])
        if m and m.group(1).lower() == kind and m.group(2) == num and l["dir"] == (1, 0):
            # a caption, not a sentence that mentions it: caption fonts differ from body text
            if not is_body(l, spec):
                return l
    return None


def visual_rect(page, lines, spec, book):
    x0, x1 = columns(page)[spec["span"]]
    top = spec.get("top")
    cap = None
    if top is None:
        cap = caption_line([l for l in lines if x0 - 2 <= l["bbox"].x0 < x1], {**book, **spec})
        if cap is None:
            raise ValueError(f"{spec['label']}: caption not found on page {spec['page']}")
        top = cap["bbox"].y0
    margins = book["margins"]
    until = spec.get("until", "body")
    if until == "page":
        bottom = margins[1]
    elif until == "body":
        below = sorted((l for l in lines if l["bbox"].y0 > top + 12 and x0 - 2 <= l["bbox"].x0 < x1
                        and l["bbox"].x1 <= x1 + 2 and l["bbox"].y1 < margins[1]), key=lambda l: l["bbox"].y0)
        # body text resumes where a body-font line sits in a block of 2+ body lines
        bodyblocks = Counter(l["block"] for l in lines if is_body(l, book))
        stop = next((l for l in below if is_body(l, book) and bodyblocks[l["block"]] >= 2), None)
        # another caption in the same column below this one also ends the visual
        nxt = next((l for l in below if CAPTION.match(l["text"]) and not is_body(l, book) and l is not cap), None)
        ends = [l["bbox"].y0 for l in (stop, nxt) if l is not None]
        bottom = (min(ends) - 4) if ends else margins[1]
    else:
        bottom = float(until)
    # Tighten horizontally to what is actually drawn/written in the band.
    band = pymupdf.Rect(x0, top - 1, x1, bottom)
    ink = [l["bbox"] for l in lines if l["bbox"].intersects(band) and band.contains(l["bbox"].tl)]
    ink += [d["rect"] for d in page.get_drawings() if band.intersects(d["rect"]) and d["rect"].width < page.rect.width * 0.98]
    ink += [pymupdf.Rect(i["bbox"]) for i in page.get_image_info() if band.intersects(pymupdf.Rect(i["bbox"]))]
    r = pymupdf.Rect(band)
    if ink:
        u = pymupdf.Rect(ink[0])
        for b in ink[1:]:
            u |= b
        r = pymupdf.Rect(max(x0, u.x0), max(top - 1, u.y0), min(x1, u.x1), min(bottom, u.y1)) & band
    return r + (-4, -4, 4, 4)



def kind_and_number(label):
    m = re.match(r"(Appendix\s+)?(Figure|Table)\s+(\d+)", label)
    return ("appendix-" if m.group(1) else "") + m.group(2).lower(), int(m.group(3))


def crop_visuals(doc, book, out_dir):
    """Render every visual to figures/<id>.png; return [{id, label, kind, page, rect, ...}]."""
    from PIL import Image

    (out_dir / "figures").mkdir(parents=True, exist_ok=True)
    seen, visuals = Counter(), []
    lines_by_page = {}
    for spec in book["visuals"]:
        pno = spec["page"] - 1
        page = doc[pno]
        lines = lines_by_page.setdefault(pno, page_lines(page, pno))
        if spec.get("rotate"):
            r = pymupdf.Rect(36, spec.get("top", 33), book.get("clip_x1", page.rect.width - 36), spec["until"])
            ink = [pymupdf.Rect(l["bbox"]) for l in lines if r.contains(l["bbox"])]
            ink += [d["rect"] for d in page.get_drawings() if r.intersects(d["rect"])]
            u = ink[0]
            for b in ink[1:]:
                u |= b
            r = ((u & r) + (-4, -4, 4, 4)) & r
        else:
            r = visual_rect(page, lines, spec, book)
        if book.get("clip_x1"):
            r.x1 = min(r.x1, book["clip_x1"])
        kind, num = kind_and_number(spec["label"])
        base = f"{kind}-{num}"
        seen[base] += 1
        vid = base if seen[base] == 1 else f"{base}-{seen[base]}"
        pix = page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), clip=r, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        if spec.get("rotate"):
            img = img.rotate(-spec["rotate"], expand=True)
        path = out_dir / "figures" / f"{vid}.png"
        img.save(path, optimize=True)
        visuals.append({"id": vid, "label": spec["label"], "kind": kind.replace("appendix-", ""),
                        "number": num, "appendix": bool(spec.get("appendix")), "page": spec["page"],
                        "rect": r, "src": f"figures/{vid}.png", "w": img.width, "h": img.height,
                        "continued": seen[base] > 1})
    return visuals


def text_lines(doc, book, visuals):
    """Running text in reading order (the PDF's own block order is column order in these
    files), minus running heads/feet, rotated text, visual regions and per-book drop areas."""
    top, bottom = book["margins"]
    rects = {}
    for v in visuals:
        rects.setdefault(v["page"] - 1, []).append(v["rect"])
    for pg, r in book.get("drop_rects", []):
        rects.setdefault(pg - 1, []).append(pymupdf.Rect(r))
    last = book.get("last_page", len(doc))
    out, dropcap = [], None
    for pno in range(last):
        page = doc[pno]
        h = page.rect.height
        for l in page_lines(page, pno):
            b = l["bbox"]
            mid = pymupdf.Point((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2)
            if l["dir"] != (1, 0) or b.y0 < top or b.y1 > bottom or any(r.contains(mid) for r in rects.get(pno, [])):
                continue
            if any(re.search(rx, l["text"]) for rx in book.get("drop_lines", [])):
                continue
            if len(l["text"]) == 1 and l["text"].isupper() and l["size"] > 18:
                dropcap = l["text"]  # a drop cap belongs to the first line of the next block
                continue
            if dropcap and l["block"] != (pno, -1):
                l["text"], dropcap = dropcap + l["text"], None
            elif any(re.search(rx, l["font"]) for rx in book.get("drop_fonts", [])):
                continue
            out.append({"p": pno, "y0": b.y0 / h, "y1": b.y1 / h, "text": l["text"], "size": l["size"],
                        "bold": l["bold"], "block": l["block"], "font": l["font"], "x0": b.x0,
                        "heading": bool(re.search(book["heading_font"], l["font"]))})
    # Justified lines that the PDF stores word by word (Harrop) come out as one "line" per word;
    # rejoin runs on the same baseline within one block.
    merged = []
    for l in out:
        m = merged[-1] if merged else None
        if m and m["block"] == l["block"] and abs(m["y0"] - l["y0"]) < 0.004 and l["x0"] > m["x0"]:
            m["text"] += " " + l["text"]
            continue
        merged.append(dict(l))
    if book.get("para_by_indent"):
        reblock_by_indent(merged, doc)
    return merged


def reblock_by_indent(lines, doc):
    """For PDFs that store every justified line as its own block: a paragraph starts at a
    first-line indent, a vertical gap or a heading, and otherwise continues, also across a
    column or page break."""
    left = {}
    for l in lines:
        key = (l["p"], l["x0"] > doc[l["p"]].rect.width / 2)
        left.setdefault(key, Counter())[round(l["x0"])] += 1
    left = {k: c.most_common(1)[0][0] for k, c in left.items()}
    para, prev = 0, None
    for l in lines:
        h = doc[l["p"]].rect.height
        col = (l["p"], l["x0"] > doc[l["p"]].rect.width / 2)
        indent = l["x0"] - left[col] > 6
        gap = prev is not None and prev["p"] == l["p"] and 0.012 < l["y0"] - prev["y1"] < 0.2 and \
            (l["x0"] > doc[l["p"]].rect.width / 2) == (prev["x0"] > doc[l["p"]].rect.width / 2)
        label = re.match(r"(Objective|Method|Results|Discussion): ", l["text"])
        if prev is None or indent or gap or label or l["heading"] or prev["heading"]:
            para += 1
        l["block"] = (0, para)
        prev = l


def drop_between(lines, book):
    out, skipping = [], None
    for l in lines:
        if skipping is not None:
            end = book["drop_between"][skipping][1]
            if end is None or not re.search(end, l["text"]):
                continue
            skipping = None
        hit = next((k for k, (start, _) in enumerate(book.get("drop_between", [])) if re.search(start, l["text"])), None)
        if hit is not None:
            skipping = hit
            continue
        out.append(l)
    return out


def heading_text(t):
    t = re.sub(r"^\d+(?:\.\d+)*\s*\|\s*", "", t).strip()
    if t.isupper():
        t = t.capitalize()
    return t


FIXES = [
    (re.compile(r"(?<=[A-Za-z=<>])\.(?=\d)"), " ."),      # "from .64" lost its space in paragraph cleanup
    (re.compile(r"\bAANis\b"), "AAN is"),                  # glued in the PDF's text layer
    (re.compile(r"\bparticipantshave\b"), "participants have"),
    (re.compile(r"Conceiç~ao"), "Conceição"),
    (re.compile(r"\bPeebleset al\."), "Peebles et al."),
    # Typos in the published Harrop text (p. 1351): an unclosed citation list and ").,".
    # Without the bracket the ten-source citation cannot be recognized and would be read aloud.
    (re.compile(r"Santonastaso et al\., 2009\. In one study"), "Santonastaso et al., 2009). In one study"),
    (re.compile(r"\(Monge et al\., 2015\)\.,"), "(Monge et al., 2015),"),
]


def rejoin_hyphen(a, b):
    """Line-end hyphen. The paper's own usage decides first (the joined word or the hyphenated
    compound appearing mid-line elsewhere), then the dictionary ("re- sponses" -> "responses",
    "binge- eating" -> "binge-eating"), then build_book's prefix list; otherwise join, since a
    fragment like "stud- ies" is a broken word. Replaces build_book.rejoin_hyphen for this batch."""
    m = re.search(r"(\w+)-$", a)
    n = re.match(r"[A-Za-z]+", b)
    if not m or not n:
        return BB_REJOIN(a, b)
    left, right = m.group(1), n.group(0)
    joined, compound = (left + right).lower(), f"{left}-{right}".lower()
    if joined in DOC_WORDS:
        keep = False
    elif compound in DOC_WORDS:
        keep = True
    elif BB.is_word(joined):
        keep = False
    elif len(left) > 1 and BB.is_word(left) and BB.is_word(right):
        keep = True
    else:
        keep = left.lower() in HYPHEN_PREFIXES and BB.is_word(right)
    return a + b if keep else a[:-1] + b


def doc_words(lines):
    """Words as the paper writes them mid-line (line-end fragments excluded)."""
    words = set()
    for l in lines:
        toks = l["text"].split()
        for t in toks[:-1] if l["text"].endswith("-") else toks:
            words.add(re.sub(r"^\W+|\W+$", "", t).lower())
    return words


DOC_WORDS = set()
BB_REJOIN = BB.rejoin_hyphen
BB.rejoin_hyphen = rejoin_hyphen


def fix_text(p):
    for rx, rep in FIXES:
        p = rx.sub(rep, p)
    return p


def section_paragraphs(lines):
    """Paragraphs for one section. Sub-headings stay as their own short paragraphs (a spoken
    signpost); the text between them gets build_book's usual paragraphing and tidying."""
    out, run, head = [], [], []
    fixes = Counter()

    def flush_text():
        if run:
            out.extend(fix_text(p) for p in BB.tidy([BB.repair_splits(p, fixes) for p in BB.paragraphs_from(run)]))
            run.clear()

    def flush_head():
        if head:
            out.append(heading_text(" ".join(h["text"] for h in head)))
            head.clear()

    for l in lines:
        if l["heading"]:
            flush_text()
            head.append(l)
        else:
            flush_head()
            run.append(l)
    flush_text()
    flush_head()
    return out, fixes


def split_sections(lines, book):
    """[(title, [lines])] at the book's section starts; lines before the first start are the
    title block and are dropped. A start line in a heading font is the heading itself and is
    dropped; one in the body font is the section's first line and is kept."""
    starts = []
    pending = list(book["sections"])
    for i, l in enumerate(lines):
        if pending and re.search(pending[0][1], l["text"]):
            starts.append((pending.pop(0)[0], i))
    if pending:
        raise ValueError(f"section starts not found: {[t for t, _ in pending]}")
    out = []
    for k, (title, i) in enumerate(starts):
        j = starts[k + 1][1] if k + 1 < len(starts) else len(lines)
        body = lines[i + 1:j] if lines[i]["heading"] else lines[i:j]
        out.append((title, body))
    return out


def reference_entries(lines, book, doc):
    """One bibliography paragraph per reference. Numbered lists split at each next number in
    sequence; author-date lists (hanging indent) split where a line starts at the column edge."""
    if book.get("refs") == "hanging":
        left = {}
        for l in lines:
            key = (l["p"], l["x0"] > doc[l["p"]].rect.width / 2)
            left[key] = min(left.get(key, 1e9), l["x0"])
        entries, cur = [], []
        for l in lines:
            key = (l["p"], l["x0"] > doc[l["p"]].rect.width / 2)
            starts = re.match(r"\*|[A-ZÀ-Ž][\w'’\- ]+,\s(?:[A-Z]\.|&)|[A-Z][\w ]+\.\s\(\d{4}", l["text"])
            if cur and l["x0"] - left[key] < 2 and starts:
                entries.append(cur)
                cur = []
            cur.append(l)
        entries.append(cur)
        text = []
        for e in entries:
            t = ""
            for l in e:
                t = BB.rejoin_hyphen(t, l["text"]) if t else l["text"]
            text.append(t)
    else:
        whole = ""
        for l in lines:
            whole = BB.rejoin_hyphen(whole, l["text"]) if whole else l["text"]
        text, n, pos = [], 1, 0
        while True:
            m = re.compile(rf"(?:^|\s){n + 1}\. (?=[A-Za-z])").search(whole, pos)
            text.append(whole[pos:m.start() if m else len(whole)])
            if not m:
                break
            pos, n = m.start() + (1 if whole[m.start()].isspace() else 0), n + 1
    out = []
    for t in text:
        t = re.sub(r"\s+", " ", t).strip()
        t = re.sub(r"(https?://|doi:)\s+", r"\1", t)
        t = re.sub(r"(10\.\d{4,})\s+/", r"\1/", t)
        if t:
            out.append(t)
    return out


MENTION = r"(?<!Appendix )\b{kind}s?\s+{num}\b"


def anchor_visuals(chapters, visuals):
    """Each visual goes right after the first paragraph that cites it ("Table 2", "Tables 1
    and 2" is not matched on purpose: the first exact mention wins); continuation pages follow
    their first page. Appendix visuals go to the Appendix chapter, in order."""
    placed = {}
    for v in visuals:
        if v["appendix"]:
            continue
        key = (v["kind"], v["number"])
        if key not in placed:
            rx = re.compile(MENTION.format(kind=v["kind"].capitalize(), num=v["number"]), re.I)
            hit = next(((c, i) for c in chapters if not c.get("bib")
                        for i, p in enumerate(c["paragraphs"]) if rx.search(p)), None)
            if hit is None:
                raise ValueError(f"no paragraph mentions {v['label']}")
            placed[key] = hit
        c, i = placed[key]
        c.setdefault("visuals", []).append(public(v, i))


def public(v, after):
    return {"id": v["id"], "kind": v["kind"], "label": v["label"], "src": v["src"],
            "w": v["w"], "h": v["h"], "after": after}


def build(slug):
    book = SPECS[slug]
    doc = pymupdf.open(book["pdf"])
    out_dir = BOOKS / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    visuals = crop_visuals(doc, book, out_dir)
    lines = drop_between(text_lines(doc, book, visuals), book)
    DOC_WORDS.clear()
    DOC_WORDS.update(doc_words(lines))
    sections = split_sections(lines, book)

    chapters, bib, fixes = [], [], Counter()
    for title, sl in sections:
        if title == "References":
            bib = reference_entries(sl, book, doc)
            continue
        paras, fx = section_paragraphs(sl)
        fixes.update(fx)
        chapters.append({"title": title, "paragraphs": paras})
    for n, c in enumerate(chapters, 1):
        w = sum(len(p.split()) for p in c["paragraphs"])
        c.update(n=n, words=w, fullWords=w, excerpt=False)
    anchor_visuals(chapters, visuals)
    appendix = [v for v in visuals if v["appendix"]]
    if bib:
        w = sum(len(p.split()) for p in bib)
        chapters.append({"n": 100 + len(chapters), "label": "Refs", "bib": True, "title": "References",
                         "paragraphs": bib, "words": w, "fullWords": w, "excerpt": False})
    if appendix:
        note = "Supplementary tables and figures from the article's appendix, shown as published."
        chapters.append({"n": 100 + len(chapters), "label": "App", "bib": True, "textOnlyNote": "Text only — appendix",
                         "title": "Appendix: Tables and Figures", "paragraphs": [note], "words": len(note.split()),
                         "fullWords": len(note.split()), "excerpt": False,
                         "visuals": [public(v, 0) for v in appendix]})
    # build_book's gates: coverage is measured against the text that was meant to be kept
    BB.FILTERED.clear()
    g, problems, warnings = BB.gates(lines, chapters, bib, len(doc), sum(len(l["text"]) for l in lines))
    if fixes:
        warnings.append(f"repaired {sum(fixes.values())} split words, e.g. {list(fixes)[:6]}")
    data = {"slug": slug, "title": book["title"], "subtitle": book["subtitle"], "author": book["author"],
            "accent": book["accent"], "narration": {"omitInTextCitations": True,
                                                               **({"citationStyle": book["citation_style"]} if book.get("citation_style") else {})}, "chapters": chapters}
    (out_dir / "book.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    page = doc[0]
    scale = 480 / page.rect.width
    page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(out_dir / "cover.png")
    report = {"slug": slug, "pdf": str(book["pdf"]), "method": "batch-2026-10-26-papers", "gates": g,
              "problems": problems, "warnings": warnings,
              "visuals": [{"id": v["id"], "label": v["label"], "page": v["page"]} for v in visuals],
              "chapters": [{"n": c["n"], "title": c["title"], "paragraphs": len(c["paragraphs"]), "words": c["words"],
                            "visuals": [v["id"] for v in c.get("visuals", [])]} for c in chapters],
              "result": "PASS" if not problems else "FAIL"}
    (out_dir / "ingest-report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    return report


def preview(slugs):
    for slug in slugs:
        book = SPECS[slug]
        doc = pymupdf.open(book["pdf"])
        out = Path(os.environ.get("PREVIEW", "/tmp")) / slug
        vs = crop_visuals(doc, book, out)
        for v in vs:
            print(slug, v["id"], v["label"], "p", v["page"], [round(x) for x in v["rect"]], f'{v["w"]}x{v["h"]}')
        with open(out / "lines.txt", "w") as fh:
            for l in text_lines(doc, book, vs):
                fh.write(f'p{l["p"]+1} {l["font"][-14:]:>14} {l["size"]:>4} {"B" if l["bold"] else " "} | {l["text"]}\n')


if __name__ == "__main__":
    if sys.argv[1:2] == ["preview"]:
        preview(sys.argv[2:] or list(SPECS))
    else:
        ok = True
        for slug in sys.argv[1:] or list(SPECS):
            r = build(slug)
            ok &= r["result"] == "PASS"
            print(json.dumps(r, indent=1, ensure_ascii=False))
        sys.exit(0 if ok else 1)
