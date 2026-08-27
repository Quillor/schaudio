#!/usr/bin/env python3
"""Extract every chapter of each PDF into app/books/<slug>/book.json.

Chapter ranges come from the PDF's own outline. Each chapter is capped at
MAX_WORDS so the demo's narration stays a sane size — a full textbook
chapter runs 10-15k words, which at two voices would be gigabytes of MP3.
Raise MAX_WORDS (or set it to None) to ingest chapters in full.
"""

import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
MAX_WORDS = 700

BOOKS = [
    {
        "slug": "lifespan",
        "pdf": "/Users/timrosenberg/Downloads/TheLifeSpanHumanDevelopmentforHelpingProfessionals.pdf",
        "title": "The Life Span",
        "subtitle": "Human Development for Helping Professionals",
        "author": "Broderick & Blewitt",
        "accent": "teal",
        "chapter_re": r"^\d+\s+\S",
    },
    {
        "slug": "counseling",
        "pdf": "/Users/timrosenberg/Downloads/Theory and Practice of Counseling and Psychotherapy.pdf",
        "title": "Theory and Practice of Counseling and Psychotherapy",
        "subtitle": "Eleventh Edition",
        "author": "Gerald Corey",
        "accent": "violet",
        "chapter_re": r"^Chapter \d+",
    },
    {
        "slug": "wampold-common-factors",
        "pdf": "/Users/timrosenberg/Downloads/Wampold_2015.pdf",
        "title": "How Important Are the Common Factors in Psychotherapy?",
        "subtitle": "An Update · World Psychiatry 2015;14:270-277",
        "author": "Bruce E. Wampold",
        "accent": "teal",
        # No PDF outline: sections come from heading lines in the text. Short
        # enough to ingest whole, so no word cap.
        "mode": "sections",
        "max_words": None,
        "sections": [
            ("Introduction", r"^SPECIAL ARTICLE$"),
            ("The contextual model", r"^THE CONTEXTUAL MODEL$"),
            ("Evidence for various common factors", r"^EVIDENCE FOR VARIOUS COMMON FACTORS$"),
            ("Specific effects", r"^SPECIFIC EFFECTS$"),
            ("Conclusions", r"^CONCLUSIONS$"),
        ],
        "stop_re": r"^References\s*$",
    },
    {
        "slug": "research-methods",
        "pdf": "/Users/timrosenberg/Downloads/ResearchMethodsClinPsych.pdf",
        "title": "Research Methods in Clinical Psychology",
        "subtitle": "An Introduction for Students and Practitioners",
        "author": "Barker, Pistrang & Elliott",
        "accent": "orange",
        "chapter_re": r"^\d+\s+\S",
    },
]

NOISE = [
    re.compile(r"^\s*\d+\s*$"),
    re.compile(r"^\s*\d*\s*CHAPTER\s*\d+\s*[•·]", re.I),
    re.compile(r"^[A-Za-z][A-Za-z\s’'&,-]+\s+\d+\s*$"),
    re.compile(r"^\s*\d+\s+Chapter\s+\w+", re.I),
    re.compile(r"Copyright \d{4} Cengage", re.I),
    re.compile(r"May not be copied, scanned", re.I),
    re.compile(r"Editorial review has deemed", re.I),
    re.compile(r"Cengage Learning reserves the right", re.I),
    re.compile(r"^\s*(WCN|ISBN)\b", re.I),
    re.compile(r"due to electronic rights", re.I),
    # Wiley stamps a download banner across every page of the article PDF.
    re.compile(r"Downloaded from https://onlinelibrary\.wiley\.com", re.I),
    re.compile(r"onlinelibrary\.wiley\.com/terms-and-conditions", re.I),
    re.compile(r"^\s*Key words:", re.I),
    re.compile(r"^\s*\(World Psychiatry \d{4}", re.I),
    re.compile(r"^Department of .*(University|Center|Centre)", re.I),
    re.compile(r"^\s*DOI \d", re.I),
]


LIGATURES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
    "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st",
}


def normalise(text):
    for bad, good in LIGATURES.items():
        text = text.replace(bad, good)
    return (text.replace("\u2018", "'").replace("\u2019", "'")
                .replace("\u201c", '"').replace("\u201d", '"'))


def clean_page(text):
    text = normalise(text)
    lines = []
    for line in text.split("\n"):
        line = line.replace("\xa0", " ").rstrip()
        if any(rx.search(line) for rx in NOISE):
            continue
        lines.append(line)
    return "\n".join(lines)


# Prefixes that legitimately keep their hyphen, so "meta-\nanalyses" rejoins as
# "meta-analyses" rather than "metaanalyses" (which TTS mangles).
HYPHEN_PREFIXES = {
    "meta", "self", "non", "pre", "post", "anti", "co", "re", "well", "cross",
    "semi", "multi", "inter", "intra", "sub", "over", "under", "long", "short",
    "high", "low", "evidence", "person", "problem", "decision", "de", "re",
}


def _rejoin(match):
    left, right = match.group(1), match.group(2)
    tail = re.split(r"[^A-Za-z]", left)[-1].lower()
    return f"{left}-{right}" if tail in HYPHEN_PREFIXES else f"{left}{right}"


