/* Playlists — cross-book chapter queues.
   Classic script loaded after app.js; shares its global scope (store, save,
   books, SLUGS, openBook, showReader, getManifest, mediaUrl, esc, fmt, $).
   Playlists live in their OWN localStorage key (and, in Phase 3, their own
   Supabase table): they become shared objects, so they must never ride the
   last-writer-wins user_state blob. */

/* ---------------- data ---------------- */

const PL_KEY = "schaudio:playlists:v1";
const PL_TITLE_MAX = 60;
const PL_DESC_MAX = 240;

const plStore = (() => {
  try { return JSON.parse(localStorage.getItem(PL_KEY)) || { playlists: [] }; }
  catch { return { playlists: [] }; }
})();

function plSave() {
  localStorage.setItem(PL_KEY, JSON.stringify(plStore));
}

const plById = (id) => plStore.playlists.find((p) => p.id === id);

function plCreate(title, description) {
  const pl = {
    id: crypto.randomUUID(),
    title: title.slice(0, PL_TITLE_MAX),
    description: (description || "").slice(0, PL_DESC_MAX),
    items: [],
    ownerId: null,
    shareToken: null,
    shareNotes: true,
    role: "owner",
    updatedAt: Date.now(),
  };
  plStore.playlists.push(pl);
  plSave();
  return pl;
}

function plUpdate(id, patch) {
  const pl = plById(id);
  if (!pl) return null;
  Object.assign(pl, patch, { updatedAt: Date.now() });
  plSave();
  return pl;
}

function plDelete(id) {
  const i = plStore.playlists.findIndex((p) => p.id === id);
  if (i < 0) return;
  plStore.playlists.splice(i, 1);
  delete store.playlistPos[id];
  plSave();
  save();
}

// Duration estimate for a set of items, same 151-wpm heuristic the chapter
// list uses when no manifest is cached.
function plEstimateMs(items) {
  let words = 0;
  for (const { slug, n } of items) {
    const ch = books.get(slug)?.book.chapters.find((c) => c.n === n);
    if (ch) words += ch.words;
  }
  return (words / 151) * 60000;
}

const plChapter = (slug, n) => books.get(slug)?.book.chapters.find((c) => c.n === n);

/* ---------------- queue driver ---------------- */

let playQueue = null; // { playlistId, items: [{slug, n}], idx } — null = book mode

function clearQueue() {
  playQueue = null;
  const eyebrow = $("plContext");
  if (eyebrow) eyebrow.hidden = true;
}

function playPlaylistItem(plId, i, { autoplay = false } = {}) {
  const pl = plById(plId);
  if (!pl || !pl.items.length) return;
  i = Math.max(0, Math.min(i, pl.items.length - 1));
  const { slug, n } = pl.items[i];
  if (!plChapter(slug, n)) return; // vanished chapter: row is disabled anyway
  playQueue = { playlistId: plId, items: pl.items.slice(), idx: i };
  store.playlistPos[plId] = i;
  save();
  showReader(slug, { chapter: n, autoplay, fromPlaylist: true });
  const eyebrow = $("plContext");
  if (eyebrow) { eyebrow.textContent = pl.title; eyebrow.hidden = false; }
}

async function queueAdvance(dir, { auto = false } = {}) {
  if (!playQueue) return;
  for (let i = playQueue.idx + dir; i >= 0 && i < playQueue.items.length; i += dir) {
    const { slug, n } = playQueue.items[i];
    const ch = plChapter(slug, n);
    if (!ch || ch.bib) continue;
    for (const v of [store.voice, ...VOICE_OPTIONS.map((o) => o.id)]) {
      if (await getManifest(slug, v, n)) {
        playQueue.idx = i;
        store.playlistPos[playQueue.playlistId] = i;
        save();
        if (auto) chState(slug, n).positionMs = 0; // fresh chapter starts at 0
        userScrolledAt = 0;
        return openBook(slug, { chapter: n, autoplay: true, fromPlaylist: true });
      }
    }
  }
  pause(); // end of queue
}

