#!/usr/bin/env python3
"""Generic PDF -> Schaudio book builder with quality gates. Used by the Hermes pipeline.

  build_book.py inspect <pdf>                      metadata candidates + structure plan (JSON)
  build_book.py build <pdf> <slug> --title T [--subtitle S] [--author A] [--accent teal]
                                                  writes app/books/<slug>/{book.json,cover.png,ingest-report.json}

Exit code of `build`: 0 = every gate passed, 1 = a gate failed (book.json is still written so a
human can look, but the pipeline must not narrate it), 2 = unusable input.

Pipeline: pymupdf spans (size/bold) per line -> drop running headers/footers (lines that repeat
across pages) and page numbers -> sections from the PDF outline, else from heading fonts, else
fixed-size parts -> paragraphs from text blocks (hyphen rejoin, bullets folded, page-break
continuation) -> references split off as a bibliography chapter (not narrated) -> gates.
"""
from __future__ import annotations

import argparse
import os
import hashlib
import json
import re
import statistics
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ingest import HYPHEN_PREFIXES, normalise  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BOOKS = Path(os.environ.get("SCHAUDIO_BOOKS", ROOT / "app" / "books"))
ACCENTS = ["teal", "violet", "orange"]

BULLETS = "●○■□◆◇▪▫•‣◦–-*"
REF_HEADINGS = re.compile(r"^(references|bibliography|works cited|literature cited|reference list)\s*$", re.I)
STOP_AFTER_REFS = re.compile(r"^(appendix|author (and article )?information|acknowledg)", re.I)
BOILERPLATE = [re.compile(p, re.I) for p in (
    r"^copyright\b", r"^©", r"all rights reserved", r"may not be (copied|reproduced)", r"reproduced with permission",
    r"further reproduction prohibited", r"downloaded from https?://", r"terms-and-conditions", r"^doi:?\s*10\.",
    r"^https?://\S+$", r"^isbn\b", r"editorial review has deemed", r"reserves the right to remove",
    r"^all rights, including",
)]
MAX_PARA_WORDS = 320       # longer paragraphs are split at sentence ends (sync + TTS stay reliable)
MIN_SECTION_WORDS = 200    # smaller sections merge into the next one (titles kept as lead-ins)
PART_WORDS = 2500          # fallback split size when a document has no usable headings
MAX_BOOK_WORDS = 150_000   # beyond this narration takes days; hold for Tim
DICT = None
HEADING_END = {}
FILTERED = []  # front-matter paragraphs removed (reported)
SYNTHETIC = {"Introduction", "Full text"}  # titles the builder invents; never read aloud as lead-ins  # heading start line -> last line of a multi-line heading
# Journal front matter. LONG_FM notices are removed whatever their length; SHORT_FM labels only
# remove a short paragraph (a wrapped keyword line can glue onto the first real paragraph).
LONG_FM = [re.compile(p, re.I) for p in (
    r"this (document|article) is copyrighted", r"solely for the personal use", r"contributed equally",
    r"writing\s*[–-]\s*(original draft|review)", r"^(\d+\s*)?(department|school|faculty|division) of\b.*(university|college|institute)",
)]
SHORT_FM = [re.compile(p, re.I) for p in (
    r"^issn\b", r"\bvol\. \d+, no\. \d+", r"published online first", r"correspondence concerning this article",
    r"^received:? .*accepted", r"^(key\s?words|keywords)\s*:", r"supplemental materials?:", r"^e-?mail:",
    r"conflicts? of interest", r"^orcid\b", r"^author note\b",
)]


# ---------------------------------------------------------------- extraction

OCR_BIN = Path.home() / ".cache" / "schaudio" / "ocr_vision"
OCR_MIN_CHARS = 80  # a page with less text-layer than this is treated as a scan
OCR_STATS = {"pages": 0, "confidence": []}


def ocr_binary():
    src = Path(__file__).resolve().parent / "ocr_vision.swift"
    if not OCR_BIN.exists() or OCR_BIN.stat().st_mtime < src.stat().st_mtime:
        OCR_BIN.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["xcrun", "swiftc", "-O", str(src), "-o", str(OCR_BIN)], check=True, capture_output=True)
    return OCR_BIN


