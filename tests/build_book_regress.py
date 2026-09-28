#!/usr/bin/env python3
"""Regression check for tools/build_book.py against books that were curated by hand.

For each source PDF that is present on this machine, build it into a temp dir and compare
with the curated app/books/<slug>/book.json: every gate must PASS and the builder must keep
at least MIN_RECALL of the curated narratable words. Run after any change to build_book.py:

  .venv-tts/bin/python tests/build_book_regress.py
"""
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DL = Path.home() / "Downloads"
W4 = DL / "Week 4 Readings"
CASES = {
    "wampold-common-factors": DL / "Wampold_2015.pdf",
    "counseling-values-ethical-dimensions": DL / "712 Kress_Counseling and Values Ethical Dimensions.pdf",
    "710-exam-1-study-guide": DL / "710 Exam 1 Study Guide.pdf",
    "carroll-ch4": W4 / "701_Carroll Ch4-req.pdf",          # scanned: Vision OCR + spread bleed
    "carroll-ch2": W4 / "701_Carroll Ch2-req.pdf",          # scanned
    "corrigan-ch1": W4 / "701_Corrigan Ch1-req.pdf",        # scanned
    "mcgiffin-2019": W4 / "712_McGiffin et al_2019.pdf",
    "molock-2023": W4 / "712_Molock et al 2023.pdf",
    "parent-2019": W4 / "712_Parent et al 2019 .pdf",
}
MIN_RECALL = 0.96


def words(book):
    return Counter(re.findall(r"[a-z0-9]+", " ".join(
        p for c in book["chapters"] if not c.get("bib") for p in c["paragraphs"]).lower()))


def main():
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        for slug, pdf in CASES.items():
            curated = ROOT / "app" / "books" / slug / "book.json"
            if not pdf.exists() or not curated.exists():
                print(f"SKIP {slug}: source or curated copy not on this machine")
                continue
            r = subprocess.run([sys.executable, str(ROOT / "tools/build_book.py"), "build", str(pdf), slug, "--title", "x"],
                               capture_output=True, text=True, env={"SCHAUDIO_BOOKS": tmp, "PATH": "/usr/bin:/bin"})
            rep = json.loads(Path(tmp, slug, "ingest-report.json").read_text())
            old, new = words(json.loads(curated.read_text())), words(json.loads(Path(tmp, slug, "book.json").read_text()))
            recall = sum((old & new).values()) / max(sum(old.values()), 1)
            ok = rep["result"] == "PASS" and recall >= MIN_RECALL
            failures += not ok
            print(f"{'OK  ' if ok else 'FAIL'} {slug:38} gates={rep['result']} recall={recall:.3f} "
                  f"chapters={rep['gates'].get('chapters')} method={rep['method']}")
            for p in rep["problems"]:
                print("      ", p[:160])
    print("PASS" if not failures else f"{failures} case(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