/* ---------------- top tabs + list view ---------------- */

function selectTopTab(tab, { setHash = true } = {}) {
  for (const b of document.querySelectorAll(".sc-toptab")) {
    b.setAttribute("aria-selected", String(b.dataset.toptab === tab));
  }
  $("homeBooksPane").hidden = tab !== "books";
  $("homePlaylistsPane").hidden = tab !== "playlists";
  if (tab === "playlists") renderPlaylists();
  if (setHash) {
    const want = tab === "playlists" ? "#/playlists" : "";
    if (location.hash !== want) history.replaceState(null, "", location.pathname + location.search + want);
  }
}

function renderPlaylists() {
  const host = $("playlistList");
  host.replaceChildren();
  if (!plStore.playlists.length) {
    const empty = document.createElement("div");
    empty.className = "sc-pl-empty";
    empty.innerHTML = `
      <i class="fa-regular fa-list-music" aria-hidden="true"></i>
      <p class="sc-pl-empty-title">No playlists yet</p>
      <p class="sc-pl-empty-sub">Collect chapters from any book into one queue — a study guide, a themed mix, a syllabus.</p>`;
    host.appendChild(empty);
    return;
  }
  for (const pl of plStore.playlists) {
    const est = plEstimateMs(pl.items);
    const row = document.createElement("div");
    row.className = "sc-pl-row";
    row.innerHTML = `
      <button class="sc-pl-open">
        <span class="sc-pl-meta">
          <span class="sc-pl-title">${esc(pl.title)}</span>
          ${pl.description ? `<span class="sc-pl-desc">${esc(pl.description)}</span>` : ""}
          <span class="sc-pl-sub">${pl.items.length} chapter${pl.items.length === 1 ? "" : "s"}${est ? ` · ${fmt(est)}` : ""}</span>
        </span>
        <i class="fa-regular fa-chevron-right" aria-hidden="true"></i>
      </button>`;
    row.querySelector(".sc-pl-open").addEventListener("click", () => showPlaylist(pl.id));
    host.appendChild(row);
  }
}

/* ---------------- playlist detail ---------------- */

let plCurrent = null; // playlist id shown in #viewPlaylist

function showPlaylist(id) {
  const pl = plById(id);
  if (!pl) { selectTopTab("playlists"); return showHomeView(); }
  plCurrent = id;
  pause();
  document.body.dataset.view = "playlist";
  $("viewHome").hidden = true;
  $("viewReader").hidden = true;
  $("viewPlaylist").hidden = false;
  const want = `#/playlist/${id}`;
  if (location.hash !== want) history.replaceState(null, "", location.pathname + location.search + want);
  renderPlaylistDetail();
}

function showHomeView() {
  history.replaceState(null, "", location.pathname + location.search + "#/playlists");
  showHome();
  selectTopTab("playlists", { setHash: false });
}