def ocr_lines(page, pno):
    """Vision OCR of one scanned page -> lines shaped like page_lines() output."""
    with tempfile.TemporaryDirectory() as tmp:
        img = Path(tmp) / f"p{pno}.png"
        page.get_pixmap(matrix=pymupdf.Matrix(3, 3), alpha=False).save(img)
        r = subprocess.run([str(ocr_binary()), str(img)], capture_output=True, text=True, check=True)
    got = json.loads(r.stdout.strip().splitlines()[-1])["lines"]
    OCR_STATS["pages"] += 1
    # Scans of book spreads catch a strip of the facing page. The main text block spans the
    # margins of the long lines; anything wholly outside it is bleed.
    long = [g for g in got if g["w"] > 0.3]
    if len(long) >= 5:
        left = sorted(g["x"] for g in long)[len(long) // 10]
        right = sorted(g["x"] + g["w"] for g in long)[-(len(long) // 10) - 1]
        bleed = [g for g in got if g["x"] + g["w"] < left + 0.01 or g["x"] > right - 0.01
                 or (g["x"] < left - 0.04 and g["w"] < 0.25) or (g["x"] + g["w"] > right + 0.04 and g["w"] < 0.25)]
        OCR_STATS["bleed_dropped"] = OCR_STATS.get("bleed_dropped", 0) + len(bleed)
        got = [g for g in got if g not in bleed]
    rows = []
    for g in got:
        text = re.sub(r"\s+", " ", normalise(g["text"])).strip()
        if not text:
            continue
        OCR_STATS["confidence"].append(g["confidence"])
        col = 1 if g["x"] > 0.48 and g["w"] < 0.5 else 0
        rows.append((col, 1 - g["y"] - g["h"], 1 - g["y"], text, g["h"] * page.rect.height, g["x"]))
    rows.sort(key=lambda r: (r[0], r[1]))
    out, block, prev = [], 0, None
    for col, y0, y1, text, size, x in rows:
        if prev and (col != prev[0] or y0 - prev[2] > (prev[2] - prev[1]) * 0.9 or abs(x - prev[5]) > 0.03):
            block += 1
        out.append({"p": pno, "y0": y0, "y1": y1, "text": text, "size": round(size * 0.75, 1), "bold": False,
                    "block": (pno, 10_000 + block), "ocr": True})
        prev = (col, y0, y1, text, size, x)
    return out


def page_lines(doc):
    """[(page_no, y0, y1, text, size, bold, block_id)] for every text line, in reading order.
    Pages without a usable text layer are OCR'd with macOS Vision."""
    out = []
    for pno, page in enumerate(doc):
        h = page.rect.height
        if len(page.get_text().strip()) < OCR_MIN_CHARS and page.get_images():
            out.extend(ocr_lines(page, pno))
            continue
        d = page.get_text("dict", sort=True)
        for bi, block in enumerate(d["blocks"]):
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                text = normalise("".join(s["text"] for s in line["spans"])).replace("​", "").replace("\xa0", " ")
                text = re.sub(r"\s+", " ", text).strip()
                if not text:
                    continue
                chars = sum(len(s["text"]) for s in spans)
                size = sum(s["size"] * len(s["text"]) for s in spans) / chars
                bold = sum(len(s["text"]) for s in spans if s["flags"] & 16 or "Bold" in s["font"]) / chars > 0.6
                out.append({"p": pno, "y0": line["bbox"][1] / h, "y1": line["bbox"][3] / h, "text": text,
                            "size": round(size, 1), "bold": bold, "block": (pno, bi)})
    return out


def shape(text):
    return re.sub(r"\d+", "#", text.lower()).strip()


def drop_noise(lines, n_pages):
    """Remove running headers/footers, page numbers and publisher boilerplate. A running header
    is a short line (digits ignored) in the top or bottom 15% of the page that recurs on many
    distinct pages; scanned spreads put it well below the paper edge, hence the wide band."""
    at_edge = lambda l: l["y0"] < 0.15 or l["y1"] > 0.85  # noqa: E731
    pages_with = {}
    for l in lines:
        if at_edge(l) and len(l["text"]) < 90:
            pages_with.setdefault(shape(l["text"]).strip("# "), set()).add(l["p"])
    min_rep = max(3, int(n_pages * 0.2))
    repeated = {k for k, v in pages_with.items() if len(v) >= min_rep and k}
    # Short lines that recur on many distinct pages anywhere (scan headers that sit mid-margin)
    anywhere = {}
    for l in lines:
        if len(l["text"].split()) <= 8:
            anywhere.setdefault(l["text"].lower(), set()).add(l["p"])
    exact = {k for k, v in anywhere.items() if len(v) >= max(3, int(n_pages * 0.25)) and re.search(r"[a-z]{3}", k)}
    kept, dropped = [], []
    for l in lines:
        t = l["text"]
        if t.lower() in exact or (at_edge(l) and (shape(t).strip("# ") in repeated or re.fullmatch(r"(page )?\d{1,4}( of \d+)?", t, re.I))) \
                or any(rx.search(t) for rx in BOILERPLATE):
            dropped.append(l)
        else:
            kept.append(l)
    return kept, dropped


def body_size(lines):
    c = Counter()
    for l in lines:
        c[l["size"]] += len(l["text"])
    return c.most_common(1)[0][0] if c else 10.0


# ---------------------------------------------------------------- sections

def clean_title(t):
    return re.sub(r"\s+", " ", normalise(t)).strip(" .:​")


def outline_sections(doc, lines):
    """Pick an outline level with a sensible number of sections; map entries onto line indices."""
    toc = [(lvl, clean_title(t), page, dest) for lvl, t, page, dest in doc.get_toc(simple=False) if clean_title(t)]
    if not toc:
        return None
    best = None
    for level in sorted({t[0] for t in toc}):
        entries = [t for t in toc if t[0] == level]
        if 2 <= len(entries) <= 80:
            best = level
            break
    if best is None:
        return None
    starts = []
    for lvl, title, page, dest in toc:
        if lvl > best:
            continue
        key = re.sub(r"\W+", "", title.lower())[:24]
        cands = [i for i, l in enumerate(lines) if l["p"] == page - 1]
        hit = next((i for i in cands if key and re.sub(r"\W+", "", l_text(lines, i).lower()).startswith(key[:16])), None)
        if hit is None and cands:
            y = (dest.get("to") or (0, 0))[1] / doc[page - 1].rect.height if isinstance(dest, dict) and dest.get("to") else 0
            hit = next((i for i in cands if lines[i]["y0"] >= y - 0.02), cands[0])
        if hit is not None and (not starts or hit > starts[-1][1]):
            starts.append((title, hit))
    return starts if len(starts) >= 2 else None


def l_text(lines, i):
    return lines[i]["text"]


def heading_sections(lines, body):
    """Headings = short standalone lines that are larger than body text, bold, or ALL CAPS.
    Each candidate gets a rank (font size, +0.5 for caps); the highest rank tier that yields
    at least 3 headings wins, so a big article title alone never becomes the only section."""
    block_len = Counter(l["block"] for l in lines)
    ranked = {}
    for i, l in enumerate(lines):
        t = l["text"]
        if len(t.split()) > 12 or t.endswith((",", ";", "-")) or not re.search(r"[A-Za-z]{3}", t) \
                or block_len[l["block"]] > 3 or REF_HEADINGS.match(t) is None and re.fullmatch(r"[\d\W]+", t):
            continue
        size = body if l.get("ocr") else l["size"]
        caps = t.isupper() and len(re.findall(r"[A-Z]{2,}", t)) >= 1
        if size >= body * 1.15 or (l["bold"] and size >= body) or caps:
            ranked[i] = round(size, 1) + (0.5 if caps else 0) + (0.2 if l["bold"] else 0)
    if not ranked:
        return None
    for tier in sorted(set(ranked.values()), reverse=True):
        idx = sorted(i for i, r in ranked.items() if r >= tier)
        merged = []
        for i in idx:  # multi-line headings: consecutive heading lines of one tier join
            if merged and i == merged[-1][2] + 1 and ranked[i] == ranked[merged[-1][2]]:
                merged[-1] = (merged[-1][0] + " " + lines[i]["text"], merged[-1][1], i)
            else:
                merged.append((lines[i]["text"], i, i))
        if len(merged) > 60:
            break
        if len(merged) >= 3:
            return [(clean_title(t), start, stop) for t, start, stop in merged]
    return None


# ---------------------------------------------------------------- paragraphs

def rejoin_hyphen(a, b):
    m = re.search(r"(\w+)-$", a)
    if not m:
        return a + " " + b
    word = m.group(1).lower()
    return (a + b) if word in HYPHEN_PREFIXES else (a[:-1] + b)


def is_figure_text(p):
    """Labels lifted out of a figure: runs of 1-3 word fragments or abbreviation lists, no prose."""
    frags = [f for f in re.split(r"[.;]\s+|,\s+", p.strip(" .")) if f]
    words = p.split()
    if len(words) > 40 or len(frags) < 3:
        return False
    short = sum(1 for f in frags if len(f.split()) <= 3) / len(frags)
    abbrev = sum(1 for w in words if re.fullmatch(r"[A-Z]{2,4}[.,]?", w)) / len(words)
    titled = all(w[:1].isupper() or w in ("&", "and", "of", "the", "in") for w in words)
    return short >= 0.9 and (abbrev >= 0.5 or titled)


def paragraphs_from(lines):
    paras, cur, last = [], "", None
    for l in lines:
        t = l["text"]
        bullet = t[:1] in BULLETS and (len(t) > 1 and t[1] == " " or t[:1] in "●○■◆▪•")
        if bullet:
            t = t.lstrip(BULLETS).strip()
        new_block = last is None or l["block"] != last["block"]
        gap_para = last is not None and l["p"] == last["p"] and l["y0"] - last["y1"] > 0.018
        # a line that starts lowercase after an unfinished sentence continues it (wrapped bullet,
        # page break, or a PDF that puts every visual line in its own block)
        cont = bool(cur) and not bullet and not re.search(r"[.!?:\"”]$", cur) and (t[:1].islower() or t[:1] in "(&")
        if cur and (bullet or ((gap_para or new_block) and not cont)):
            paras.append(cur)
            cur = ""
        cur = rejoin_hyphen(cur, t) if cur else t
        last = l
    if cur:
        paras.append(cur)
    out = []
    for p in paras:
        n = len(p.split())
        if (n < 250 and any(rx.search(p) for rx in LONG_FM)) or (n < 40 and any(rx.search(p) for rx in SHORT_FM)) \
                or is_figure_text(p):
            FILTERED.append(p)
            continue
        p = re.sub(r"\s*→\s*", " — ", p)
        p = re.sub(r"\s+([,.;:)])", r"\1", re.sub(r"\s+", " ", p)).strip()
        if p:
            out.append(p)
    return out


def tidy(paras):
    """Fold tiny fragments (sub-headings, labels) into the next paragraph; split huge ones."""
    out, carry = [], ""
    for p in paras:
        if carry:
            p = f"{carry}{'' if carry.endswith(('.', ':', '?', '!')) else '.'} {p}"
            carry = ""
        if len(p.split()) < 8 and not p.endswith((".", "?", "!")):
            carry = p
            continue
        out.append(p)
    if carry:
        out.append(carry)
    final = []
    for p in out:
        words = p.split()
        if len(words) <= MAX_PARA_WORDS:
            final.append(p)
            continue
        sents = re.split(r"(?<=[.!?])\s+(?=[A-Z\"(])", p)
        chunk = ""
        for s in sents:
            if chunk and len((chunk + " " + s).split()) > MAX_PARA_WORDS * 0.8:
                final.append(chunk)
                chunk = s
            else:
                chunk = f"{chunk} {s}".strip()
        if chunk:
            final.append(chunk)
    return final


# ---------------------------------------------------------------- quality

def dictionary():
    global DICT
    if DICT is None:
        p = Path("/usr/share/dict/words")
        DICT = {w.strip().lower() for w in p.read_text().splitlines()} if p.exists() else set()
    return DICT


def is_word(w):
    d = dictionary()
    w = w.lower()
    return w in d or (w.endswith("s") and w[:-1] in d) or (w.endswith("es") and w[:-2] in d) \
        or (w.endswith("ed") and (w[:-2] in d or w[:-1] in d)) or (w.endswith("ing") and (w[:-3] in d or w[:-3] + "e" in d)) \
        or (w.endswith("ly") and w[:-2] in d)


def repair_splits(text, fixes):
    """'speci fic' -> 'specific' when neither half is a word but the join is (ligature damage)."""
    def fix(m):
        a, b = m.group(1), m.group(2)
        if dictionary() and not is_word(a) and is_word(a + b) and (not is_word(b) or len(b) <= 3):
            fixes[f"{a} {b}"] += 1
            return a + b
        return m.group(0)
    return re.sub(r"\b([A-Za-z]{2,})\s(fi\w*|fl\w*|ff\w*|[a-z]{1,3})\b", fix, text)


def tokens(s):
    return re.findall(r"[a-z0-9]+", s.lower())


def gates(source_lines, chapters, bib, n_pages, total_chars):
    g, problems, warnings = {}, [], []
    g["chars_per_page"] = round(total_chars / max(n_pages, 1))
    if g["chars_per_page"] < 200 and not OCR_STATS["pages"]:
        problems.append(f"almost no text layer ({g['chars_per_page']} chars/page): scanned PDF, needs OCR")
    narr = [c for c in chapters if not c.get("bib")]
    words = sum(c["words"] for c in narr)
    g["words"], g["chapters"] = words, len(narr)
    if words < 150:
        problems.append(f"only {words} narratable words")
    if not 1 <= len(narr) <= 80:
        problems.append(f"{len(narr)} chapters (expected 1-80)")
    empty = [c["title"] for c in narr if c["words"] < 20]
    if empty:
        problems.append(f"near-empty chapters: {empty[:5]}")
    if words > MAX_BOOK_WORDS:
        problems.append(f"{words} words is more than {MAX_BOOK_WORDS}; days of narration, needs Tim's OK")
    src_text = ""
    for l in source_lines:
        src_text = rejoin_hyphen(src_text, l["text"]) if src_text else l["text"]
    src = Counter(tokens(src_text.replace("→", " "))) - Counter(tokens(" ".join(FILTERED)))
    out = Counter(tokens(" ".join(p for c in chapters for p in c["paragraphs"]) + " " +
                         " ".join(c["title"] for c in chapters)))
    lost = src - out
    lost_n = sum(v for k, v in lost.items() if len(k) > 1)
    g["coverage"] = round(1 - lost_n / max(sum(src.values()), 1), 4)
    if g["coverage"] < 0.97:
        problems.append(f"text coverage {g['coverage']:.1%} < 97% (lost e.g. {[k for k, _ in lost.most_common(12)]})")
    all_text = " ".join(p for c in narr for p in c["paragraphs"])
    toks = re.findall(r"[A-Za-z]+", re.sub(r"\b(?:[A-Za-z]\.){2,}|(?:^|\s)[a-zA-Z][.)](?=\s)", " ", all_text))
    spaced = len(re.findall(r"\b(?:[a-z] ){4,}[a-z]\b", all_text))
    g["spaced_letter_runs"] = spaced
    if spaced > 3:
        problems.append(f"{spaced} runs of spaced-out letters (broken text extraction)")
    singles = sum(1 for t in toks if len(t) == 1 and t.lower() not in ("a", "i"))
    g["stray_letters"] = round(singles / max(len(toks), 1), 4)
    if g["stray_letters"] > 0.05:
        problems.append(f"{g['stray_letters']:.1%} stray single letters (garbled extraction)")
    if dictionary():
        long = [t for t in toks if len(t) >= 4 and t.islower()]
        unknown = sum(1 for t in long if not is_word(t))
        g["unknown_word_rate"] = round(unknown / max(len(long), 1), 4)
        if g["unknown_word_rate"] > 0.15:
            problems.append(f"{g['unknown_word_rate']:.0%} of lowercase words not in the dictionary (garbled text?)")
        elif g["unknown_word_rate"] > 0.08:
            warnings.append(f"{g['unknown_word_rate']:.0%} unknown lowercase words (jargon or damage)")
    if OCR_STATS["pages"]:
        conf = sum(OCR_STATS["confidence"]) / max(len(OCR_STATS["confidence"]), 1)
        g["ocr_pages"], g["ocr_confidence"] = OCR_STATS["pages"], round(conf, 3)
        warnings.append(f"{OCR_STATS['pages']} scanned page(s) read with OCR (mean confidence {conf:.2f})")
        if conf < 0.9:
            problems.append(f"OCR confidence {conf:.2f} < 0.90: scan too poor to narrate without review")
    if dictionary():
        garbled = []
        for c in narr:
            for p in c["paragraphs"]:
                ws = [w for w in re.findall(r"[A-Za-z]+", p) if len(w) >= 3 and w.islower()]
                if len(ws) >= 6 and sum(1 for w in ws if not is_word(w)) / len(ws) > 0.35:
                    garbled.append(p[:100])
        g["garbled_paragraphs"] = len(garbled)
        if garbled:
            problems.append(f"{len(garbled)} paragraph(s) look garbled (mostly non-words), e.g. {garbled[:3]}")
    if FILTERED:
        warnings.append(f"dropped {len(FILTERED)} front-matter paragraph(s), e.g. {[f[:100] for f in FILTERED[:3]]}")
    if OCR_STATS.get("bleed_dropped"):
        warnings.append(f"cropped {OCR_STATS['bleed_dropped']} OCR line(s) of facing-page bleed")
    g["bibliography_entries"] = len(bib)
    return g, problems, warnings


# ---------------------------------------------------------------- build

def structure(doc):
    raw = page_lines(doc)
    total_chars = sum(len(l["text"]) for l in raw)
    lines, dropped = drop_noise(raw, len(doc))
    body = body_size(lines)
    starts, method = outline_sections(doc, lines), "outline"
    if not starts:
        hs = heading_sections(lines, body)
        starts, method = ([(t, a) for t, a, _ in hs], "headings") if hs else (None, "headings")
        HEADING_END.update({a: b for _, a, b in hs or []})
    if not starts:
        starts, method = [("Full text", 0)], "parts"
    if starts[0][1] > 0:
        starts = [("Introduction", 0)] + starts
    return raw, lines, dropped, body, starts, method, total_chars


def build_chapters(lines, starts, method):
    sections = []
    for k, (title, i) in enumerate(starts):
        j = starts[k + 1][1] if k + 1 < len(starts) else len(lines)
        body_lines = lines[HEADING_END.get(i, i) + 1:j] if method != "parts" and title != "Introduction" else lines[i:j]
        sections.append([title, body_lines])

    # References: split off at a references heading (inside or as a section)
    bib, cut = [], None
    for si, (title, sl) in enumerate(sections):
        if REF_HEADINGS.match(title):
            cut = (si, 0)
            break
        idx = next((k for k, l in enumerate(sl) if REF_HEADINGS.match(l["text"])), None)
        if idx is not None and si >= len(sections) - 2:
            cut = (si, idx)
            break
    if cut:
        si, idx = cut
        ref_lines = sections[si][1][idx + (0 if REF_HEADINGS.match(sections[si][0]) else 1):]
        stop = next((k for k, l in enumerate(ref_lines) if STOP_AFTER_REFS.match(l["text"])), len(ref_lines))
        bib = paragraphs_from(ref_lines[:stop])
        if REF_HEADINGS.match(sections[si][0]):
            sections = sections[:si]
        else:
            sections[si][1] = sections[si][1][:idx]
            sections = sections[:si + 1]

    fixes = Counter()
    wc = lambda c: sum(len(p.split()) for p in c["paragraphs"])  # noqa: E731
    raw_chapters = [{"title": t, "paragraphs": tidy([repair_splits(p, fixes) for p in paragraphs_from(sl)])}
                    for t, sl in sections]
    # Tiny sections (a bare "Chapter 3" heading, a two-line preface) fold into the next
    # section, their titles kept as lead-in sentences so nothing is lost.
    merged, pending = [], []
    for c in raw_chapters:
        if wc(c) < MIN_SECTION_WORDS:
            pending.append(c)
            continue
        if pending:
            lead = [x for q in pending for x in ([f"{q['title']}."] if q["title"] not in SYNTHETIC else []) + q["paragraphs"]]
            c = {"title": c["title"], "paragraphs": tidy(lead + c["paragraphs"])}
            pending = []
        merged.append(c)
    if pending:
        tail = [x for q in pending for x in ([f"{q['title']}."] if q["title"] not in SYNTHETIC else []) + q["paragraphs"]]
        if merged:
            merged[-1]["paragraphs"] = tidy(merged[-1]["paragraphs"] + tail)
        else:
            merged = [{"title": "Full text", "paragraphs": tidy(tail)}]

    # Very long sections (or a document with no headings) split into ~PART_WORDS parts at
    # paragraph boundaries, so a chapter stays a comfortable listening unit.
    split = []
    for c in merged:
        if wc(c) <= PART_WORDS * 2:
            split.append(c)
            continue
        parts, cur, w = [], [], 0
        for p in c["paragraphs"]:
            cur.append(p)
            w += len(p.split())
            if w >= PART_WORDS:
                parts.append(cur)
                cur, w = [], 0
        if cur and parts and w < PART_WORDS / 3:
            parts[-1].extend(cur)
        elif cur:
            parts.append(cur)
        base = "" if c["title"] == "Full text" else c["title"] + ", "
        split += [{"title": f"{base}part {k}" if base else f"Part {k}", "paragraphs": ps} for k, ps in enumerate(parts, 1)]
    merged = split

    out = []
    for n, c in enumerate(merged, 1):
        w = sum(len(p.split()) for p in c["paragraphs"])
        out.append({"n": n, "title": c["title"], "paragraphs": c["paragraphs"], "words": w, "fullWords": w, "excerpt": False})
    if bib:
        w = sum(len(p.split()) for p in bib)
        out.append({"n": 100 + len(out), "label": "Refs", "bib": True, "title": "References", "paragraphs": bib,
                    "words": w, "fullWords": w, "excerpt": False})
    return out, bib, fixes


def inspect(pdf):
    doc = pymupdf.open(pdf)
    raw, lines, dropped, body, starts, method, total_chars = structure(doc)
    meta = {k: v for k, v in (doc.metadata or {}).items() if v and k in ("title", "author", "subject")}
    first = [l for l in raw if l["p"] == 0]
    big = sorted(first, key=lambda l: -l["size"])[:6]
    return {
        "pdf": str(pdf), "pages": len(doc), "sha1": hashlib.sha1(Path(pdf).read_bytes()).hexdigest(),
        "pdf_metadata": meta, "filename": Path(pdf).stem,
        "largest_text_on_page_1": [l["text"] for l in big],
        "page_1_text": " ".join(l["text"] for l in first)[:1500],
        "structure": {"method": method, "sections": [t for t, _ in starts][:80], "body_font": body,
                      "noise_lines_dropped": len(dropped)},
        "chars_per_page": round(total_chars / max(len(doc), 1)),
    }


def build(pdf, slug, title, subtitle, author, accent):
    doc = pymupdf.open(pdf)
    raw, lines, dropped, body, starts, method, total_chars = structure(doc)
    chapters, bib, fixes = build_chapters(lines, starts, method)
    g, problems, warnings = gates(lines, chapters, bib, len(doc), total_chars)
    if fixes:
        warnings.append(f"repaired {sum(fixes.values())} split words, e.g. {list(fixes)[:6]}")
    page1 = " ".join(l["text"] for l in raw if l["p"] <= 2).lower() + " " + Path(pdf).stem.lower()
    for label, value in (("title", title), ("author", author)):
        if value:
            ws = [w for w in tokens(value) if len(w) > 2]
            miss = [w for w in ws if w not in page1]
            if ws and len(miss) > len(ws) * 0.34:
                problems.append(f"{label} {value!r} not found on the first pages (missing {miss}); metadata must come from the PDF")
    out = BOOKS / slug
    out.mkdir(parents=True, exist_ok=True)
    book = {"slug": slug, "title": title, "subtitle": subtitle or "", "author": author or "",
            "accent": accent, "chapters": chapters}
    (out / "book.json").write_text(json.dumps(book, indent=1, ensure_ascii=False) + "\n")
    page = doc[0]
    scale = 480 / page.rect.width
    page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(out / "cover.png")
    report = {"slug": slug, "pdf": str(pdf), "method": method, "gates": g, "problems": problems, "warnings": warnings,
              "chapters": [{"n": c["n"], "title": c["title"], "paragraphs": len(c["paragraphs"]), "words": c["words"]}
                           for c in chapters],
              "sample": [c["paragraphs"][0][:300] for c in chapters[:3] if c["paragraphs"]],
              "result": "PASS" if not problems else "FAIL"}
    (out / "ingest-report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    return report


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("inspect"); s.add_argument("pdf")
    s = sub.add_parser("build"); s.add_argument("pdf"); s.add_argument("slug"); s.add_argument("--title", required=True)
    s.add_argument("--subtitle", default=""); s.add_argument("--author", default=""); s.add_argument("--accent", default="")
    a = ap.parse_args()
    try:
        if a.cmd == "inspect":
            print(json.dumps(inspect(a.pdf), indent=1, ensure_ascii=False))
            return 0
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,60}", a.slug):
            print(json.dumps({"result": "FAIL", "problems": ["slug must be lowercase letters, digits and dashes"]}))
            return 2
        accent = a.accent if a.accent in ACCENTS else ACCENTS[int(hashlib.sha1(a.slug.encode()).hexdigest(), 16) % 3]
        r = build(a.pdf, a.slug, a.title.strip(), a.subtitle.strip(), a.author.strip(), accent)
        print(json.dumps(r, indent=1, ensure_ascii=False))
        return 0 if r["result"] == "PASS" else 1
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"result": "ERROR", "problems": [f"{type(e).__name__}: {e}"]}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