# A numbered list item ("7. Describe the four phases...") is real content even
# when it is under the 12-word bar that filters out page furniture. Without this
# every short objective/step silently vanished, leaving lists that skip numbers.
# Two digits max and a following space keep years ("1963.") and page numbers out;
# reference entries start with an author name or "(2006).", so they stay dropped.
LIST_ITEM = re.compile(r"^\d{1,2}[.)]\s+\S")


def to_paragraphs(raw):
    raw = re.sub(r"(\w+)-\n(\w+)", _rejoin, raw)
    paras, buf = [], []

    def flush():
        if buf:
            p = re.sub(r"\s+", " ", " ".join(buf)).strip()
            n_words = len(p.split())
            if n_words >= 12 or (n_words >= 4 and LIST_ITEM.match(p)):
                paras.append(p)
            buf.clear()

    lines = [l.strip() for l in raw.split("\n")]
    body = [len(l) for l in lines if len(l) > 20]
    # Journal PDFs have no blank line between paragraphs; the giveaway is a
    # line noticeably shorter than the justified column width.
    full = sorted(body)[len(body) // 2] if body else 0

    for line in lines:
        s = line
        if not s:
            flush()
            continue
        if len(s) < 60 and (s.isupper() or (s == s.title() and " " in s and not s.endswith((".", ",", ";", ":")))):
            flush()
            continue
        buf.append(s)
        if full and len(s) < full * 0.82 and s.endswith((".", "?", "!", '"')):
            flush()
    flush()
    return paras


# A chapter's trailing References section is real text but useless narration:
# hours of "Erikson, E. H. (1963)." read aloud. Split it into its own entry so
# the app can present "Chapter N-A: Bibliography" and users can skip it whole.
REF_LIKE = re.compile(r"\(\d{4}[a-z]?\)\.|\b[A-Z][A-Za-z'-]+,\s+[A-Z]\.(\s*[A-Z]\.)*")


def _is_ref(p):
    hits = len(REF_LIKE.findall(p))
    return hits >= 2 or (hits >= 1 and len(p.split()) < 22)


def split_bib(paras, min_tail=8):
    """Split (body, bibliography). The bibliography is the tail run that opens
    with four straight reference-shaped paragraphs and stays >=70% reference-
    shaped to the end; shorter tails stay in the body (in-text citations are
    dense in places, and a false split would silence real prose)."""
    flags = [_is_ref(x) for x in paras]
    for i in range(len(paras)):
        tail = flags[i:]
        if len(tail) >= min_tail and all(tail[:4]) and sum(tail) / len(tail) >= 0.7:
            return paras[:i], paras[i:]
    return paras, []


def chapter_spans(reader, chapter_re):
    """[(title, start_page, end_page)] from the PDF's top-level outline."""
    entries = []
    for item in reader.outline:
        if isinstance(item, list):
            continue
        title = item.title.replace("\xa0", " ").strip()
        if not re.match(chapter_re, title):
            continue
        try:
            page = reader.get_destination_page_number(item)
        except Exception:
            continue
        entries.append((title, page))
    spans = []
    for i, (title, start) in enumerate(entries):
        end = entries[i + 1][1] if i + 1 < len(entries) else min(start + 40, len(reader.pages))
        spans.append((title, start, end))
    return spans


def section_spans(reader, spec):
    """[(title, [lines])] for PDFs with no outline: split on heading lines."""
    lines = []
    for page in reader.pages:
        lines.extend(clean_page(page.extract_text() or "").split("\n"))

    stop = re.compile(spec["stop_re"]) if spec.get("stop_re") else None
    if stop:
        for i, line in enumerate(lines):
            if stop.match(line.strip()):
                lines = lines[:i]
                break

    marks = []
    for title, pattern in spec["sections"]:
        rx = re.compile(pattern)
        for i, line in enumerate(lines):
            if rx.match(line.strip()):
                marks.append((title, i))
                break

    marks.sort(key=lambda m: m[1])
    spans = []
    for i, (title, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(lines)
        spans.append((title, lines[start + 1:end]))
    return spans


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for spec in BOOKS:
        if only and spec["slug"] != only:
            continue
        reader = PdfReader(spec["pdf"])
        cap = spec.get("max_words", MAX_WORDS)
        if spec.get("mode") == "sections":
            raw_spans = [(t, "\n".join(ls)) for t, ls in section_spans(reader, spec)]
        else:
            raw_spans = [
                (t, "\n\n".join(clean_page(reader.pages[i].extract_text() or "")
                                 for i in range(a, min(b, len(reader.pages)))))
                for t, a, b in chapter_spans(reader, spec["chapter_re"])
            ]
        chapters = []
        for n, (title, raw) in enumerate(raw_spans, 1):
            paras = to_paragraphs(raw)
            kept, count = [], 0
            for p in paras:
                w = len(p.split())
                if cap and count and count + w > cap:
                    break
                kept.append(p)
                count += w
            if not kept:
                continue
            chapters.append({"n": n, "title": title, "paragraphs": kept, "words": count})

        out = ROOT / "app" / "books" / spec["slug"]
        out.mkdir(parents=True, exist_ok=True)
        (out / "book.json").write_text(json.dumps({
            "slug": spec["slug"],
            "title": spec["title"],
            "subtitle": spec["subtitle"],
            "author": spec["author"],
            "accent": spec["accent"],
            "chapters": chapters,
        }, indent=1) + "\n")
        total = sum(c["words"] for c in chapters)
        print(f"{spec['slug']}: {len(chapters)} chapters, {total} words")


if __name__ == "__main__":
    main()
