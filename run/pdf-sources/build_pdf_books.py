#!/usr/bin/env python3
"""Faithfully extract the four assigned PDF sources into Schaudio book data."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import fitz
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from ingest import HYPHEN_PREFIXES, _rejoin, normalise, to_paragraphs  # noqa: E402


SPECS = [
    {
        "slug": "710-ch2-and-3",
        "pdf": Path("/Users/timrosenberg/Downloads/710- Ch2and3.pdf"),
        "title": "The Life Span: Chapters 2 and 3",
        "subtitle": "Human Development for Helping Professionals",
        "author": "Patricia C. Broderick and Pamela Blewitt",
        "accent": "teal",
        "kind": "textbook",
    },
    {
        "slug": "caspi-moffitt-all-for-one",
        "pdf": Path("/Users/timrosenberg/Downloads/712 caspi-moffitt-2018-all-for-one-and-one-for-all.pdf"),
        "title": "All for One and One for All: Mental Disorders in One Dimension",
        "subtitle": "American Journal of Psychiatry, 2018",
        "author": "Avshalom Caspi and Terrie E. Moffitt",
        "accent": "orange",
        "kind": "caspi",
    },
    {
        "slug": "dsm-5-failure",
        "pdf": Path("/Users/timrosenberg/Downloads/712_Mehdi_Is_DSM-5_a_Failure.pdf"),
        "title": "Is DSM-5 a Failure?",
        "subtitle": "Analyzing the Controversies Surrounding the Current American Mental Health Diagnostic Manual",
        "author": "Syed Muhammad Ahsan Mehdi, Barnett Meyers, and D. P. Devanand",
        "accent": "violet",
        "kind": "mehdi",
    },
    {
        "slug": "counseling-values-ethical-dimensions",
        "pdf": Path("/Users/timrosenberg/Downloads/712 Kress_Counseling and Values Ethical Dimensions.pdf"),
        "title": "Ethical Dimensions of Diagnosing",
        "subtitle": "Considerations for Clinical Mental Health Counselors",
        "author": "Victoria E. Kress, Rachel M. Hoffman, and Karen Eriksen",
        "accent": "teal",
        "kind": "kress",
    },
]


GENERIC_NOISE = [
    re.compile(r"^\s*\d+\s*$"),
    re.compile(r"^\s*\d+\s+CHAPTER\s+\d+", re.I),
    re.compile(r"^CHAPTER\s+\d+\s*[•·]", re.I),
    re.compile(r"^Copyright\s*[©]?", re.I),
    re.compile(r"^Reproduced with permission of copyright owner", re.I),
    re.compile(r"^Further reproduction prohibited", re.I),
]


def clean_line(line: str, kind: str) -> str:
    line = normalise(line).replace("/uni00A0", " ").replace("\xa0", " ")
    line = re.sub(r"\s+", " ", line).strip()
    if not line or any(rx.search(line) for rx in GENERIC_NOISE):
        return ""
    if kind == "textbook":
        if line in {"Learning", "Objectives", "Learning Objectives", "Pearson eTextbook"}:
            return ""
        if re.match(r"^(?:2Genetics, Epigenetics,|and the Brain:|The Fundamentals of|Behavioral Development|Cognitive Development|in the Early Years)$", line):
            return ""
        if re.match(r"^\d+\s+(?:Chapter|CHAPTER)\s+\d+", line):
            return ""
        if re.match(r"^.+\s+\d{2,3}$", line) and len(line.split()) <= 12:
            return ""
    elif kind == "caspi":
        if line in {"CASPI AND MOFFITT", "MENTAL DISORDERS IN ONE DIMENSION", "REVIEWS AND OVERVIEWS"}:
            return ""
        if re.match(r"^Am J Psychiatry 175:9, September 2018", line):
            return ""
        if line == "ajp.psychiatryonline.org":
            return ""
        if re.match(r"^Am J Psychiatry 2018; 175:831", line):
            return ""
    elif kind == "mehdi":
        if re.match(r"^PSYCHIATRIC ANNALS\s*[•·]", line, re.I):
            return ""
        if line in {"Peer Review: REVIEW ARTICLE", "Copyright © SLACK Incorporated"}:
            return ""
        if re.match(r"^From the Geriatric Psychiatry Clinical Fellowship Program", line):
            return ""
        if re.match(r"^(Originally submitted|Correspondence:|State Psychiatric Institute|Disclosure:|Sunovion|doi:10\.3928)", line):
            return ""
    elif kind == "kress":
        if re.match(r"^(?:\d+\s+)?Counseling and Values\s*[■•]", line):
            return ""
        if "Downloaded from https://onlinelibrary.wiley.com" in line:
            return ""
        if re.match(r"^© 2010 by the American Counseling Association", line):
            return ""
        if re.match(r"^(Victoria E\. Kress, Department|Rachel M\. Hoffman, Counseling|Karen Eriksen, We|Meridian Services|Rayen Avenue)", line):
            return ""
    return line


def page_texts(reader: PdfReader, kind: str) -> list[str]:
    texts = []
    for page in reader.pages:
        lines = [clean_line(line, kind) for line in (page.extract_text() or "").splitlines()]
        if kind == "caspi":
            try:
                start = lines.index("AJP AT 175")
                end = next(i for i in range(start, len(lines)) if lines[i].startswith("(Am J Psychiatry 1910"))
                lines[start : end + 1] = [""]
            except (ValueError, StopIteration):
                pass
        text = "\n".join(lines)
        text = re.sub(r"(?m)^([A-Z])\n([a-z])", r"\1\2", text)
        if kind == "caspi":
            replacements = {
                "brieflyr e v i e wi t ,a r t i c u l a t e": "briefly review it, articulate",
                "s c h i z o p h r e n i a( p s y c h o t i ce x periences)": "schizophrenia (psychotic experiences)",
                "disorder-speci ficp r o t o c o l s ,t h e nc o b b l e": "disorder-specific protocols, then cobble",
                "p,s u c ha s": "p, such as",
                "d i a g n o s e ss u c ha sF L K": "diagnoses such as FLK",
            }
            for bad, good in replacements.items():
                text = text.replace(bad, good)
        texts.append(text)
    return texts


def paragraphs(raw: str) -> list[str]:
    raw = re.sub(r"(\w+)\s*-\s*\n\s*(\w+)", _rejoin, raw)
    raw = re.sub(r"(?m)^([A-Z])\n([a-z])", r"\1\2", raw)
    paras = to_paragraphs(raw)
    cleaned = []
    for p in paras:
        p = re.sub(r"\s+(?:FIGURE|TABLE)\s+\d+(?:\.\d+)?\b.*$", "", p).strip()
        p = re.sub(r"\s+\(?Sources?:\s.*$", "", p).strip()
        if not p or p.count("#20") >= 3:
            continue
        word_repairs = {
            "Mof fitt": "Moffitt",
            "speci fic": "specific",
            "classi fication": "classification",
            "de ficit": "deficit",
            "dif ficult": "difficult",
            "in fluence": "influence",
            "re flect": "reflect",
            "de finition": "definition",
            "de fined": "defined",
            "con firm": "confirm",
            "pro files": "profiles",
            "re fin": "refin",
            "signi fic": "signific",
            "modi fic": "modific",
            "ef fic": "effic",
            "uni fied": "unified",
            "in flamm": "inflamm",
            "identi fi": "identifi",
            "Identi fi": "Identifi",
            "con flation": "conflation",
            "un filtered": "unfiltered",
            "Wake field": "Wakefield",
            "liabilit y": "liability",
            "the rapeutic": "therapeutic",
            "DSMIV-TR": "DSM-IV-TR",
            "DSMIV": "DSM-IV",
            "DSM5": "DSM-5",
        }
        for bad, good in word_repairs.items():
            p = p.replace(bad, good)
        p = re.sub(r"\bofp\b", "of p", p)
        p = p.replace('the"generalist', 'the "generalist')
        p = re.sub(r"([,;:])(?=[A-Za-z])", r"\1 ", p)
        p = re.sub(r"\)(?=[A-Za-z\"])", ") ", p)
        cleaned.append(re.sub(r"\s+", " ", p).strip())
    return cleaned


def chapter(n: int, title: str, paras: list[str]) -> dict:
    words = sum(len(p.split()) for p in paras)
    return {
        "n": n,
        "title": title,
        "paragraphs": paras,
        "words": words,
        "fullWords": words,
        "excerpt": False,
    }


def bib_chapter(base_n: int, paras: list[str]) -> dict:
    words = sum(len(p.split()) for p in paras)
    return {
        "n": 100 + base_n,
        "label": f"{base_n}-A",
        "bib": True,
        "title": f"Chapter {base_n}-A: Bibliography",
        "paragraphs": paras,
        "words": words,
        "fullWords": words,
        "excerpt": False,
    }


def find_marker(lines: list[str], marker: str, start: int = 0) -> int:
    for i in range(start, len(lines)):
        if lines[i].strip() == marker:
            return i
    raise ValueError(f"marker not found: {marker!r}")


def article_chapters(texts: list[str], kind: str) -> list[dict]:
    lines = []
    for page in texts:
        lines.extend(page.splitlines())
        lines.append("")

    if kind == "caspi":
        sections = [
            ("Overview", None),
            ("How Did We Get Here? A Brief History of Research on the Structure of Psychopathology", "HOW DID WE GET HERE? A BRIEF HISTORY OF"),
            ("The Quixotic Pursuit of Specificity and the Promise of Nonspecific Shared Pathogenesis", "THE QUIXOTIC PURSUIT OF SPECIFICITY AND THE"),
            ("The Genetics of p", "THE GENETICS OF p"),
            ("The Neuroscience of p", "THE NEUROSCIENCE OF p"),
            ("Psychological Trauma and p", "PSYCHOLOGICAL TRAUMA AND p"),
            ("Prevention of Mental Disorders", "PREVENTION OF MENTAL DISORDERS"),
            ("Conclusions", "CONCLUSIONS"),
        ]
        content_end = find_marker(lines, "AUTHOR AND ARTICLE INFORMATION")
        refs_start = find_marker(lines, "REFERENCES", content_end)
    elif kind == "mehdi":
        sections = [
            ("Overview", None),
            ("Historical Background", "HISTORICAL BACKGROUND"),
            ("The Problems of False Positive or Over-Diagnosis", "THE PROBLEMS OF FALSE POSITIVE"),
            ("Analyzing the False Positive Issue", "ANALYZING THE FALSE POSITIVE"),
            ("DSM-5 and Research", "DSM-5 AND RESEARCH"),
            ("The National Institute of Mental Health Research-Oriented Domain Initiative", "THE NATIONAL INSTITUTE OF"),
            ("Diagnostic Labels vs. Alternate Systems of Identification", "DIAGNOSTIC LABELS VS ALTERNATE"),
            ("Evaluating Criticism About Openness of the Process", "EVALUATING CRITICISM ABOUT"),
            ("Pros and Cons of the Criticism", "PROS AND CONS OF THE CRITICISM"),
            ("Conclusion", "CONCLUSION"),
        ]
        refs_start = find_marker(lines, "REFERENCES")
        content_end = refs_start
    elif kind == "kress":
        sections = [
            ("Overview", None),
            ("Informed Consent and Confidentiality", "Informed Consent and Confidentiality"),
            ("Accuracy Versus Misrepresentation", "Accuracy Versus Misrepresentation"),
            ("Multiple Relationships: The Therapeutic-Fiduciary Relationship Tension", "Multiple Relationships: The Therapeutic–Fiduciary"),
            ("Traditional Strategies for Facilitating Ethical Diagnostic Practices", "Traditional Strategies for Facilitating"),
            ("Emerging Strategies for Ethical Diagnostic Practice", "Emerging Strategies for Enhancing"),
        ]
        refs_start = find_marker(lines, "References")
        content_end = refs_start
    else:
        raise ValueError(kind)

    marks = [(title, 0 if marker is None else find_marker(lines, marker), marker is not None) for title, marker in sections]
    result = []
    for i, (title, start, has_marker) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else content_end
        paras = paragraphs("\n".join(lines[start + int(has_marker):end]))
        if not paras:
            raise ValueError(f"empty section: {title}")
        result.append(chapter(i + 1, title, paras))

    refs = paragraphs("\n".join(lines[refs_start + 1 :]))
    if not refs:
        raise ValueError("empty bibliography")
    result.append(bib_chapter(len(result), refs))
    return result


def create_cover(pdf: Path, out: Path) -> None:
    doc = fitz.open(pdf)
    page = doc[0]
    scale = 480 / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    pix.save(out)


def build(spec: dict) -> None:
    reader = PdfReader(spec["pdf"])
    texts = page_texts(reader, spec["kind"])
    if spec["kind"] == "textbook":
        ranges = [
            (2, "Genetics, Epigenetics, and the Brain: The Fundamentals of Behavioral Development", 0, 45),
            (3, "Cognitive Development in the Early Years", 45, len(texts)),
        ]
        chapters = []
        for n, title, start, end in ranges:
            paras = paragraphs("\n\n".join(texts[start:end]))
            if not paras:
                raise ValueError(f"empty chapter {n}")
            chapters.append(chapter(n, title, paras))
    else:
        chapters = article_chapters(texts, spec["kind"])

    out = ROOT / "app" / "books" / spec["slug"]
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "slug": spec["slug"],
        "title": spec["title"],
        "subtitle": spec["subtitle"],
        "author": spec["author"],
        "accent": spec["accent"],
        "chapters": chapters,
    }
    (out / "book.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    create_cover(spec["pdf"], out / "cover.png")
    print(spec["slug"], len(chapters), sum(c["words"] for c in chapters), sum(len(c["paragraphs"]) for c in chapters))


if __name__ == "__main__":
    for item in SPECS:
        build(item)
