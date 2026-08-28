/* Book FM (formerly Schaudio) — audiobook reader on Flavor DS.
   Audio<->text sync is driven by measured word timings in each book's
   manifest.json (edge-tts WordBoundary events), not estimates. */

"use strict";

const SLUGS = ["lifespan", "counseling", "research-methods", "wampold-common-factors"];
const SPRITE = "../vendor/flavor/icons/sprite.svg";
const STORE_KEY = "schaudio:v2";
const CAT_COLORS = ["accent", "success", "warning", "danger", "secondary", "info"];
const SKIP_MS = 15000;
const SPEEDS = [0.8, 1, 1.25, 1.5, 2];
const MAX_TEXT_SIZE = 6;
const IS_DEV = ["localhost", "127.0.0.1", ""].includes(location.hostname);

/* ---------------- state ---------------- */

const store = loadStore();
const books = new Map(); // slug -> {book, manifest}
let current = null;
let paraIdx = 0;
let playing = false;
let rafId = 0;
let pendingSel = null;
let popCat = null;
let editingCatId = null;   // null = creating
let dialogColor = CAT_COLORS[0];
let activeCatFilter = null;
let activeTab = "notes";
let userScrolledAt = 0;
let lastWordKey = "";

// Media (book text, manifests, audio, covers) can live on a separate host
// (Cloudflare R2) so code deploys stay small. Empty base = same-origin (dev).
const MEDIA_BASE = (window.SCHAUDIO && window.SCHAUDIO.mediaBase || "").replace(/\/$/, "");
const mediaUrl = (path) => MEDIA_BASE ? `${MEDIA_BASE}/${path}` : path;

const $ = (id) => document.getElementById(id);
const audio = $("audio");

function loadStore() {
  let s = {};
  try { s = JSON.parse(localStorage.getItem(STORE_KEY)) || {}; } catch { /* fresh */ }
  try { // migrate v1 annotations if present
    if (!localStorage.getItem(STORE_KEY) && localStorage.getItem("schaudio:v1")) {
      s = JSON.parse(localStorage.getItem("schaudio:v1")) || {};
    }
  } catch { /* ignore */ }
  s.books ||= {};
  s.categories ||= [
    { id: "c1", name: "Key concept", color: "accent" },
    { id: "c2", name: "Definition", color: "success" },
    { id: "c3", name: "Question", color: "warning" },
    { id: "c4", name: "For the exam", color: "danger" },
  ];
  s.theme ||= null;
  s.speed ||= 1;
  s.lastBook ||= null;
  s.appearance ||= { size: 2, font: "serif", space: "regular" };
  s.user ||= null;
  s.voice ||= "sam";
  return s;
}
const save = () => {
  store.updatedAt = Date.now();
  localStorage.setItem(STORE_KEY, JSON.stringify(store));
  schedulePush();
};
const bookState = (slug) => {
  const b = (store.books[slug] ||= { chapter: 1, chapters: {} });
  b.chapter ||= 1;
  b.chapters ||= {};
  return b;
};
// per-chapter slice: position + annotations live with the chapter they belong to
const chState = (slug, n) => {
  const b = bookState(slug);
  return (b.chapters[n] ||= { positionMs: 0, highlights: [], bookmarks: [] });
};
const cur = () => chState(current, bookState(current).chapter);
const curChapter = () => books.get(current).book.chapters.find((c) => c.n === bookState(current).chapter)
                       || books.get(current).book.chapters[0];

/* Align the book's own tokens (punctuation intact) with the TTS word
   timings, which split on whitespace AND punctuation. Greedy consume:
   one text token may span several timing words ("self-esteem"). */
function alignTokens(text, words) {
  const norm = (s) => s.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
  const tokens = text.split(/\s+/);
  const out = [];
  let j = 0;
  for (const tok of tokens) {
    const target = norm(tok);
    let startMs = null, endMs = null;
    if (target && j < words.length) {
      let acc = "";
      let k = j;
      while (k < words.length && acc.length < target.length) {
        acc += norm(words[k].text);
        k++;
        if (acc === target) break;
      }
      if (acc === target) {
        startMs = words[j].startMs;
        endMs = words[k - 1].endMs;
        j = k;
      } else if (norm(words[j].text).startsWith(target) || target.startsWith(norm(words[j].text))) {
        startMs = words[j].startMs;
        endMs = words[j].endMs;
        j++;
      }
    }
    if (startMs === null) {
      const prev = out.at(-1);
      startMs = prev ? prev.endMs : 0;
      endMs = startMs;
    }
    out.push({ text: tok, startMs, endMs });
  }
  return out;
}

/* ---------------- boot ---------------- */

(async function boot() {
  applyTheme(store.theme, false);
  applyAppearance(false);
  audio.playbackRate = store.speed;
  $("speed").textContent = speedLabel(store.speed);
  initAuth();

  for (const slug of SLUGS) {
    const book = await fetch(mediaUrl(`books/${slug}/book.json`), { cache: "no-cache" }).then((r) => r.json());
    books.set(slug, { book, manifest: null, manifests: {} });
  }
  renderHome();
  renderCategories();
  wireEvents();
  initMediaSession();
})();

/* ---------------- navigation ---------------- */

function showHome() {
  pause();
  document.body.dataset.view = "home";
  $("viewReader").hidden = true;
  $("viewHome").hidden = false;
  renderHome();
}

function showReader(slug, opts = {}) {
  document.body.dataset.view = "reader";
  $("viewHome").hidden = true;
  $("viewReader").hidden = false;
  openBook(slug, opts);
}

/* ---- app-style zoom: the cover scales up into the reader and back ---- */

const REDUCE_MOTION = matchMedia("(prefers-reduced-motion: reduce)");

function coverRect(coverEl) {
  const r = coverEl.getBoundingClientRect();
  return { top: r.top, left: r.left, width: r.width, height: r.height };
}

// Aspect-preserving zoom target: the cover scales up, centered, never stretched.
function zoomTarget(rect) {
  const s = Math.min((innerWidth * 0.86) / rect.width, (innerHeight * 0.78) / rect.height);
  const w = rect.width * s, h = rect.height * s;
  return { top: (innerHeight - h) / 2, left: (innerWidth - w) / 2, width: w, height: h };
}

function playZoom(src, a, b, { fadeBackdrop, fadeImgIn, onDone }) {
  const bd = document.createElement("div");
  bd.className = "sc-zoom-backdrop";
  const img = document.createElement("img");
  img.className = "sc-zoom";
  img.alt = "";
  img.src = src;
  Object.assign(img.style, { top: a.top + "px", left: a.left + "px", width: a.width + "px", height: a.height + "px" });
  bd.style.opacity = fadeBackdrop === "in" ? "0" : "1";
  if (fadeImgIn) img.style.opacity = "0";
  document.body.append(bd, img);
  requestAnimationFrame(() => requestAnimationFrame(() => {
    bd.style.opacity = fadeBackdrop === "in" ? "1" : "0";
    img.style.opacity = "1";
    Object.assign(img.style, { top: b.top + "px", left: b.left + "px", width: b.width + "px", height: b.height + "px" });
  }));
  setTimeout(() => {
    onDone?.();
    img.style.opacity = "0";
    bd.style.opacity = "0";
    setTimeout(() => { img.remove(); bd.remove(); }, 260);
  }, 340);
}

