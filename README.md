# Book FM (Schaudio)

An audiobook app template built on **Flavor DS** (https://flavor-ds.vercel.app), with true
audio↔text sync: every word's timing is measured at narration time, so the spoken word is lit
in the text as it plays, and clicking any word seeks the audio to that word.

## Features

- **Home / reader navigation** — a home screen (Continue-listening card + cover grid using each
  PDF's real first page) and a reader that shows only the current book, with a back button
- **Listen** — per-paragraph MP3 narration, big round play, ±15s skip, speed (0.8–2×), scrubber
- **Audio → text** — the current word highlights as it is spoken; the page auto-scrolls to keep
  the spoken line at reading height (pauses politely while you browse)
- **Text → audio** — click any word to jump the narration there
- **Highlight + notes** — select a passage → choose a category → optional note
- **Custom categories** — create, rename, recolor; six contrast-approved semantic color pairs,
  each highlight tinted with a solid underline edge so near hues stay distinct
- **Bookmarks** — press `B` or the bookmark button; pinned as ticks on the scrubber
- **Progress** — per-book position persisted (localStorage); progress bars on covers; resume
- **Text settings** — size (7 steps up to 30px), fonts tuned for reading (Source Serif 4,
  Libre Franklin, Atkinson Hyperlegible), Regular/Relaxed/Loose line spacing
- **Voices** — two narrators: **Sam** (en-US-AndrewMultilingualNeural, the house voice) and
  **Morgan** (en-US-BrianMultilingualNeural at −8% rate — deep, slow, relaxing; both are the
  community-rated most natural edge-tts voices). Each voice has its own audio set and timing
  manifest, and switching carries your position over
- **Chapters** — table of contents extracted from each PDF's real outline; the narrated
  chapter is playable with live progress, the rest are listed as not downloaded
- **Mobile parity** — under 760px the notes/bookmarks/categories panel becomes a bottom sheet
  and the transport is thumb-sized; safe-area insets respected
- **Google sign-in (prod only)** — disabled in dev (`localhost` shows a DEV badge). On the
  deployed site, set `window.SCHAUDIO.googleClientId` in `app/index.html` (a Google OAuth
  Web client ID with your Vercel domain as an authorized JS origin); `vercel.json` rewrites
  `/` to the app.

Keyboard: `Space` play/pause · `←/→` ±15s · `B` bookmark · `Esc` close popover/panel.
Brand typography is Flavor's **Editorial** pair (`data-font="editorial"`: Fraunces display,
Libre Franklin text). Light/dark via the toggle — one `data-mode` attribute re-resolves all.

## Layout

```
schaudio/
├── vendor/flavor/          Flavor DS as fetched from its MCP
│   ├── flavor.css          token layer — FIRST stylesheet, all 96 theme combinations
│   └── components.css      fds-* component classes
├── vendor/fontawesome/     Font Awesome 7 Pro subset (regular/solid/light) from the local kit
├── app/
│   ├── index.html          shell: rail · page · margin · transport (theme attrs on <html>)
│   ├── app.css             app layer — semantic tokens ONLY (raw hex = defect)
│   ├── app.js              sync engine + highlights/notes/categories/bookmarks/progress
│   └── books/<slug>/       book.json (text) · manifest.json (word timings) · audio/*.mp3
├── tools/
│   ├── ingest.py           PDF → cleaned chapter excerpt → book.json
│   └── narrate.py          book.json → edge-tts narration + WordBoundary timing manifest
└── DESIGN.md               the design plan this was built to
```

## Run

```bash
python3 -m http.server 8741
# open http://localhost:8741/app/
```

## Add a book

1. Add an entry to `EXCERPTS` in `tools/ingest.py` (PDF path, page range, metadata) and add its
   slug to `SLUGS` in `app/app.js`.
2. `python3 -m venv .venv-tts && .venv-tts/bin/pip install edge-tts pypdf`
3. `.venv-tts/bin/python tools/ingest.py && .venv-tts/bin/python tools/narrate.py`

Narration uses `edge-tts` WordBoundary events (the approach from the pierce-design-system
video-studio pipeline) — timings are measured from the synthesizer, not estimated.
Delete a book's `manifest.json` to re-narrate it (e.g. after changing `VOICES`/`RATE`).

Extra voices: `.venv-tts/bin/python tools/narrate.py morgan` generates the Morgan set
(`manifest-morgan.json` + `audio/morgan/`). Add profiles in `PROFILES` in
[tools/narrate.py](tools/narrate.py) and to `VOICE_OPTIONS` in [app/app.js](app/app.js).
`tools/toc.py` refreshes each book's chapter list from the PDF outline.

## Flavor DS conformance

- flavor.css loads first; theme = nine attributes on `<html>` (`data-font="reading"` gives the
  Source Serif 4 / Source Sans 3 reading pair)
- App layer references only semantic tokens (`--surface-*`, `--text-*`, `--accent-*`,
  `--space-*`, `--radius-*`, `--duration-*`); guard: `grep -nE "#[0-9a-f]{3,8}" app/app.css`
- Highlight/category colors use only the six approved tint+ink pairs
  (`accent|secondary|success|warning|info|danger`)
- Logical properties throughout, so `dir="rtl"` flips the layout
- Icons are Font Awesome 7 Pro (local kit, vendored subset); regular = default state,
  solid = active

## What is not in this repository

`app/books/` is generated, not source, and is gitignored: the extracted chapter
text (`book.json`), the narration (`audio/`), the word-timing manifests
(`manifests/`) and the covers. It runs to hundreds of megabytes and is
copyrighted book content, so it stays out of version control.

To rebuild it from your own PDFs:

```bash
python3 -m venv .venv-tts
.venv-tts/bin/pip install edge-tts pypdf pymupdf pillow

# point tools/ingest.py's BOOKS list at your PDF paths, then:
.venv-tts/bin/python tools/ingest.py          # PDF -> chapter text
.venv-tts/bin/python tools/covers.py          # page 1 -> cover.png
.venv-tts/bin/python tools/narrate.py sam     # text -> audio + word timings
```

`tools/overnight.py` runs the whole pipeline unattended, deploying after each
chapter. `tools/claim.py` lets several workers narrate in parallel safely —
claims are atomic, so two processes never touch the same chapter, and all
workers append to one shared log at `run/schaudio-run.log`.

The Xcode project is also generated (`cd ios && xcodegen generate`), so only
`project.yml` is tracked.

## Keys in this repository

`app/index.html` contains a Supabase project URL, a Supabase **anon** key and
Google **client IDs**. All three are public by design — they are visible to any
browser that loads the app. Security comes from Supabase row-level security,
which restricts every row to its owning user. No secret is stored here: the
Google client secret lives only in Supabase's provider settings.
