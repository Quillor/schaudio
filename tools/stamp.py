#!/usr/bin/env python3
"""Stamp app.css/app.js URLs with a content hash.

Without this, a browser keeps serving the cached script after a deploy, so a
shipped fix silently doesn't reach anyone (including, embarrassingly, testing).
"""
import hashlib, pathlib, re

root = pathlib.Path(__file__).resolve().parent.parent / "app"
html_path = root / "index.html"
html = html_path.read_text()

for name in ("app.css", "app.js"):
    digest = hashlib.sha1((root / name).read_bytes()).hexdigest()[:10]
    html = re.sub(rf'{re.escape(name)}(\?v=[0-9a-f]+)?', f"{name}?v={digest}", html)

html_path.write_text(html)
print("\n".join(l.strip() for l in html.splitlines() if "?v=" in l))