function openWithZoom(slug, coverEl, opts = {}) {
  if (REDUCE_MOTION.matches || !coverEl) return showReader(slug, opts);
  const from = coverRect(coverEl);
  playZoom(mediaUrl(`books/${slug}/cover.png`), from, zoomTarget(from), {
    fadeBackdrop: "in",
    onDone: () => showReader(slug, opts),
  });
}

function closeWithZoom() {
  const slug = current;
  pause();
  closeSheets();
  showHome();
  if (REDUCE_MOTION.matches || !slug) return;
  const tile = [...document.querySelectorAll(".sc-tile-cover")].find((img) => img.src.includes(`/${slug}/`));
  if (!tile) return;
  const to = coverRect(tile);
  playZoom(mediaUrl(`books/${slug}/cover.png`), zoomTarget(to), to, { fadeBackdrop: "out", fadeImgIn: true });
}

/* ---------------- home ---------------- */

function renderHome() {
  // continue card
  const last = store.lastBook && books.get(store.lastBook);
  const cc = $("continueCard");
  const lastCh = last && bookState(store.lastBook).chapters?.[bookState(store.lastBook).chapter];
  if (last && last.manifest && lastCh?.positionMs > 1000) {
    const st = lastCh;
    const pct = Math.min(100, Math.round((st.positionMs / last.manifest.totalMs) * 100));
    $("continueCover").src = mediaUrl(`books/${store.lastBook}/cover.png`);
    $("continueCover").alt = "";
    $("continueTitle").textContent = last.book.title;
    const chTitle = last.book.chapters.find((c) => c.n === bookState(store.lastBook).chapter)?.title || "";
    $("continueSub").textContent = `${chTitle} · ${fmt(last.manifest.totalMs - st.positionMs)} left`;
    $("continueBar").setAttribute("aria-valuenow", pct);
    $("continueBarFill").style.inlineSize = pct + "%";
    cc.hidden = false;
  } else {
    cc.hidden = true;
  }

  // grid
  const grid = $("bookGrid");
  grid.replaceChildren();
  for (const slug of SLUGS) {
    const { book } = books.get(slug);
    const b = bookState(slug);
    const started = Object.values(b.chapters || {}).filter((c) => c.positionMs > 1000).length;
    const pct = Math.round((started / book.chapters.length) * 100);
    const el = document.createElement("button");
    el.className = "sc-tile";
    el.innerHTML = `
      <span class="sc-tile-coverwrap">
        <img class="sc-tile-cover" src="${mediaUrl(`books/${slug}/cover.png`)}" alt="">
        <span class="sc-tile-bar"><span style="inline-size:${pct}%"></span></span>
      </span>
      <span class="sc-tile-title">${esc(book.title)}</span>
      <span class="sc-tile-sub">${esc(book.author)} · ${book.chapters.filter((c) => !c.bib).length} chapters</span>`;
    el.setAttribute("aria-label", `${book.title}, ${started} of ${book.chapters.filter((c) => !c.bib).length} chapters started`);
    el.addEventListener("click", () => openWithZoom(slug, el.querySelector(".sc-tile-cover")));
    grid.appendChild(el);
  }
}

const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ---------------- open & render a book ---------------- */

