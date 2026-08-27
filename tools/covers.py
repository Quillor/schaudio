#!/usr/bin/env python3
"""Render page 1 of each book's PDF as its cover image."""
import json
from pathlib import Path
import fitz

ROOT = Path(__file__).resolve().parent.parent
PDFS = {
    "lifespan": "/Users/timrosenberg/Downloads/TheLifeSpanHumanDevelopmentforHelpingProfessionals.pdf",
    "counseling": "/Users/timrosenberg/Downloads/Theory and Practice of Counseling and Psychotherapy.pdf",
    "research-methods": "/Users/timrosenberg/Downloads/ResearchMethodsClinPsych.pdf",
    "wampold-common-factors": "/Users/timrosenberg/Downloads/Wampold_2015.pdf",
}
for slug, pdf in PDFS.items():
    doc = fitz.open(pdf)
    page = doc[0]
    zoom = 480 / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    out = ROOT / "app" / "books" / slug / "cover.png"
    pix.save(out)
    print(slug, pix.width, "x", pix.height, "->", out.name)
