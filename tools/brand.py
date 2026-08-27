#!/usr/bin/env python3
"""Generate every icon size from branding/icon.png (square, ideally 1024px+):
web favicons + apple-touch-icon into app/, and the iOS AppIcon set."""
import json, sys
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
src = ROOT / "branding/icon.png"
if not src.exists():
    sys.exit("branding/icon.png not found - save the icon there first")
img = Image.open(src).convert("RGBA")

# Web: favicons + touch icon. Trim the image's own outer transparent margin
# if any, then export straight; the artwork already carries its shape.
web = {"icon-32.png": 32, "icon-192.png": 192, "icon-512.png": 512,
       "icon-1024.png": 1024, "apple-touch-icon.png": 180}
for name, px in web.items():
    img.resize((px, px), Image.LANCZOS).save(ROOT / "app/brand" / name)
    print(f"app/brand/{name}  {px}px")

# iOS single-size AppIcon (Xcode 14+): one 1024 with no alpha (App Store rule).
appicon = ROOT / "ios/Schaudio/Resources/Assets.xcassets/AppIcon.appiconset"
appicon.mkdir(parents=True, exist_ok=True)
flat = Image.new("RGB", img.size, (255, 255, 255))
flat.paste(img, mask=img.split()[3])
flat.resize((1024, 1024), Image.LANCZOS).save(appicon / "icon-1024.png")
(appicon / "Contents.json").write_text(json.dumps({
    "images": [{"filename": "icon-1024.png", "idiom": "universal",
                "platform": "ios", "size": "1024x1024"}],
    "info": {"author": "xcode", "version": 1}}, indent=2))
print("ios AppIcon: icon-1024.png (alpha flattened)")