function renderPlaylistDetail() {
  const pl = plById(plCurrent);
  if (!pl) return showHomeView();
  $("plDetailTitle").textContent = pl.title;
  $("plDetailDesc").textContent = pl.description;
  $("plDetailDesc").hidden = !pl.description;
  const est = plEstimateMs(pl.items);
  $("plDetailSub").textContent = pl.items.length
    ? `${pl.items.length} chapter${pl.items.length === 1 ? "" : "s"}${est ? ` · ${fmt(est)}` : ""}`
    : "";

  const resumeIdx = Math.min(store.playlistPos[pl.id] ?? 0, Math.max(0, pl.items.length - 1));
  const playBtn = $("plPlay");
  playBtn.hidden = !pl.items.length;
  playBtn.querySelector("span").textContent = (store.playlistPos[pl.id] ?? 0) > 0 ? "Resume" : "Play";
  playBtn.onclick = () => playPlaylistItem(pl.id, resumeIdx, { autoplay: true });

  const host = $("plItems");
  host.replaceChildren();
  if (!pl.items.length) {
    const empty = document.createElement("div");
    empty.className = "sc-pl-empty sc-pl-empty-detail";
    empty.innerHTML = `<p class="sc-pl-empty-sub">This playlist is empty. Add chapters from any book.</p>`;
    host.appendChild(empty);
  }
  pl.items.forEach((item, i) => {
    const ch = plChapter(item.slug, item.n);
    const row = document.createElement("div");
    row.className = "sc-pl-item";
    row.dataset.idx = i;
    if (!ch) {
      row.innerHTML = `
        <span class="sc-pl-grip" aria-hidden="true"><i class="fa-regular fa-grip-dots-vertical"></i></span>
        <span class="sc-chapter-meta"><span class="sc-chapter-sub">No longer available</span></span>
        <span class="sc-pl-remove" role="button" tabindex="0" aria-label="Remove"><i class="fa-regular fa-xmark"></i></span>`;
    } else {
      const book = books.get(item.slug).book;
      const st = chState(item.slug, item.n);
      const estMs = (ch.words / 151) * 60000;
      const pct = estMs ? Math.min(100, Math.round((st.positionMs / estMs) * 100)) : 0;
      const status = pct >= 98 ? "Finished" : st.positionMs > 1000 ? `${pct}%` : "";
      const active = playQueue?.playlistId === pl.id && playQueue.idx === i;
      row.dataset.state = active ? "current" : "";
      row.innerHTML = `
        <span class="sc-pl-grip" role="button" tabindex="0" aria-label="Reorder (arrow keys)"><i class="fa-regular fa-grip-dots-vertical" aria-hidden="true"></i></span>
        <button class="sc-pl-item-main">
          <span class="sc-chapter-meta">
            <span class="sc-pl-item-book">${esc(book.title)}</span>
            <span class="sc-chapter-title">${esc(ch.title)}</span>
            <span class="sc-chapter-sub">${status ? status + " · " : ""}${fmt(estMs)}</span>
          </span>
          <i class="fa-solid ${active ? "fa-volume-high" : "fa-play"}" aria-hidden="true"></i>
        </button>
        <span class="sc-pl-remove" role="button" tabindex="0" aria-label="Remove ${esc(ch.title)}"><i class="fa-regular fa-xmark" aria-hidden="true"></i></span>`;
      row.querySelector(".sc-pl-item-main").addEventListener("click", () => playPlaylistItem(pl.id, i, { autoplay: true }));
    }
    const rm = row.querySelector(".sc-pl-remove");
    const doRemove = (e) => {
      e.stopPropagation();
      const items = pl.items.slice();
      items.splice(i, 1);
      plUpdateItemsRemapped(pl, items);
    };
    rm.addEventListener("click", doRemove);
    rm.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") doRemove(e); });
    wireDrag(row, pl);
    host.appendChild(row);
  });
}

// Update items while keeping the saved pointer (and any live queue) on the
// same chapter it was on before the edit.
function plUpdateItemsRemapped(pl, items) {
  const prev = pl.items[store.playlistPos[pl.id] ?? 0];
  plUpdate(pl.id, { items });
  const at = prev ? items.findIndex((it) => it.slug === prev.slug && it.n === prev.n) : -1;
  store.playlistPos[pl.id] = at >= 0 ? at : 0;
  save();
  if (playQueue?.playlistId === pl.id) {
    const live = playQueue.items[playQueue.idx];
    playQueue.items = items.slice();
    const li = items.findIndex((it) => it.slug === live.slug && it.n === live.n);
    if (li >= 0) playQueue.idx = li; else clearQueue();
  }
  renderPlaylistDetail();
}

/* ---------------- drag reorder ---------------- */

