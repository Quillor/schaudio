# Schaudio for iOS

A native SwiftUI port of the web reader. Same books, same narration, same
word-level sync — but with real background audio, so a chapter keeps playing
with the screen off and the lock screen shows proper controls.

- **Deployment target:** iOS 17.0 (needed for `@Observable` and the two-parameter
  `onChange`). Covers iPhone XS and later.
- **Language:** Swift 6, strict concurrency.
- **UI:** SwiftUI, no third-party dependencies.

## Build and run

The Xcode project is generated, not committed, so the file list never drifts:

```bash
brew install xcodegen          # once
cd ios && xcodegen generate
open Schaudio.xcodeproj
```

Pick a simulator or your iPhone and press Run. For a device build you'll need to
set a signing team once — select the **Schaudio** target → *Signing & Capabilities*
→ pick your Apple ID. A free Apple ID works; the app then expires after 7 days
and needs a re-run.

Command-line equivalents:

```bash
# simulator
xcodebuild -project Schaudio.xcodeproj -scheme Schaudio \
  -sdk iphonesimulator -configuration Debug build CODE_SIGNING_ALLOWED=NO

# device (needs your signing team)
xcodebuild -project Schaudio.xcodeproj -scheme Schaudio \
  -sdk iphoneos -configuration Release build
```

## Where the content comes from

Nothing is bundled. The app reads the same JSON and MP3s the website serves, from
Cloudflare R2 (`https://pub-83aebd7fcc2b48538b1f792814c1fc14.r2.dev/books/…`),
and caches every file it fetches under Caches. That base must match
`window.SCHAUDIO.mediaBase` in `app/index.html` — the corpus moved off Vercel
when deploys went code-only, and the old `/app/books` path now 404s. Re-running `tools/ingest.py` / `tools/narrate.py` and
redeploying updates the phone too, with no App Store round trip. A chapter you
have already opened keeps working offline.

## How it's put together

| File | Responsibility |
|---|---|
| `Models.swift` | Wire format shared with the web app, plus `TokenBuilder`, which aligns the book's own words to the synthesizer's measured timings |
| `Library.swift` | Fetches books and manifests; network first, disk cache as the offline fallback |
| `Player.swift` | `AVQueuePlayer` per chapter (one item per paragraph), 20 Hz word tracking, `AVAudioSession` + `MPNowPlayingInfoCenter` + `MPRemoteCommandCenter` |
| `Store.swift` | Progress, highlights, notes, bookmarks, categories, appearance — one JSON document, written atomically off the main thread |
| `LibraryView` / `ReaderView` | Cover grid; reader with per-word rendering, tap-to-seek, long-press-to-highlight, auto-follow scrolling |
| `PlayerBar.swift` | Scrubber, speed, ±15s, bookmark, and the four sheets |
| `Sheets.swift` | Chapters, Voice, Text settings, Notes & bookmarks, Highlight editor |

### Background audio

Three things have to line up, and all three are in place:

1. `UIBackgroundModes: [audio]` in Info.plist (set from `project.yml`).
2. `AVAudioSession` category `.playback`, mode `.spokenAudio`, policy `.longFormAudio`
   — this is also what makes playback ignore the silent switch.
3. `MPNowPlayingInfoCenter` metadata (chapter, author, book, cover art) and
   `MPRemoteCommandCenter` handlers for play/pause, ±15s and scrubbing.

Because a chapter is a queue of paragraph items, iOS advances paragraphs itself
while suspended — no wake-ups needed.

## Debug affordances

Two `#if DEBUG`-only environment variables make automated runs possible; neither
exists in a release build:

```bash
SIMCTL_CHILD_SCHAUDIO_OPEN_BOOK=lifespan \
SIMCTL_CHILD_SCHAUDIO_AUTOPLAY=1 \
SIMCTL_CHILD_SCHAUDIO_OPEN_SHEET=chapters \
xcrun simctl launch <device-udid> com.quillor.schaudio
```

`SCHAUDIO_OPEN_SHEET` takes `chapters`, `voice`, `text` or `notes`.

## Sign-in and sync

Tap the account button in the library. Sign-in runs through
`ASWebAuthenticationSession` — the system's OAuth surface, which runs in Safari's
process, so Google accepts it (embedded web views are refused), existing Google
sessions are reused, and the app never sees a password. The flow talks to Google
directly rather than bouncing through Supabase, which is why the consent screen
names **Schaudio**. PKCE is used because iOS OAuth clients are public and have
no secret.

The returned ID token is exchanged for a Supabase session, and the refresh token
is kept in the keychain (not UserDefaults) so sign-in survives relaunches.

`SyncPayload.swift` is the contract with the web app: it encodes the *web's*
field names, so a phone and a browser read and write the same
`user_state` row. Highlight and bookmark ids round-trip as opaque strings —
the web mints ids like `h1756…`, and coercing those into UUIDs would duplicate
every highlight on each sync. Conflicts resolve by `updatedAt`: newest wins,
whole-document. Pushes are debounced two seconds so scrubbing or typing a note
is one request, not fifty.

**If you change the payload shape, change `app/app.js` in the same commit** —
these two files are one protocol.

## Offline

Account → Offline downloads a whole book, in whichever voice is selected, to
`Documents/offline/<slug>/…`, mirroring the manifest's own paths. The player
prefers a local file when one exists, so a downloaded book never touches the
network — verified by checking the `AVPlayerItem` URL scheme is `file`. Files
are flagged `isExcludedFromBackup`, because re-downloadable audio must not eat
the user's iCloud quota (Apple rejects apps that get this wrong).

## TestFlight

Not possible from this checkout yet. A TestFlight build needs four things that
aren't here: a paid Apple Developer Program membership, an Apple Distribution
certificate (the only signing identity on this machine is a *Developer ID*
one, which signs Mac apps outside the App Store), an App Store Connect record
for `com.quillor.schaudio`, and a `DEVELOPMENT_TEAM` in `project.yml` (still
`""`). Once those exist:

```bash
cd ios && xcodegen generate
xcodebuild -project Schaudio.xcodeproj -scheme Schaudio \
  -sdk iphoneos -configuration Release -archivePath build/Schaudio.xcarchive archive
xcodebuild -exportArchive -archivePath build/Schaudio.xcarchive \
  -exportOptionsPlist ExportOptions.plist -exportPath build/export
xcrun altool --upload-app -f build/export/Schaudio.ipa -t ios \
  --apiKey <key-id> --apiIssuer <issuer-id>
```

Sign in with Apple is also required before App Store review will pass, since
the app offers Google sign-in (see *Not done yet*). TestFlight itself only
needs the beta review, which is lighter, but the same rule is applied to
external testing groups.

## Not done yet

- **Per-chapter downloads.** It's whole-book or nothing; the plumbing is
  per-paragraph, so per-chapter is a small addition.
- **Sync merge.** Conflict resolution is last-writer-wins on the whole
  document. Editing on two devices while both are offline loses the older set of
  edits. A per-field merge would be the fix if that ever bites.
- **Sign in with Apple.** Apple requires it alongside third-party sign-in for
  App Store distribution. Not needed for personal/TestFlight use.
