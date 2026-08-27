#!/usr/bin/env python3
"""Sync app/books/ to the Cloudflare R2 bucket. Incremental: uploads only
files whose size differs from the object already in the bucket (audio files
are write-once, so size is a sufficient change test; manifests/book.json are
small enough that a rare same-size edit can be forced with --force).

Credentials come from ~/.config/schaudio/r2.env:
    R2_ACCOUNT_ID=...
    R2_ACCESS_KEY_ID=...
    R2_SECRET_ACCESS_KEY=...
    R2_BUCKET=schaudio-media

Usage:  publish_r2.py [--force] [prefix]     e.g.  publish_r2.py books/lifespan
"""
import os, sys
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
ENV = Path.home() / ".config/schaudio/r2.env"
TYPES = {".mp3": "audio/mpeg", ".json": "application/json", ".png": "image/png"}

cfg = {}
for line in ENV.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip()

s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{cfg['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
    aws_access_key_id=cfg["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=cfg["R2_SECRET_ACCESS_KEY"],
    region_name="auto",
)
bucket = cfg.get("R2_BUCKET", "schaudio-media")
force = "--force" in sys.argv
prefix = next((a for a in sys.argv[1:] if not a.startswith("-")), "books")

remote = {}
paginator = s3.get_paginator("list_objects_v2")
for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
    for o in page.get("Contents", []):
        remote[o["Key"]] = o["Size"]

up = skip = 0
for f in sorted((ROOT / "app").glob(f"{prefix}/**/*")):
    if not f.is_file() or f.suffix not in TYPES:
        continue
    key = str(f.relative_to(ROOT / "app"))
    if not force and remote.get(key) == f.stat().st_size:
        skip += 1
        continue
    s3.upload_file(str(f), bucket, key, ExtraArgs={
        "ContentType": TYPES[f.suffix],
        "CacheControl": "public, max-age=31536000, immutable" if f.suffix == ".mp3"
                        else "public, max-age=60",
    })
    up += 1
    if up % 200 == 0:
        print(f"  ...{up} uploaded")
print(f"uploaded {up}, unchanged {skip}  (bucket: {bucket}, prefix: {prefix})")