function wireDrag(row, pl) {
  const grip = row.querySelector(".sc-pl-grip");
  if (!grip) return;

  grip.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
    e.preventDefault();
    const i = +row.dataset.idx;
    const j = e.key === "ArrowUp" ? i - 1 : i + 1;
    if (j < 0 || j >= pl.items.length) return;
    const items = pl.items.slice();
    [items[i], items[j]] = [items[j], items[i]];
    plUpdateItemsRemapped(pl, items);
    $("plItems").children[j]?.querySelector(".sc-pl-grip")?.focus();
  });

  grip.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    grip.setPointerCapture(e.pointerId);
    const host = $("plItems");
    const rows = [...host.children];
    const startY = e.clientY;
    const from = +row.dataset.idx;
    let to = from;
    row.classList.add("dragging");

    const mids = rows.map((r) => {
      const b = r.getBoundingClientRect();
      return b.top + b.height / 2;
    });

    const onMove = (ev) => {
      const dy = ev.clientY - startY;
      row.style.transform = `translateY(${dy}px)`;
      to = from;
      const y = mids[from] + dy;
      for (let k = 0; k < mids.length; k++) {
        if (k !== from && y > mids[k]) to = k > from ? k : Math.min(to, k) === to && to === from ? k : to;
      }
      // simpler: nearest slot by midpoint
      to = mids.reduce((best, m, k) => (Math.abs(y - m) < Math.abs(y - mids[best]) ? k : best), from);
      rows.forEach((r, k) => {
        if (r === row) return;
        let shift = 0;
        if (from < to && k > from && k <= to) shift = -row.offsetHeight;
        if (from > to && k >= to && k < from) shift = row.offsetHeight;
        r.style.transform = shift ? `translateY(${shift}px)` : "";
      });
    };
    const onUp = () => {
      grip.removeEventListener("pointermove", onMove);
      grip.removeEventListener("pointerup", onUp);
      grip.removeEventListener("pointercancel", onUp);
      row.classList.remove("dragging");
      rows.forEach((r) => (r.style.transform = ""));
      if (to !== from) {
        const items = pl.items.slice();
        const [moved] = items.splice(from, 1);
        items.splice(to, 0, moved);
        plUpdateItemsRemapped(pl, items);
      }
    };
    grip.addEventListener("pointermove", onMove);
    grip.addEventListener("pointerup", onUp);
    grip.addEventListener("pointercancel", onUp);
  });
}

/* ---------------- create/edit/delete dialogs ---------------- */

let plDialogId = null; // null = creating

function openPlDialog(id = null) {
  plDialogId = id;
  const pl = id ? plById(id) : null;
  $("plDialogHeading").textContent = pl ? "Edit playlist" : "New playlist";
  $("plTitle").value = pl?.title || "";
  $("plDesc").value = pl?.description || "";
  plCounters();
  $("plDialog").showModal();
  $("plTitle").focus();
}

function plCounters() {
  $("plTitleCount").textContent = `${$("plTitle").value.length}/${PL_TITLE_MAX}`;
  $("plDescCount").textContent = `${$("plDesc").value.length}/${PL_DESC_MAX}`;
}

function savePlDialog() {
  const title = $("plTitle").value.trim();
  if (!title) { $("plTitle").focus(); return; }
  const desc = $("plDesc").value.trim();
  if (plDialogId) {
    plUpdate(plDialogId, { title: title.slice(0, PL_TITLE_MAX), description: desc.slice(0, PL_DESC_MAX) });
  } else {
    const pl = plCreate(title, desc);
    $("plDialog").close();
    showPlaylist(pl.id);
    return;
  }
  $("plDialog").close();
  if (document.body.dataset.view === "playlist") renderPlaylistDetail();
  else renderPlaylists();
}

function confirmDeletePlaylist(id) {
  const pl = plById(id);
  if (!pl) return;
  $("plDeleteName").textContent = pl.title;
  $("plDeleteDialog").showModal();
  $("plDeleteConfirm").onclick = () => {
    if (playQueue?.playlistId === id) clearQueue();
    plDelete(id);
    $("plDeleteDialog").close();
    showHomeView();
  };
}

/* ---------------- add-chapter modal ---------------- */

const previewAudio = new Audio();
let previewKey = null; // "slug:n" currently previewing
let addModalSlug = null;

function stopPreview() {
  previewAudio.pause();
  previewAudio.removeAttribute("src");
  previewKey = null;
  for (const b of document.querySelectorAll(".sc-add-preview[data-playing]")) delete b.dataset.playing;
  updatePreviewIcons();
}

