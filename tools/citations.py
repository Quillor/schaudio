"""Conservative author/year citation omission, with source-token alignment.

Only narration is changed. Book paragraphs remain verbatim. ``narrationTokens``
stores each original whitespace token with its citation characters removed, so
the reader never accidentally aligns a silent author name to a later TTS word.
"""

import re

YEAR = r"(?:1[5-9]\d{2}|20\d{2})[a-z]?"
PAREN = re.compile(r"\([^()]*\)")
AUTHOR = r"(?:[A-Z]\.\s*)*(?:(?:van|von|de|di|del|ur)\s+)?[A-ZÀ-ÖØ-Þ][\w’'\-]+(?:\s+(?:(?:for|of|and|the)\s+)?[A-ZÀ-ÖØ-Þ][\w’'\-]+)*(?:\s+\[[A-Z]+\])?"
AUTHORS = rf"{AUTHOR}(?:(?:\s*(?:&|and)\s*|,\s*(?:(?:&|and|with)\s*)?){AUTHOR})*(?:,?\s+et\s+al\.?)?"
CITATION = re.compile(
    rf"^(?:(?:see(?: also)?|e\.g\.|cf\.|cited in|for a different view, see)[,\s]+)?{AUTHORS},?\s+"
    rf"{YEAR}(?:\s*,\s*{YEAR})*(?:,\s*p{{1,2}}\.\s*[\d–—\-]+)?$"
)
NARRATIVE = re.compile(rf"(?:{AUTHORS})(?:['’]s)?\s*$")
YEAR_ONLY = re.compile(rf"^{YEAR}(?:\s*,\s*{YEAR})*(?:,\s*p{{1,2}}\.\s*[\d–—\-]+)?$")


def citation_spans(text):
    """Return half-open character spans; keep ambiguous prose parentheticals."""
    spans = []
    for match in PAREN.finditer(text):
        body = match.group()[1:-1]
        groups = [part.strip() for part in body.split(";")]
        follows_author = NARRATIVE.search(text[:match.start()])
        parenthetical = all(CITATION.fullmatch(part) or (index == 0 and follows_author and YEAR_ONLY.fullmatch(part))
                            for index, part in enumerate(groups))
        # Narrative authors remain spoken: "Smith (2019) found" -> "Smith found".
        narrative = YEAR_ONLY.fullmatch(body.strip()) and NARRATIVE.search(text[:match.start()])
        if parenthetical or narrative:
            spans.append((match.start(), match.end()))
        else:
            # Keep meaningful scale names, statistics, and explanatory prose,
            # but omit reference-only semicolon groups inside the same brackets.
            parts = list(re.finditer(r"[^;]+", body))
            for index, part in enumerate(parts):
                if CITATION.fullmatch(part.group().strip()):
                    start, end = part.span()
                    if index:
                        start -= 1  # preceding semicolon
                    elif end < len(body):
                        end += 1  # following semicolon
                    spans.append((match.start() + 1 + start, match.start() + 1 + end))
            # Citation embedded in otherwise useful prose: retain the prose.
            for embedded in re.finditer(rf"(?:see\s+)?{AUTHORS},\s*{YEAR},\s*(?=(?:for|study)\b)", body):
                spans.append((match.start() + 1 + embedded.start(), match.start() + 1 + embedded.end()))
    return spans


def prepare_narration(text, omit_citations=False):
    if not omit_citations:
        return text, {}
    spans = citation_spans(text)
    chars = list(text)
    for start, end in spans:
        chars[start:end] = [" "] * (end - start)
    cleaned = "".join(chars)
    tokens = [cleaned[m.start():m.end()].strip() for m in re.finditer(r"\S+", text)]
    spoken = re.sub(r"\s+([,;:!?]|\.(?!\d))", r"\1", " ".join(cleaned.split()))
    if not any(ch.isalnum() for ch in spoken):
        raise ValueError("paragraph contains only a citation; move it to text-only bibliography before narration")
    return spoken, {"narrationTokens": tokens, "omittedCitationSpans": spans}


def book_omits_citations(book_dir):
    import json
    return json.loads((book_dir / "book.json").read_text()).get("narration", {}).get("omitInTextCitations") is True