async function openBook(slug, { autoplay = false, chapter = null } = {}) {
  current = slug;
  store.lastBook = slug;
  const entry = books.get(slug);
  const b = bookState(slug);
  if (chapter) b.chapter = chapter;
  if (!entry.book.chapters.some((c) => c.n === b.chapter)) b.chapter = entry.book.chapters[0].n;

  const ch = curChapter();
  // prefer the chosen narrator; fall back to any voice that has this chapter
  let manifest = await getManifest(slug, store.voice, ch.n);
  if (!manifest) {
    for (const v of VOICE_OPTIONS) {
      if (v.id === store.voice) continue;
      manifest = await getManifest(slug, v.id, ch.n);
      if (manifest) break;
    }
  }
  entry.manifest = manifest;

  $("bookTitle").textContent = entry.book.title;
  $("bookChapter").textContent = ch.title;
  $("deskCover").src = mediaUrl(`books/${slug}/cover.png`);
  $("deskChapter").textContent = ch.title;

  lastWordKey = "";
  paraIdx = -1;
  audio.removeAttribute("src");
  const page = $("page");
  page.replaceChildren();
  ch.paragraphs.forEach((text, p) => {
    const el = document.createElement("p");
    el.className = "sc-para";
    el.dataset.p = p;
    // Audio may cover fewer paragraphs than the text (partially narrated
    // chapter). Those paragraphs still render, just without word timings.
    const mp = manifest && manifest.paragraphs[p];
    const words = mp ? mp.tokens : text.split(/\s+/).map((t) => ({ text: t }));
    words.forEach((w, i) => {
      const span = document.createElement("span");
      span.className = "sc-w";
      span.dataset.p = p;
      span.dataset.w = i;
      span.textContent = w.text;
      el.appendChild(span);
      el.appendChild(document.createTextNode(" "));
    });
    page.appendChild(el);
  });

  // These books are ingested as excerpts. Saying so at the end of the text is
  // the difference between "the app is broken" and "the chapter stops here".
  const narratedParas = manifest ? manifest.paragraphs.length : 0;
  const partial = narratedParas > 0 && narratedParas < ch.paragraphs.length;
  if (ch.excerpt || partial) {
    const note = document.createElement("div");
    note.className = "sc-excerpt-end";
    note.id = "excerptEnd";
    const missing = partial
      ? ch.paragraphs.slice(narratedParas).reduce((n, t) => n + t.split(/\s+/).length, 0)
      : Math.max(0, (ch.fullWords || 0) - (ch.words || 0));
    note.innerHTML = `
      <p class="sc-excerpt-title">${partial ? "End of narrated audio" : "End of excerpt"}</p>
      <p class="sc-excerpt-body">${partial
        ? `The rest of this chapter — about ${missing.toLocaleString()} words — is here to read, but hasn't been narrated yet.`
        : `This chapter continues for about ${missing.toLocaleString()} more words that haven't been narrated yet. Only the opening of each chapter is in the app so far.`}</p>
      <button class="fds-button" data-variant="secondary" id="excerptNext">Next chapter</button>`;
    page.appendChild(note);
  }

  applyHighlights();
  renderNotes();
  renderBookmarks();
  renderScrubMarks();
  renderChapters();
  updateMediaMetadata();

  const total = manifest ? manifest.totalMs : 0;
  $("timeTotal").textContent = fmt(total);
  $("playPause").disabled = !manifest;
  $("playPause").title = manifest ? "" : "Narration for this chapter is still being generated";
  if (manifest) {
    seekTo(Math.min(cur().positionMs, Math.max(0, total - 500)), { autoplay, scroll: "instant" });
  } else {
    $("timeNow").textContent = "0:00";
    $("progressBadge").textContent = "Audio not available yet — text is readable";
  }
  save();
}

/* ---------------- voices ---------------- */

const VOICE_OPTIONS = [
  { id: "sam", name: "Sam", desc: "Warm, clear and engaging — the house narrator" },
  { id: "morgan", name: "Morgan", desc: "Deep, slow and relaxing, with an unhurried cadence" },
];

async function getManifest(slug, voiceId, chapterN) {
  const entry = books.get(slug);
  const key = `${voiceId}-${chapterN}`;
  if (!(key in entry.manifests)) {
    const file = `manifests/${voiceId}-ch${String(chapterN).padStart(2, "0")}.json`;
    const m = await fetch(mediaUrl(`books/${slug}/${file}`), { cache: "no-cache" })
      .then((r) => (r.ok ? r.json() : null)).catch(() => null);
    const ch = entry.book.chapters.find((c) => c.n === chapterN);
    if (m && ch) m.paragraphs.forEach((p, i) => { p.tokens = alignTokens(ch.paragraphs[i], p.words); });
    entry.manifests[key] = m;
  }
  return entry.manifests[key];
}

async function setVoice(voiceId) {
  const old = man();
  const oldMs = old ? globalMs() : 0;
  const wasPlaying = playing;
  pause();
  const n = bookState(current).chapter;
  const m = await getManifest(current, voiceId, n);
  if (!m) { renderVoiceSheet(); return; }   // not generated for this chapter
  store.voice = voiceId;
  save();
  books.get(current).manifest = m;
  $("timeTotal").textContent = fmt(m.totalMs);
  lastWordKey = "";
  audio.removeAttribute("src");
  paraIdx = -1;
  // same text, different pacing: carry the position over proportionally
  const frac = old ? oldMs / old.totalMs : 0;
  seekTo(frac * m.totalMs, { autoplay: wasPlaying, scroll: "instant" });
  renderScrubMarks();
  renderVoiceSheet();
}

function renderVoiceSheet() {
  const host = $("voiceList");
  host.replaceChildren();
  const n = bookState(current).chapter;
  for (const v of VOICE_OPTIONS) {
    const loaded = books.get(current)?.manifests[`${v.id}-${n}`];
    const missing = loaded === null;
    const el = document.createElement("button");
    el.className = "sc-voice-opt";
    el.setAttribute("aria-pressed", String(store.voice === v.id));
    el.innerHTML = `
      <span class="sc-voice-name">${esc(v.name)}</span>
      <span class="sc-voice-desc">${esc(v.desc)}</span>
      ${missing ? `<span class="sc-voice-desc">Not generated for this chapter yet</span>` : ""}`;
    el.addEventListener("click", () => setVoice(v.id));
    host.appendChild(el);
  }
}

/* ---------------- chapters ---------------- */

function renderChapters() {
  const { book } = books.get(current);
  const b = bookState(current);
  const realChs = book.chapters.filter((c) => !c.bib);
  const totalCh = realChs.length;
  const startedCh = realChs.filter((c) => (b.chapters?.[c.n]?.positionMs || 0) > 1000).length;

  for (const host of document.querySelectorAll(".sc-chapters-host")) {
    host.replaceChildren();

    // Book-level summary so "where am I" is answerable at a glance.
    const summary = document.createElement("p");
    summary.className = "sc-chapters-summary";
    summary.textContent = `Chapter ${b.chapter} of ${totalCh} · ${startedCh} started`;
    host.appendChild(summary);

    book.chapters.forEach((ch) => {
      const st = b.chapters?.[ch.n];
      const active = ch.n === b.chapter;
      // Duration is only known once a chapter has been played (its manifest is
      // cached); fall back to a word-count estimate so every row says something.
      const knownMs = books.get(current).manifests?.[`${store.voice}-${ch.n}`]?.totalMs;
      const estMs = knownMs || (ch.words ? (ch.words / 151) * 60000 : 0);
      const pos = st?.positionMs || 0;
      const pct = estMs ? Math.min(100, Math.round((pos / estMs) * 100)) : 0;
      const finished = pct >= 98;

      const el = document.createElement("button");
      el.className = "sc-chapter";
      el.dataset.state = active ? "current" : finished ? "finished" : pos > 1000 ? "started" : "new";
      if (active) el.setAttribute("aria-current", "true");

      // The speaker icon already marks the playing row; a badge was redundant.
      const status = ch.bib ? "Text only — references"
        : active ? ""
        : finished ? "Finished"
        : pos > 1000 ? `${pct}% · ${fmt(Math.max(0, estMs - pos))} left`
        : "Not started";

      el.innerHTML = `
        <span class="sc-chapter-n">${finished && !active ? '<i class="fa-solid fa-check"></i>' : (ch.label || ch.n)}</span>
        <span class="sc-chapter-meta">
          <span class="sc-chapter-title">${esc(ch.title)}</span>
          <span class="sc-chapter-sub">${status}${estMs && !ch.bib ? `${status ? " · " : ""}${fmt(estMs)}` : ""}</span>
          ${pos > 1000 && !finished
            ? `<span class="sc-chapter-bar"><span style="inline-size:${pct}%"></span></span>` : ""}
        </span>
        <i class="fa-solid ${ch.bib ? "fa-book-open" : active ? "fa-volume-high" : "fa-play"}" aria-hidden="true"></i>`;

      el.setAttribute("aria-label",
        `Chapter ${ch.label || ch.n}, ${ch.title}, ${active ? "now playing" : finished ? "finished" : pos > 1000 ? pct + " percent listened" : "not started"}`);

      el.addEventListener("click", () => {
        closeSheets();
        userScrolledAt = 0;
        openBook(current, { chapter: ch.n, autoplay: true });
      });
      host.appendChild(el);
    });
  }
}

/* ---------------- lock screen / background playback ----------------
   Media Session keeps the OS transport (lock screen, Control Center,
   headphone buttons) in sync so playback survives the screen turning off. */

function updateMediaMetadata() {
  if (!("mediaSession" in navigator) || !current) return;
  const { book } = books.get(current);
  const ch = curChapter();
  navigator.mediaSession.metadata = new MediaMetadata({
    title: ch.title,
    artist: book.author,
    album: book.title,
    artwork: [{ src: new URL(mediaUrl(`books/${current}/cover.png`), location.href).href, sizes: "480x615", type: "image/png" }],
  });
}

function initMediaSession() {
  if (!("mediaSession" in navigator)) return;
  const ms = navigator.mediaSession;
  const set = (action, handler) => { try { ms.setActionHandler(action, handler); } catch { /* unsupported */ } };
  set("play", () => play());
  set("pause", () => pause());
  set("seekbackward", (d) => seekTo(globalMs() - (d?.seekOffset || 15) * 1000));
  set("seekforward", (d) => seekTo(globalMs() + (d?.seekOffset || 15) * 1000));
  set("seekto", (d) => { if (d?.seekTime != null) seekTo(d.seekTime * 1000); });
  set("previoustrack", () => {
    const chs = books.get(current).book.chapters;
    const i = chs.findIndex((c) => c.n === bookState(current).chapter);
    if (globalMs() > 5000 || i <= 0) seekTo(0);
    else openBook(current, { chapter: chs[i - 1].n, autoplay: true });
  });
  set("nexttrack", () => {
    const chs = books.get(current).book.chapters;
    const i = chs.findIndex((c) => c.n === bookState(current).chapter);
    if (i >= 0 && i < chs.length - 1) openBook(current, { chapter: chs[i + 1].n, autoplay: true });
  });
}

function updatePositionState(ms) {
  if (!("mediaSession" in navigator) || !navigator.mediaSession.setPositionState) return;
  const m = man();
  if (!m) return;
  try {
    navigator.mediaSession.setPositionState({
      duration: m.totalMs / 1000,
      playbackRate: audio.playbackRate,
      position: Math.min(ms, m.totalMs) / 1000,
    });
  } catch { /* out-of-range during a seek */ }
}

/* ---------------- playback & sync ---------------- */

const man = () => books.get(current)?.manifest;

function globalMs() {
  const m = man();
  if (!m) return 0;
  return m.paragraphs[paraIdx].startMs + audio.currentTime * 1000;
}

function play() {
  if (!man() || !audio.src) return;
  audio.play().then(() => {
    playing = true;
    if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "playing";
    $("playIcon").className = "fa-solid fa-pause";
    $("playPause").setAttribute("aria-label", "Pause");
    tick();
  }).catch(() => { /* needs user gesture */ });
}

function pause() {
  audio.pause();
  playing = false;
  if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "paused";
  cancelAnimationFrame(rafId);
  $("playIcon").className = "fa-solid fa-play";
  $("playPause").setAttribute("aria-label", "Play");
  persistPosition();
}

function seekTo(ms, { autoplay = playing, scroll = "instant" } = {}) {
  const m = man();
  if (!m) return;
  ms = Math.max(0, Math.min(ms, m.totalMs - 50));
  let p = m.paragraphs.findIndex((pp) => ms < pp.startMs + pp.durationMs);
  if (p < 0) p = m.paragraphs.length - 1;
  const local = (ms - m.paragraphs[p].startMs) / 1000;
  if (paraIdx !== p || !audio.src.endsWith(m.paragraphs[p].audio)) {
    paraIdx = p;
    audio.src = mediaUrl(`books/${current}/${m.paragraphs[p].audio}`);
  }
  audio.currentTime = Math.max(0, local);
  syncUI(ms, scroll);
  if (autoplay) play(); else persistPosition();
}

audio.addEventListener("ended", () => {
  const m = man();
  if (!m) return;
  if (paraIdx < m.paragraphs.length - 1) {
    seekTo(m.paragraphs[paraIdx + 1].startMs, { autoplay: true });
    return;
  }
  const chs = books.get(current).book.chapters;
  const i = chs.findIndex((c) => c.n === bookState(current).chapter);
  const finished = curChapter();
  const fm = man();
  const partialChapter = fm && finished && fm.paragraphs.length < finished.paragraphs.length;
  // A truncated chapter didn't really end — jumping onward silently is what
  // made this look like the player was skipping ahead on its own.
  if (finished?.excerpt || partialChapter) {
    pause();
    userScrolledAt = Date.now();
    $("excerptEnd")?.scrollIntoView({ behavior: REDUCE_MOTION.matches ? "auto" : "smooth", block: "center" });
    return;
  }
  // Advance to the next NARRATED chapter; bibliography entries are text-only
  // and would strand autoplay on a silent page.
  const next = chs.slice(i + 1).find((c) => !c.bib);
  if (i >= 0 && next) {
    userScrolledAt = 0;
    openBook(current, { chapter: next.n, autoplay: true });
  } else {
    pause();
  }
});

function tick() {
  if (!playing) return;
  syncUI(globalMs(), "smooth");
  rafId = requestAnimationFrame(tick);
}
// rAF is throttled in hidden tabs; timeupdate (~4 Hz) keeps sync alive there.
audio.addEventListener("timeupdate", () => { if (playing) syncUI(globalMs(), "smooth"); });

function syncUI(ms, scrollMode) {
  const m = man();
  if (!m) return;

  const pct = (ms / m.totalMs) * 100;
  $("scrubPlayed").style.inlineSize = pct + "%";
  $("scrubHead").style.insetInlineStart = pct + "%";
  $("scrub").setAttribute("aria-valuenow", Math.round(pct));
  $("timeNow").textContent = fmt(ms);
  $("progressBadge").textContent = `${Math.round(pct)}% · ${fmt(m.totalMs - ms)} left`;
  updatePositionState(ms);

  const para = m.paragraphs[paraIdx];
  const local = ms - para.startMs;
  let wi = para.tokens.findIndex((w) => local < w.endMs);
  if (wi < 0) wi = para.tokens.length - 1;
  const key = `${current}:${paraIdx}:${wi}`;
  if (key !== lastWordKey) {
    lastWordKey = key;
    document.querySelectorAll(".sc-w.now").forEach((el) => el.classList.remove("now"));
    const pEl = $("page").children[paraIdx];
    if (pEl) {
      [...pEl.children].forEach((el, i) => {
        el.classList.toggle("said", i < wi);
        if (i === wi) el.classList.add("now");
      });
      [...$("page").children].forEach((el, p) => {
        if (p < paraIdx) el.querySelectorAll(".sc-w:not(.said)").forEach((w) => w.classList.add("said"));
        if (p > paraIdx) el.querySelectorAll(".sc-w.said").forEach((w) => w.classList.remove("said"));
      });
    }
  }
  const nowEl = document.querySelector(".sc-w.now");
  if (nowEl) autoScroll(nowEl, scrollMode);
}

let progScrollUntil = 0; // our own scrolls end up as "scroll" events too

/* Auto-follow easing is stepped by sync ticks (timeupdate/rAF), never by
   native smooth scrolling — whose rAF-driven animation stalls in throttled
   tabs and made following silently stop. */
function autoScroll(el, mode) {
  if (!el) return;
  const page = $("page");
  const r = el.getBoundingClientRect();
  const pr = page.getBoundingClientRect();
  const delta = r.top - (pr.top + pr.height * 0.34);
  if (mode === "instant") {
    progScrollUntil = Date.now() + 300;
    page.scrollTop += delta;
    return;
  }
  if (!playing) return;                              // paused: the reader owns the scroll
  if (Date.now() - userScrolledAt < 2000) return;    // mid-browse: yield, then resume following
  const outOfBand = r.top < pr.top + 40 || r.top > pr.top + pr.height * 0.68;
  if (!outOfBand) return;
  progScrollUntil = Date.now() + 400;
  const step = REDUCE_MOTION.matches ? delta : delta * 0.35;
  page.scrollTop += step;
}

let persistTimer = 0;
function persistPosition() {
  clearTimeout(persistTimer);
  persistTimer = setTimeout(() => {
    if (!current) return;
    cur().positionMs = Math.round(globalMs());
    save();
  }, 250);
}
audio.addEventListener("timeupdate", persistPosition);

function speedLabel(s) { return { 0.8: "0.8×", 1: "1.0×", 1.25: "1.25×", 1.5: "1.5×", 2: "2.0×" }[s] || s + "×"; }

const fmt = (ms) => {
  const s = Math.max(0, Math.round(ms / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(ss).padStart(2, "0");
};

/* ---------------- highlights & notes ---------------- */

function catById(id) { return store.categories.find((c) => c.id === id) || store.categories[0]; }

function applyHighlights() {
  document.querySelectorAll(".sc-w[data-hl]").forEach((el) => { delete el.dataset.hl; delete el.dataset.note; el.removeAttribute("title"); });
  for (const h of cur().highlights) {
    const cat = catById(h.catId);
    const pEl = $("page").children[h.p];
    if (!pEl) continue;
    for (let i = h.w0; i <= h.w1; i++) {
      const w = pEl.children[i];
      if (w) { w.dataset.hl = cat.color; w.title = cat.name; }
    }
    if (h.note) {
      const lastW = pEl.children[h.w1];
      if (lastW) lastW.dataset.note = "1";
    }
  }
}

function renderNotes() {
  const all = cur().highlights;
  const hs = all
    .filter((h) => !activeCatFilter || h.catId === activeCatFilter)
    .sort((a, b) => a.p - b.p || a.w0 - b.w0);
  $("noteCount").textContent = all.length;
  for (const host of document.querySelectorAll(".sc-notes-host")) {
    host.replaceChildren();
    if (!hs.length) {
      host.innerHTML = `<p class="sc-empty">${activeCatFilter ? "No highlights in this category yet." : "Select any passage while you listen to highlight it or attach a note."}</p>`;
      continue;
    }
    for (const h of hs) {
      const cat = catById(h.catId);
      const el = document.createElement("div");
      el.className = "sc-note";
      el.dataset.catBorder = cat.color;
      el.setAttribute("role", "button");
      el.tabIndex = 0;
      el.innerHTML = `
        <div class="sc-note-quote">“${esc(h.quote)}”</div>
        ${h.note ? `<div class="sc-note-text">${esc(h.note)}</div>` : ""}
        <div class="sc-note-foot">
          <span class="sc-cat-dot" data-cat-color="${cat.color}"></span>${esc(cat.name)}
          <button class="sc-note-del" aria-label="Delete highlight">
            <i class="fa-regular fa-trash-can" aria-hidden="true"></i>
          </button>
        </div>`;
      el.addEventListener("click", (e) => {
        if (e.target.closest(".sc-note-del")) return removeHighlight(h.id);
        jumpToWord(h.p, h.w0);
      });
      el.addEventListener("keydown", (e) => { if (e.key === "Enter") jumpToWord(h.p, h.w0); });
      host.appendChild(el);
    }
  }
}

function jumpToWord(p, w) {
  const m = man();
  if (!m) return;
  userScrolledAt = 0;
  seekTo(m.paragraphs[p].startMs + m.paragraphs[p].tokens[w].startMs);
}

function removeHighlight(id) {
  const st = cur();
  st.highlights = st.highlights.filter((h) => h.id !== id);
  save();
  applyHighlights();
  renderNotes();
  renderCategories();
}

function wordRangeFromSelection() {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
  const range = sel.getRangeAt(0);
  const wordEl = (n) => (n.nodeType === 1 ? n : n.parentElement)?.closest?.(".sc-w");
  let a = wordEl(range.startContainer), b = wordEl(range.endContainer);
  if (!a && !b) return null;
  a ||= b; b ||= a;
  if (a.dataset.p !== b.dataset.p) {
    b = [...$("page").children[a.dataset.p].children].at(-1);
  }
  let w0 = +a.dataset.w, w1 = +b.dataset.w;
  if (w0 > w1) [w0, w1] = [w1, w0];
  return { p: +a.dataset.p, w0, w1 };
}

function openPopover(rangeInfo, rect) {
  pendingSel = rangeInfo;
  popCat = store.categories[0].id;
  renderPopCats();
  $("popNote").value = "";
  const pop = $("pop");
  pop.hidden = false;
  const pw = pop.offsetWidth || 280;
  const x = Math.min(Math.max(8, rect.left + rect.width / 2 - pw / 2), innerWidth - pw - 8);
  const y = rect.bottom + 8 + 200 > innerHeight ? Math.max(8, rect.top - 8 - pop.offsetHeight) : rect.bottom + 8;
  pop.style.left = x + "px";
  pop.style.top = y + "px";
}

function renderPopCats() {
  const host = $("popCats");
  host.replaceChildren();
  for (const c of store.categories) {
    const b = document.createElement("button");
    b.className = "sc-pop-cat";
    b.setAttribute("aria-pressed", String(c.id === popCat));
    b.innerHTML = `<span class="sc-cat-dot" data-cat-color="${c.color}"></span>${esc(c.name)}`;
    b.addEventListener("click", () => { popCat = c.id; renderPopCats(); });
    host.appendChild(b);
  }
}

function saveHighlight() {
  if (!pendingSel) return;
  const { p, w0, w1 } = pendingSel;
  const pEl = $("page").children[p];
  const quote = [...pEl.children].slice(w0, w1 + 1).map((el) => el.textContent).join(" ");
  cur().highlights.push({
    id: "h" + Date.now(), p, w0, w1,
    catId: popCat,
    note: $("popNote").value.trim(),
    quote,
    createdMs: Date.now(),
  });
  save();
  closePopover();
  applyHighlights();
  renderNotes();
  renderCategories();
}

function closePopover() {
  $("pop").hidden = true;
  pendingSel = null;
  window.getSelection()?.removeAllRanges();
}

/* ---------------- categories ---------------- */

function renderCategories() {
  const host = $("categoryList");
  host.replaceChildren();
  const counts = {};
  for (const slug of SLUGS)
    for (const chs of Object.values(bookState(slug).chapters || {}))
      for (const h of chs.highlights || []) counts[h.catId] = (counts[h.catId] || 0) + 1;
  for (const c of store.categories) {
    const el = document.createElement("div");
    el.className = "sc-cat";
    el.setAttribute("role", "button");
    el.tabIndex = 0;
    el.setAttribute("aria-pressed", String(activeCatFilter === c.id));
    el.innerHTML = `
      <span class="sc-cat-dot" data-cat-color="${c.color}"></span>
      <span class="sc-cat-name">${esc(c.name)}</span>
      <span class="sc-cat-count">${counts[c.id] || 0}</span>
      <button class="sc-cat-edit" aria-label="Rename ${esc(c.name)}">
        <i class="fa-regular fa-pen" aria-hidden="true"></i>
      </button>`;
    el.addEventListener("click", (e) => {
      if (e.target.closest(".sc-cat-edit")) return openCatDialog(c.id);
      activeCatFilter = activeCatFilter === c.id ? null : c.id;
      renderCategories();
      renderNotes();
      if (activeCatFilter) selectTab("notes");
    });
    host.appendChild(el);
  }
}

function openCatDialog(catId = null) {
  editingCatId = catId;
  const cat = catId ? catById(catId) : null;
  $("catDialogTitle").textContent = cat ? "Edit category" : "New category";
  $("catSave").textContent = cat ? "Save" : "Create";
  $("catName").value = cat ? cat.name : "";
  dialogColor = cat ? cat.color : CAT_COLORS[0];
  renderDialogColors();
  $("catDialog").showModal();
}

function renderDialogColors() {
  const host = $("catColors");
  host.replaceChildren();
  for (const color of CAT_COLORS) {
    const b = document.createElement("button");
    b.className = "sc-pop-cat";
    b.setAttribute("aria-pressed", String(color === dialogColor));
    b.innerHTML = `<span class="sc-cat-dot" data-cat-color="${color}"></span>`;
    b.setAttribute("aria-label", color);
    b.addEventListener("click", () => { dialogColor = color; renderDialogColors(); });
    host.appendChild(b);
  }
}

/* ---------------- bookmarks ---------------- */

function renderBookmarks() {
  const host = $("bookmarkList");
  host.replaceChildren();
  const bms = [...cur().bookmarks].sort((a, b) => a.ms - b.ms);
  if (!bms.length) {
    host.innerHTML = `<p class="sc-empty">Press <strong>B</strong> or the bookmark button in the player to pin a moment.</p>`;
    return;
  }
  for (const bm of bms) {
    const el = document.createElement("button");
    el.className = "sc-bm";
    el.innerHTML = `
      <i class="fa-solid fa-bookmark" aria-hidden="true"></i>
      <span class="sc-bm-label">${esc(bm.label)}</span>
      <span class="sc-bm-time">${fmt(bm.ms)}</span>
      <span class="sc-bm-x" role="button" aria-label="Delete bookmark">
        <i class="fa-regular fa-xmark" aria-hidden="true"></i>
      </span>`;
    el.addEventListener("click", (e) => {
      if (e.target.closest(".sc-bm-x")) {
        const st = cur();
        st.bookmarks = st.bookmarks.filter((b) => b.id !== bm.id);
        save(); renderBookmarks(); renderScrubMarks();
        return;
      }
      userScrolledAt = 0;
      seekTo(bm.ms);
    });
    host.appendChild(el);
  }
}

function addBookmark() {
  const m = man();
  if (!m) return;
  const ms = globalMs();
  const para = m.paragraphs[paraIdx];
  const local = ms - para.startMs;
  let wi = para.tokens.findIndex((w) => local < w.endMs);
  if (wi < 0) wi = 0;
  const label = para.tokens.slice(wi, wi + 4).map((w) => w.text).join(" ") + "…";
  cur().bookmarks.push({ id: "b" + Date.now(), ms: Math.round(ms), label });
  save();
  renderBookmarks();
  renderScrubMarks();
}

function renderScrubMarks() {
  const m = man();
  const host = $("scrubMarks");
  host.replaceChildren();
  if (!m) return;
  for (const bm of cur().bookmarks) {
    const t = document.createElement("div");
    t.className = "sc-scrub-mark";
    t.style.insetInlineStart = (bm.ms / m.totalMs) * 100 + "%";
    host.appendChild(t);
  }
}

/* ---------------- theme & appearance ---------------- */

function applyTheme(mode, persist = true) {
  const html = document.documentElement;
  const resolved = mode || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  html.dataset.mode = resolved;
  const icon = resolved === "dark" ? "fa-regular fa-sun" : "fa-regular fa-moon";
  $("themeIcon").className = icon;
  $("themeIcon2").className = icon;
  if (persist) { store.theme = mode; save(); }
  $("themeLight").setAttribute("aria-pressed", String(mode === "light"));
  $("themeDark").setAttribute("aria-pressed", String(mode === "dark"));
  $("themeSystem").setAttribute("aria-pressed", String(mode === null || mode === undefined));
}

function applyAppearance(persist = true) {
  const a = store.appearance;
  document.body.dataset.textSize = a.size;
  document.body.dataset.bookFont = ["sans", "legible"].includes(a.font) ? a.font : "serif";
  document.body.dataset.lineSpace = a.space;
  $("styleSerif").setAttribute("aria-pressed", String(!["sans", "legible"].includes(a.font)));
  $("styleSans").setAttribute("aria-pressed", String(a.font === "sans"));
  $("styleLegible").setAttribute("aria-pressed", String(a.font === "legible"));
  $("spaceRegular").setAttribute("aria-pressed", String(!["relaxed", "loose"].includes(a.space)));
  $("spaceRelaxed").setAttribute("aria-pressed", String(a.space === "relaxed"));
  $("spaceLoose").setAttribute("aria-pressed", String(a.space === "loose"));
  $("sizeDown").disabled = a.size <= 0;
  $("sizeUp").disabled = a.size >= MAX_TEXT_SIZE;
  if (persist) save();
}

/* ---------------- auth + sync (Supabase, prod only) ----------------
   Static app, no server of our own: Supabase handles Google sign-in and
   stores the whole per-user state blob (RLS: each user reads/writes only
   their own row — see supabase/schema.sql). Dev stays local-only. */

let sb = null;
let sbUser = null;
let pushTimer = 0;
let googleClient = null;

function authBadge(html) { $("authSlot").innerHTML = html; }

async function initAuth() {
  if (IS_DEV) {
    authBadge(`<span class="sc-auth-badge" title="Sign-in and sync activate on the deployed site">DEV · sign-in off</span>`);
    return;
  }
  const { supabaseUrl, supabaseAnonKey, googleClientId } = window.SCHAUDIO || {};
  if (!supabaseUrl || !supabaseAnonKey) {
    authBadge(`<span class="sc-auth-badge" title="Set supabaseUrl and supabaseAnonKey in index.html">sign-in unconfigured</span>`);
    return;
  }
  await new Promise((resolve, reject) => {
    const el = document.createElement("script");
    el.src = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js";
    el.onload = resolve;
    el.onerror = reject;
    document.head.appendChild(el);
  }).catch(() => null);
  if (!window.supabase) return authBadge(`<span class="sc-auth-badge">sign-in unavailable</span>`);

  sb = window.supabase.createClient(supabaseUrl, supabaseAnonKey);
  googleClient = googleClientId || null;
  const { data: { session } } = await sb.auth.getSession();
  handleSession(session);
  sb.auth.onAuthStateChange((_evt, s2) => handleSession(s2));
}

/* Google sign-in.
   Preferred path is the ID-token (GIS) flow: the consent UI runs on OUR
   origin, so Google shows "Schaudio" rather than the Supabase callback
   host. If GIS can't load or is dismissed, fall back to the redirect flow,
   which always works. */

function redirectSignIn() {
  return sb.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: location.origin + location.pathname },
  });
}

async function sha256Hex(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

function loadGis() {
  if (window.google?.accounts?.id) return Promise.resolve(true);
  return new Promise((resolve) => {
    const el = document.createElement("script");
    el.src = "https://accounts.google.com/gsi/client";
    el.async = true;
    el.onload = () => resolve(!!window.google?.accounts?.id);
    el.onerror = () => resolve(false);
    document.head.appendChild(el);
  });
}

async function startGoogleSignIn(btn) {
  if (!googleClient || !window.isSecureContext) return redirectSignIn();
  btn.disabled = true;
  try {
    const ok = await loadGis();
    if (!ok) return redirectSignIn();

    const nonce = crypto.randomUUID();
    const hashedNonce = await sha256Hex(nonce);
    let settled = false;

    google.accounts.id.initialize({
      client_id: googleClient,
      nonce: hashedNonce,
      auto_select: false,
      cancel_on_tap_outside: true,
      callback: async (resp) => {
        settled = true;
        const { error } = await sb.auth.signInWithIdToken({
          provider: "google",
          token: resp.credential,
          nonce,
        });
        if (error) redirectSignIn();
      },
    });

    google.accounts.id.prompt((notification) => {
      // One Tap unavailable (blocked, no session, opted out): use the redirect
      if (!settled && (notification.isNotDisplayed?.() || notification.isSkippedMoment?.())) {
        redirectSignIn();
      }
    });
  } catch {
    redirectSignIn();
  } finally {
    setTimeout(() => { btn.disabled = false; }, 1200);
  }
}

const GOOGLE_MARK = `<svg class="sc-gmark" viewBox="0 0 48 48" aria-hidden="true">
  <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.7-6.7C35.6 2.6 30.2 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.8 6.1C12.3 13.2 17.7 9.5 24 9.5z"/>
  <path fill="#4285F4" d="M46.1 24.6c0-1.6-.1-3.1-.4-4.6H24v9.1h12.4c-.5 2.9-2.2 5.3-4.7 6.9l7.3 5.7c4.3-3.9 6.8-9.7 6.8-17.1z"/>
  <path fill="#FBBC05" d="M10.4 28.6c-.5-1.4-.8-2.9-.8-4.6s.3-3.2.8-4.6l-7.8-6.1C.9 16.5 0 20.1 0 24s.9 7.5 2.6 10.7l7.8-6.1z"/>
  <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.3-5.7c-2 1.4-4.7 2.3-8.6 2.3-6.3 0-11.7-3.7-13.6-9.2l-7.8 6.1C6.5 42.6 14.6 48 24 48z"/>
</svg>`;

function handleSession(session) {
  sbUser = session?.user || null;
  const slot = $("authSlot");

  if (!sbUser) {
    slot.replaceChildren();
    const btn = document.createElement("button");
    btn.className = "sc-signin";
    btn.id = "signIn";
    btn.innerHTML = `${GOOGLE_MARK}<span>Sign in</span>`;
    btn.title = "Sign in to sync your progress, highlights and notes across devices";
    btn.addEventListener("click", () => startGoogleSignIn(btn));
    slot.appendChild(btn);
    return;
  }

  const name = sbUser.user_metadata?.full_name || sbUser.email || "Account";
  const email = sbUser.email || "";
  const pic = sbUser.user_metadata?.avatar_url;
  const initial = (name.trim()[0] || "?").toUpperCase();

  slot.innerHTML = `
    <span class="sc-account">
      <button class="sc-account-btn" id="accountBtn" aria-expanded="false" aria-haspopup="menu">
        ${pic ? `<img class="sc-avatar" src="${esc(pic)}" alt="">`
              : `<span class="sc-avatar sc-avatar-initial">${esc(initial)}</span>`}
        <span class="sc-account-name">${esc(name.split(" ")[0])}</span>
        <i class="fa-solid fa-chevron-down" aria-hidden="true"></i>
      </button>
      <div class="sc-account-menu" id="accountMenu" role="menu" hidden>
        <div class="sc-account-who">
          ${pic ? `<img class="sc-avatar" src="${esc(pic)}" alt="">`
                : `<span class="sc-avatar sc-avatar-initial">${esc(initial)}</span>`}
          <span class="sc-account-meta"><strong>${esc(name)}</strong><span>${esc(email)}</span></span>
        </div>
        <p class="sc-account-sync">Progress, highlights and notes sync across your devices.</p>
        <button class="sc-signout" id="signOut">
          <i class="fa-regular fa-arrow-right-from-bracket" aria-hidden="true"></i> Sign out
        </button>
      </div>
    </span>`;

  const btn = $("accountBtn"), menu = $("accountMenu");
  btn.addEventListener("click", () => {
    const show = menu.hidden;
    menu.hidden = !show;
    btn.setAttribute("aria-expanded", String(show));
  });
  document.addEventListener("pointerdown", (e) => {
    if (!menu.hidden && !e.target.closest(".sc-account")) {
      menu.hidden = true;
      btn.setAttribute("aria-expanded", "false");
    }
  });
  $("signOut").addEventListener("click", async () => {
    await sb.auth.signOut();
  });
  pullRemote();
}

async function pullRemote() {
  if (!sb || !sbUser) return;
  const { data, error } = await sb.from("user_state").select("data, updated_at").eq("user_id", sbUser.id).maybeSingle();
  if (error) return;
  const remote = data?.data;
  if (remote && (remote.updatedAt || 0) > (store.updatedAt || 0)) {
    Object.keys(store).forEach((k) => delete store[k]);
    Object.assign(store, remote);
    localStorage.setItem(STORE_KEY, JSON.stringify(store));
    // re-render everything visible from the fresher state
    applyTheme(store.theme, false);
    applyAppearance(false);
    renderHome();
    renderCategories();
    if (document.body.dataset.view === "reader" && current) {
      const slug = current;
      current = null;
      openBook(slug);
    }
  } else {
    schedulePush();
  }
}

function schedulePush() {
  if (!sb || !sbUser) return;
  clearTimeout(pushTimer);
  pushTimer = setTimeout(async () => {
    await sb.from("user_state").upsert({
      user_id: sbUser.id,
      data: store,
      updated_at: new Date().toISOString(),
    });
  }, 2000);
}

/* ---------------- panel & tabs ---------------- */

function selectTab(tab) {
  activeTab = tab;
  document.querySelectorAll(".sc-panel-tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.tab === tab)));
  ["notes", "bookmarks", "categories"].forEach((t) => { $(`tab-${t}`).hidden = t !== tab; });
}

/* ---- bottom sheets: one open at a time, over the player ---- */

const SHEETS = [
  { id: "panel", btn: "notesBtn" },
  { id: "textSheet", btn: "textBtn" },
  { id: "appearanceSheet", btn: "appearanceBtn" },
  { id: "voiceSheet", btn: "voiceBtn" },
  { id: "chaptersSheet", btn: "chaptersBtn" },
];

function closeSheets() {
  for (const { id, btn } of SHEETS) {
    $(id).hidden = true;
    $(btn).setAttribute("aria-expanded", "false");
  }
  $("scrim").hidden = true;
}

function toggleSheet(id, force) {
  const entry = SHEETS.find((s) => s.id === id);
  const show = force !== undefined ? force : $(id).hidden;
  closeSheets();
  if (show) {
    $(id).hidden = false;
    $(entry.btn).setAttribute("aria-expanded", "true");
    $("scrim").hidden = false;
  }
}

const togglePanel = (force) => toggleSheet("panel", force);

/* ---------------- events ---------------- */

function wireEvents() {
  // navigation
  $("closeReader").addEventListener("click", closeWithZoom);
  $("scrim").addEventListener("click", closeSheets);

  // minimize / expand the transport
  const applyTransportMode = () => {
    const min = !!store.transportMin;
    document.body.dataset.transport = min ? "min" : "full";
    $("minIcon").className = min ? "fa-regular fa-chevron-up" : "fa-regular fa-chevron-down";
    $("minToggle").setAttribute("aria-label", min ? "Expand player" : "Minimize player");
    $("minToggle").setAttribute("aria-expanded", String(!min));
  };
  applyTransportMode();
  $("minToggle").addEventListener("click", () => {
    store.transportMin = !store.transportMin;
    save();
    applyTransportMode();
  });
  // Collapsed bar: the whole strip is a tap target for "expand" — thumbs miss
  // a 34px chevron. Real controls (play, scrubber) keep their own behavior.
  $("transport").addEventListener("click", (e) => {
    if (!store.transportMin) return;
    if (e.target.closest("button, .sc-scrub, input, a")) return;
    store.transportMin = false;
    save();
    applyTransportMode();
  });
  $("continueBtn").addEventListener("click", () => openWithZoom(store.lastBook, $("continueCover"), { autoplay: true }));

  // transport
  $("playPause").addEventListener("click", () => (playing ? pause() : play()));
  $("skipBack").addEventListener("click", () => seekTo(globalMs() - SKIP_MS));
  $("skipFwd").addEventListener("click", () => seekTo(globalMs() + SKIP_MS));
  $("addBookmark").addEventListener("click", addBookmark);
  $("speed").addEventListener("click", () => {
    const next = SPEEDS[(SPEEDS.indexOf(store.speed) + 1) % SPEEDS.length];
    store.speed = next;
    audio.playbackRate = next;
    $("speed").textContent = speedLabel(next);
    save();
  });

  // theme (home bar quick toggle + appearance sheet)
  $("themeToggle").addEventListener("click", () => applyTheme(document.documentElement.dataset.mode === "dark" ? "light" : "dark"));
  $("themeLight").addEventListener("click", () => applyTheme("light"));
  $("themeDark").addEventListener("click", () => applyTheme("dark"));
  $("themeSystem").addEventListener("click", () => applyTheme(null));

  // text settings
  $("sizeDown").addEventListener("click", () => { store.appearance.size = Math.max(0, store.appearance.size - 1); applyAppearance(); });
  $("sizeUp").addEventListener("click", () => { store.appearance.size = Math.min(MAX_TEXT_SIZE, store.appearance.size + 1); applyAppearance(); });
  $("styleSerif").addEventListener("click", () => { store.appearance.font = "serif"; applyAppearance(); });
  $("styleSans").addEventListener("click", () => { store.appearance.font = "sans"; applyAppearance(); });
  $("styleLegible").addEventListener("click", () => { store.appearance.font = "legible"; applyAppearance(); });
  $("spaceRegular").addEventListener("click", () => { store.appearance.space = "regular"; applyAppearance(); });
  $("spaceRelaxed").addEventListener("click", () => { store.appearance.space = "relaxed"; applyAppearance(); });
  $("spaceLoose").addEventListener("click", () => { store.appearance.space = "loose"; applyAppearance(); });

  // sheets
  $("notesBtn").addEventListener("click", () => toggleSheet("panel"));
  $("textBtn").addEventListener("click", () => toggleSheet("textSheet"));
  $("appearanceBtn").addEventListener("click", () => toggleSheet("appearanceSheet"));
  $("voiceBtn").addEventListener("click", async () => {
    const n = bookState(current).chapter;
    await Promise.all(VOICE_OPTIONS.map((v) => getManifest(current, v.id, n)));
    renderVoiceSheet();
    toggleSheet("voiceSheet");
  });
  $("chaptersBtn").addEventListener("click", () => { renderChapters(); toggleSheet("chaptersSheet"); });
  document.querySelectorAll("[data-close-sheet], #panelClose").forEach((b) => b.addEventListener("click", closeSheets));
  document.querySelectorAll(".sc-panel-tab").forEach((t) => t.addEventListener("click", () => selectTab(t.dataset.tab)));

  // swipe-to-close on every sheet handle
  document.querySelectorAll(".sc-sheet").forEach((sheet) => {
    const handle = sheet.querySelector(".sc-sheet-handle");
    if (!handle) return;
    let dragStartY = null, dragDy = 0;
    handle.addEventListener("pointerdown", (e) => {
      if (!matchMedia("(max-width: 1023px)").matches) return;
      dragStartY = e.clientY;
      dragDy = 0;
      sheet.classList.add("dragging");
      handle.setPointerCapture(e.pointerId);
    });
    handle.addEventListener("pointermove", (e) => {
      if (dragStartY === null) return;
      dragDy = Math.max(0, e.clientY - dragStartY);
      sheet.style.transform = `translateY(${dragDy}px)`;
    });
    const endDrag = () => {
      if (dragStartY === null) return;
      sheet.classList.remove("dragging");
      sheet.style.transform = "";
      if (dragDy > 90) closeSheets();
      dragStartY = null;
    };
    handle.addEventListener("pointerup", endDrag);
    handle.addEventListener("pointercancel", endDrag);
  });

  // scrub
  const scrub = $("scrub");
  const scrubToEvent = (e) => {
    const m = man();
    if (!m) return;
    const r = scrub.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    seekTo(frac * m.totalMs);
  };
  scrub.addEventListener("pointerdown", (e) => {
    scrub.setPointerCapture(e.pointerId);
    scrubToEvent(e);
    const move = (ev) => scrubToEvent(ev);
    const up = () => { scrub.removeEventListener("pointermove", move); scrub.removeEventListener("pointerup", up); };
    scrub.addEventListener("pointermove", move);
    scrub.addEventListener("pointerup", up);
  });
  scrub.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight") { e.preventDefault(); seekTo(globalMs() + 5000); }
    if (e.key === "ArrowLeft") { e.preventDefault(); seekTo(globalMs() - 5000); }
  });

  // text interactions
  $("page").addEventListener("click", (e) => {
    if (e.target.id === "excerptNext") {
      const chs = books.get(current).book.chapters;
      const i = chs.findIndex((c) => c.n === bookState(current).chapter);
      const nx = chs.slice(i + 1).find((c) => !c.bib);
      if (i >= 0 && nx) {
        userScrolledAt = 0;
        openBook(current, { chapter: nx.n, autoplay: true });
      }
      return;
    }
    if (window.getSelection() && !window.getSelection().isCollapsed) return;
    const w = e.target.closest(".sc-w");
    if (w) jumpToWord(+w.dataset.p, +w.dataset.w);
  });
  const trySelection = () => {
    setTimeout(() => {
      const info = wordRangeFromSelection();
      if (!info) return;
      const rect = window.getSelection().getRangeAt(0).getBoundingClientRect();
      openPopover(info, rect);
    }, 0);
  };
  $("page").addEventListener("mouseup", trySelection);
  $("page").addEventListener("touchend", trySelection);
  // Any scroll not caused by autoScroll (wheel, trackpad, scrollbar drag,
  // touch) counts as manual browsing; our own scrolls are time-flagged.
  $("page").addEventListener("scroll", () => {
    if (document.hidden) return; // no human scrolls a hidden tab; timing there is unreliable
    if (Date.now() > progScrollUntil) userScrolledAt = Date.now();
  }, { passive: true });

  $("popSave").addEventListener("click", saveHighlight);
  $("popCancel").addEventListener("click", closePopover);
  document.addEventListener("pointerdown", (e) => {
    if (!$("pop").hidden && !e.target.closest("#pop") && !e.target.closest(".sc-para")) closePopover();
    if (!e.target.closest(".sc-sheet") && !e.target.closest(".sc-menu-btn")) closeSheets();
  });

  // category dialog
  $("addCategory").addEventListener("click", () => openCatDialog(null));
  $("catCancel").addEventListener("click", () => $("catDialog").close());
  $("catSave").addEventListener("click", () => {
    const name = $("catName").value.trim();
    if (!name) return $("catName").focus();
    if (editingCatId) {
      const c = catById(editingCatId);
      c.name = name;
      c.color = dialogColor;
    } else {
      store.categories.push({ id: "c" + Date.now(), name, color: dialogColor });
    }
    save();
    $("catDialog").close();
    renderCategories();
    renderPopCats();
    applyHighlights();
    renderNotes();
  });

  // keyboard
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, textarea, [contenteditable]")) return;
    if (document.body.dataset.view !== "reader") return;
    if (e.code === "Space") { e.preventDefault(); playing ? pause() : play(); }
    if (e.key === "ArrowRight") seekTo(globalMs() + SKIP_MS);
    if (e.key === "ArrowLeft") seekTo(globalMs() - SKIP_MS);
    if (e.key === "Escape") { closePopover(); closeSheets(); }
  });
}