function updatePreviewIcons() {
  for (const b of document.querySelectorAll(".sc-add-preview")) {
    const on = b.dataset.key === previewKey;
    b.innerHTML = `<i class="fa-${on ? "solid fa-stop" : "regular fa-headphones"}" aria-hidden="true"></i>`;
    b.setAttribute("aria-label", on ? "Stop preview" : "Preview chapter");
  }
}

async function togglePreview(slug, n) {
  const key = `${slug}:${n}`;
  if (previewKey === key) return stopPreview();
  stopPreview();
  pause(); // main player
  for (const v of [store.voice, ...VOICE_OPTIONS.map((o) => o.id)]) {
    const m = await getManifest(slug, v, n);
    if (m) {
      previewKey = key;
      previewAudio.src = mediaUrl(`books/${slug}/${m.paragraphs[0].audio}`);
      previewAudio.play().catch(() => {});
      updatePreviewIcons();
      return;
    }
  }
}
previewAudio.addEventListener("ended", stopPreview);

function setAddStep(step) {
  stopPreview();
  $("addChapterDialog").dataset.step = step;
}

function openAddModal() {
  addModalSlug = null;
  renderAddBooks();
  setAddStep("books");
  $("addChapterDialog").showModal();
}

function renderAddBooks() {
  const host = $("addBookList");
  host.replaceChildren();
  for (const slug of sortedSlugs()) {
    const { book } = books.get(slug);
    const row = document.createElement("button");
    row.className = "sc-add-book";
    row.innerHTML = `
      <img src="${mediaUrl(`books/${slug}/cover.png`)}" alt="" class="sc-add-cover">
      <span class="sc-chapter-meta">
        <span class="sc-chapter-title">${esc(book.title)}</span>
        <span class="sc-chapter-sub">${esc(book.author)}</span>
      </span>
      <i class="fa-regular fa-chevron-right" aria-hidden="true"></i>`;
    row.addEventListener("click", () => {
      addModalSlug = slug;
      renderAddChapters();
      setAddStep("chapters");
    });
    host.appendChild(row);
  }
}

function plHasItem(pl, slug, n) {
  return pl.items.some((it) => it.slug === slug && it.n === n);
}

function toggleItem(plId, slug, n) {
  const pl = plById(plId);
  const ch = plChapter(slug, n);
  if (!pl || !ch || ch.bib) return;
  if (plHasItem(pl, slug, n)) {
    plUpdateItemsRemapped(pl, pl.items.filter((it) => !(it.slug === slug && it.n === n)));
  } else {
    plUpdate(plId, { items: [...pl.items, { slug, n }] });
  }
}

function renderAddChapters() {
  const pl = plById(plCurrent);
  const { book } = books.get(addModalSlug);
  $("addChaptersBook").textContent = book.title;
  const host = $("addChapterList");
  host.replaceChildren();
  for (const ch of book.chapters.filter((c) => !c.bib)) {
    const added = plHasItem(pl, addModalSlug, ch.n);
    const row = document.createElement("div");
    row.className = "sc-add-chapter";
    row.innerHTML = `
      <span class="sc-chapter-meta">
        <span class="sc-chapter-title">${esc(ch.title)}</span>
        <span class="sc-chapter-sub">${fmt((ch.words / 151) * 60000)}</span>
      </span>
      <button class="sc-add-ctl sc-add-preview" data-key="${addModalSlug}:${ch.n}" aria-label="Preview chapter"><i class="fa-regular fa-headphones" aria-hidden="true"></i></button>
      <button class="sc-add-ctl sc-add-view" aria-label="View chapter text"><i class="fa-regular fa-file-lines" aria-hidden="true"></i></button>
      <button class="sc-add-ctl sc-add-toggle" data-added="${added}" aria-label="${added ? "Remove from playlist" : "Add to playlist"}">
        <i class="fa-${added ? "solid fa-check" : "regular fa-plus"}" aria-hidden="true"></i>
      </button>`;
    row.querySelector(".sc-add-preview").addEventListener("click", () => togglePreview(addModalSlug, ch.n));
    row.querySelector(".sc-add-view").addEventListener("click", () => openChapterPreview(ch));
    row.querySelector(".sc-add-toggle").addEventListener("click", (e) => {
      toggleItem(plCurrent, addModalSlug, ch.n);
      const nowAdded = plHasItem(plById(plCurrent), addModalSlug, ch.n);
      const btn = e.currentTarget;
      btn.dataset.added = String(nowAdded);
      btn.setAttribute("aria-label", nowAdded ? "Remove from playlist" : "Add to playlist");
      btn.innerHTML = `<i class="fa-${nowAdded ? "solid fa-check" : "regular fa-plus"}" aria-hidden="true"></i>`;
    });
    host.appendChild(row);
  }
}

