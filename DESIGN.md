# Design Plan — Flavor DS × Schaudio

## Subject
- **Subject:** Schaudio, an audiobook app where listening and reading are one activity — audio and text stay locked together so you can move between ear and eye without losing your place.
- **Audience:** People who study what they read. Students, nonfiction readers, anyone who annotates in the margin.
- **The app's single job:** Get you back into the book in one tap, and make the words capturable while they are being spoken.
- **Subject-world materials:** the sewn bookmark ribbon in a hardcover; the cracked-open gutter and spine; margins and marginalia in pencil; a librarian's colored index tabs; the tape counter on a cassette deck; dog-ears; offset paper stock under daylight; the dark wood of a shelf.

## Direction
Two directions were held:

- **A — Shelf and page.** A dark shell (the shelf) holding a light paper pane (the page). Ink-black text, one ribbon-red accent, colored index tabs for categories. Emotion: focused study. Risk: a light reading surface can drift into the warm-cream editorial cliché.
- **B — Night listening.** Deep ink-blue throughout, amber lamp-light accent, built for headphones in the dark. Emotion: intimacy. Risk: dark-by-default is a default, not a choice, unless the subject demands it.

**Choosing A over B because Schaudio's whole differentiator is that the text is a first-class citizen — a reading surface has to hold up in daylight and at a long measure — accepting that the headphones-in-the-dark moment is served by a real Night mode rather than by the primary identity.**

The cream cliché is dodged deliberately: the paper is a cool-neutral offset stock, not aged cream; the accent is ribbon red (blue-leaning, saturated), not terracotta; and the display face is not a characterful serif.

## Tokens

### Color
| Token | Hex | Role |
|-------|-----|------|
| `shell` | `#15181D` | app shell — the shelf |
| `shell-raised` | `#1E222A` | rails, transport bar, sheets |
| `paper` | `#F4F3EF` | the reading pane — the page |
| `ink` | `#161514` | primary text on paper |
| `ink-muted` | `#767268` | secondary text, timecode |
| `ribbon` | `#C8102E` | the sewn bookmark ribbon — accent |

Rationale: the palette is the physical object. A dark shelf holds a light page, and the one saturated colour in a hardcover is the ribbon sewn into its spine — so ribbon red carries the only accent job in the app: where the audio is now, and where you marked it.

### Index tabs (content-semantic, not chrome)
A separate scale, because these colour *user content*, not UI. Four default tabs from a librarian's index cards, extensible by the user:
`ribbon #C8102E` · `amber #D99A22` · `moss #5F8A4C` · `sky #3D7FB8`

### Type
| Role | Face | Why this face for this subject |
|------|------|-------------------------------|
| UI / display | Instrument Sans | Chrome needs to recede behind the page. Has enough width contrast to set headings without borrowing the page's voice. |
| Book text | Source Serif 4 | Drawn specifically for long-form reading on screen. The app renders actual book pages; this is the functional choice, not a decorative one. |
| Transport | DM Mono | Timecode and the tape counter need tabular figures that do not shift width as they tick. |

Scale: 11 / 12 / 13 / 15 / 17 / 21 / 27 / 34. Book text sets at 19–20px on a 62–66 character measure.

### Spacing & shape
- Rhythm: 4px base. Sections breathe on 8 / 12 / 20 / 32.
- Radius: 3px on chrome (the crisp edge of trimmed paper), 0 on the page itself, full round only on the transport controls.
- Elevation: no drop shadows on the page. The shell/paper value split does the elevation work. One inset seam where the page meets the shell — the gutter.

## Layout
**Concept:** the app *is* an open book — a shelf rail on the left, the page in the centre, the margin on the right, and the transport running the full width beneath, like the deck the book is playing on.

```
┌──────────────────────────────────────────────────────────────┐
│  SHELF RAIL     │        PAGE            │     MARGIN        │
│                 │ ┃                      │                   │
│  library        │ ┃  chapter title       │   note tab ───────│
│  ├ covers +     │ ┃                      │   note tab        │
│  │  progress    │ ┃  body text with the  │                   │
│  │              │ ┃  spoken word lit     │   bookmark tab    │
│  categories     │ ┃  in ribbon red       │                   │
│  ├ index tabs   │ ┃                      │   note tab        │
│  bookmarks      │ ┃  ← the ribbon runs   │                   │
│                 │ ┃    down the gutter   │                   │
├──────────────────────────────────────────────────────────────┤
│  ◀15  ▶/❚❚  15▶   ━━━━━━━━●────────  1.0×  00:12:41 / 41:08  │
└──────────────────────────────────────────────────────────────┘
```

## Signature
**The ribbon.** A vertical ribbon runs down the page gutter and marks exactly where the audio is. The currently spoken word fills with ribbon red as it is said, so the text visibly *plays*. Bookmarks are tabs pinned onto that ribbon, and notes hang off it into the margin. Every other surface stays quiet so this one thing reads.

## Motion
One orchestrated moment: the word fill advancing, and the page keeping the spoken line at a fixed reading height so the text moves under a stationary eye. The ribbon tab settles when you drop a bookmark. Nothing fades up on scroll; nothing lifts on hover except the transport controls.

## Copy voice
- Register: plain and bookish. It talks about books, not about software.
- CTAs by exact label: `Resume` · `Play` · `Add note` · `Save highlight` · `Bookmark` · `New category` · `Jump to`
- Banned for this brief: seamless, unlock, empower, immersive, experience (as a noun), "Get started".