let previewChapterN = null;

function openChapterPreview(ch) {
  stopPreview();
  previewChapterN = ch.n;
  $("chapterPreviewTitle").textContent = ch.title;
  const host = $("chapterPreviewText");
  host.replaceChildren();
  for (const para of ch.paragraphs) {
    const p = document.createElement("p");
    p.textContent = para;
    host.appendChild(p);
  }
  host.scrollTop = 0;
  const added = plHasItem(plById(plCurrent), addModalSlug, ch.n);
  $("chapterPreviewAdd").textContent = added ? "Added ✓" : "Add to playlist";
  setAddStep("preview");
}

/* ---------------- routing + boot ---------------- */

function route() {
  const h = location.hash;
  // Supabase's OAuth callback lands with #access_token=...; that hash belongs
  // to the auth layer, not this router.
  if (h && !h.startsWith("#/")) return;
  if (h.startsWith("#/pl/")) return openSharedLink(h.slice(5));      // Phase 3
  if (h.startsWith("#/playlist/")) return showPlaylist(h.slice(11));
  if (h === "#/playlists") { showHome(); return selectTopTab("playlists", { setHash: false }); }
  if (document.body.dataset.view === "playlist") { showHome(); selectTopTab("books", { setHash: false }); }
}

function openSharedLink(token) {
  // Phase 3 wires this to Supabase; until then, degrade gracefully.
  selectTopTab("playlists");
}

function plBoot() {
  // tabs
  for (const b of document.querySelectorAll(".sc-toptab")) {
    b.addEventListener("click", () => selectTopTab(b.dataset.toptab));
  }
  $("plNew").addEventListener("click", () => openPlDialog(null));
  $("plBack").addEventListener("click", showHomeView);
  $("plEdit").addEventListener("click", () => openPlDialog(plCurrent));
  $("plDeleteBtn").addEventListener("click", () => confirmDeletePlaylist(plCurrent));
  $("plAddChapter").addEventListener("click", openAddModal);

  // dialogs
  $("plTitle").addEventListener("input", plCounters);
  $("plDesc").addEventListener("input", plCounters);
  $("plDialogSave").addEventListener("click", savePlDialog);
  $("plDialogCancel").addEventListener("click", () => $("plDialog").close());
  $("plDeleteCancel").addEventListener("click", () => $("plDeleteDialog").close());

  // add-chapter modal
  $("addBackToBooks").addEventListener("click", () => setAddStep("books"));
  $("addClose1").addEventListener("click", () => { stopPreview(); $("addChapterDialog").close(); renderPlaylistDetail(); });
  $("addClose2").addEventListener("click", () => { stopPreview(); $("addChapterDialog").close(); renderPlaylistDetail(); });
  $("chapterPreviewBack").addEventListener("click", () => { renderAddChapters(); setAddStep("chapters"); });
  $("chapterPreviewAdd").addEventListener("click", () => {
    toggleItem(plCurrent, addModalSlug, previewChapterN);
    renderAddChapters();
    setAddStep("chapters");
  });
  $("addChapterDialog").addEventListener("close", () => { stopPreview(); if (document.body.dataset.view === "playlist") renderPlaylistDetail(); });

  addEventListener("hashchange", route);
  route();
}
