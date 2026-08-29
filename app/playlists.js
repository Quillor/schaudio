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
  localStorage.setItem(PL_KEY, JSON.stringify({
    playlists: plStore.playlists.filter((p) => p.role !== "guest"),
  }));
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
  plPush(pl);
  return pl;
}

function plUpdate(id, patch) {
  const pl = plById(id);
  if (!pl) return null;
  Object.assign(pl, patch, { updatedAt: Date.now() });
  plSave();
  plPush(pl);
  return pl;
}

function plDelete(id) {
  const i = plStore.playlists.findIndex((p) => p.id === id);
  if (i < 0) return;
  const pl = plStore.playlists[i];
  plStore.playlists.splice(i, 1);
  delete store.playlistPos[id];
  plSave();
  save();
  if (plCanSync() && pl.role === "owner") {
    sb.from("playlists").delete().eq("id", id).then(() => {});
  }
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
  // Creating playlists requires an account in production (they sync and can
  // be shared); dev has no auth, so keep creation available there.
  const canCreate = IS_DEV || (typeof sbUser !== "undefined" && !!sbUser);
  $("plNew").hidden = !canCreate;
  if (!plStore.playlists.length) {
    const empty = document.createElement("div");
    empty.className = "sc-pl-empty";
    if (canCreate) {
      empty.innerHTML = `
        <i class="fa-regular fa-list-music" aria-hidden="true"></i>
        <p class="sc-pl-empty-title">No playlists yet</p>
        <p class="sc-pl-empty-sub">Collect chapters from any book into one queue — a study guide, a themed mix, a syllabus.</p>`;
    } else {
      empty.innerHTML = `
        <i class="fa-regular fa-list-music" aria-hidden="true"></i>
        <p class="sc-pl-empty-title">Make the books your own</p>
        <p class="sc-pl-empty-sub">Sign up to build playlists that mix chapters from any book, keep them in sync
        across your devices, and share them — notes included — with anyone.</p>
        <button class="fds-button sc-pl-empty-cta" data-variant="primary" id="plPromoSignIn">Sign up with Google</button>`;
      empty.querySelector("#plPromoSignIn").addEventListener("click", (e) => startGoogleSignIn(e.currentTarget));
    }
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

function showPlaylist(id, { retried = false } = {}) {
  const pl = plById(id);
  if (!pl) {
    // At boot the router can win the race against the first server pull;
    // fetch once before concluding the playlist doesn't exist.
    if (!retried && plCanSync()) {
      plPull().then(() => showPlaylist(id, { retried: true }));
      return;
    }
    selectTopTab("playlists");
    return showHomeView();
  }
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
  const guest = pl.role === "guest";
  const canEdit = pl.role === "owner";
  $("plEdit").hidden = !canEdit;
  $("plDeleteBtn").hidden = !canEdit;
  $("plAddChapter").hidden = !canEdit;
  $("plShareBtn").hidden = guest || IS_DEV;
  $("plNotesBtn").hidden = guest ? !(pl.shareNotes && Object.keys(pl.noteCounts || {}).length) : IS_DEV;
  $("guestBanner").hidden = !guest || sessionStorage.getItem("sc-guest-banner") === "off";
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
    if (pl.role !== "owner") {
      // members and guests play, but cannot reorder or remove
      row.querySelector(".sc-pl-grip")?.remove();
      row.querySelector(".sc-pl-remove")?.remove();
      host.appendChild(row);
      return;
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

  // phase 3: share, notes, guest controls
  $("plShareBtn").addEventListener("click", openShareDialog);
  $("plNotesBtn").addEventListener("click", openNotesDialog);
  $("shareDone").addEventListener("click", () => $("plShareDialog").close());
  $("shareEnable").addEventListener("change", async (e) => {
    const pl = plById(plCurrent);
    if (e.target.checked) {
      const { data: tok, error } = await sb.rpc("share_playlist", { pl: pl.id });
      if (!error) { pl.shareToken = tok; plSave(); renderShareLink(pl); }
      else e.target.checked = false;
    } else {
      await sb.rpc("unshare_playlist", { pl: pl.id });
      pl.shareToken = null; plSave(); renderShareLink(pl);
    }
  });
  $("shareNotesToggle").addEventListener("change", (e) => {
    plUpdate(plCurrent, { shareNotes: e.target.checked });
  });
  $("shareCopy").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText($("shareLink").value); $("shareCopy").textContent = "Copied"; }
    catch { $("shareLink").select(); }
    setTimeout(() => { $("shareCopy").textContent = "Copy"; }, 1500);
  });
  $("shareMyNotes").addEventListener("change", async (e) => {
    await sb.from("playlist_members").update({ share_my_notes: e.target.checked })
      .eq("playlist_id", plCurrent).eq("user_id", sbUser.id);
  });
  $("leavePlaylist").addEventListener("click", async () => {
    await sb.from("playlist_members").delete()
      .eq("playlist_id", plCurrent).eq("user_id", sbUser.id);
    $("plShareDialog").close();
    plStore.playlists = plStore.playlists.filter((p) => p.id !== plCurrent);
    plSave();
    showHomeView();
  });
  $("plNotesClose").addEventListener("click", () => $("plNotesDialog").close());
  $("noteFilterPerson").addEventListener("change", renderPlaylistNotes);
  $("noteFilterBook").addEventListener("change", renderPlaylistNotes);
  $("notePromoCancel").addEventListener("click", () => $("notePromoDialog").close());
  $("notePromoSignIn").addEventListener("click", () => {
    $("notePromoDialog").close();
    document.getElementById("signIn")?.click() || startGoogleSignIn($("notePromoSignIn"));
  });
  $("guestSignIn").addEventListener("click", (e) => startGoogleSignIn(e.currentTarget));
  $("guestDismiss").addEventListener("click", () => {
    sessionStorage.setItem("sc-guest-banner", "off");
    $("guestBanner").hidden = true;
  });

  addEventListener("hashchange", route);
  route();
}

/* ================= Phase 3: sharing, sync, guests ================= */

const plCanSync = () => typeof sb !== "undefined" && sb && typeof sbUser !== "undefined" && sbUser && !IS_DEV;

let plPushTimers = {};
function plPush(pl) {
  if (!plCanSync() || !pl || pl.role !== "owner") return;
  clearTimeout(plPushTimers[pl.id]);
  plPushTimers[pl.id] = setTimeout(async () => {
    delete plPushTimers[pl.id];
    // NOT upsert: INSERT ... ON CONFLICT trips RLS here (the select policy is
    // a security-definer membership check, and Postgres requires it for the
    // conflict arm). Plain update-then-insert passes the same policies fine.
    const row = {
      id: pl.id,
      owner_id: sbUser.id,
      title: pl.title,
      description: pl.description,
      items: pl.items,
      share_notes: pl.shareNotes,
      updated_at: new Date(pl.updatedAt).toISOString(),
    };
    const upd = await sb.from("playlists").update(row).eq("id", pl.id).select("id");
    if (upd.error) return console.warn("playlist push failed:", upd.error.message);
    if (!upd.data.length) {
      const ins = await sb.from("playlists").insert(row);
      if (ins.error) console.warn("playlist push failed:", ins.error.message);
      else pl.ownerId = sbUser.id;
    } else {
      pl.ownerId = sbUser.id;
    }
  }, 500);
}

async function plPull() {
  if (!plCanSync()) return;
  const [rowsRes, memRes] = await Promise.all([
    sb.from("playlists").select("*"),
    sb.from("playlist_members").select("*"),
  ]);
  if (rowsRes.error) return;     // failed fetch: keep local state untouched
  const rows = rowsRes.data, memberships = memRes.data;
  if (!rows) return;
  for (const r of rows) {
    const role = r.owner_id === sbUser.id ? "owner" : "member";
    const local = plById(r.id);
    const incoming = {
      id: r.id, title: r.title, description: r.description,
      items: r.items || [], ownerId: r.owner_id,
      shareToken: r.share_token, shareNotes: r.share_notes,
      role, updatedAt: new Date(r.updated_at).getTime(),
      members: (memberships || []).filter((m) => m.playlist_id === r.id),
    };
    const dirty = !!plPushTimers[r.id];   // an edit is still waiting to upload
    if (!local) plStore.playlists.push(incoming);
    else if (role !== "owner") Object.assign(local, incoming);
    else if (!dirty && incoming.updatedAt > local.updatedAt) Object.assign(local, incoming);
    else if (incoming.updatedAt < local.updatedAt || dirty) plPush(local); // local wins: push up
  }
  // locally-created, never-synced playlists: push them up now
  for (const pl of plStore.playlists) {
    if (pl.role === "owner" && !rows.some((r) => r.id === pl.id)) plPush(pl);
  }
  // Reconcile deletions ONLY when the server demonstrably answered with the
  // caller's real data (at least one row came back). An empty response can
  // also mean an auth hiccup - RLS silently returns [] on a bad token - and
  // pruning on that wiped every synced playlist locally. Never delete on
  // empty; a truly deleted playlist disappears on the next healthy pull.
  if (rows.length > 0) {
    const keep = new Set(rows.map((r) => r.id));
    plStore.playlists = plStore.playlists.filter(
      (pl) => pl.role === "guest" || keep.has(pl.id) || (pl.role === "owner" && !pl.ownerId)
    );
  }
  plSave();
  if (document.body.dataset.view === "playlist") renderPlaylistDetail();
  else if (!$("homePlaylistsPane").hidden) renderPlaylists();
}

function plOnAuthReady() {
  if (!$("homePlaylistsPane").hidden) renderPlaylists();
  plPull();
  const h = location.hash;
  if (h.startsWith("#/pl/")) openSharedLink(h.slice(5));
}

/* ---------------- share sheet ---------------- */

async function openShareDialog() {
  const pl = plById(plCurrent);
  if (!pl || !plCanSync()) return;
  const dlg = $("plShareDialog");
  const isOwner = pl.role === "owner";
  $("shareOwnerPane").hidden = !isOwner;
  $("shareMemberPane").hidden = isOwner;

  if (isOwner) {
    $("shareEnable").checked = !!pl.shareToken;
    $("shareNotesToggle").checked = !!pl.shareNotes;
    renderShareLink(pl);
    renderMembers(pl);
  } else {
    const me = (pl.members || []).find((m) => m.user_id === sbUser.id);
    $("shareMyNotes").checked = me ? !!me.share_my_notes : true;
  }
  dlg.showModal();
}

function renderShareLink(pl) {
  const row = $("shareLinkRow");
  row.hidden = !pl.shareToken;
  if (pl.shareToken) {
    $("shareLink").value = `${location.origin}${location.pathname}#/pl/${pl.shareToken}`;
  }
}

function renderMembers(pl) {
  const host = $("shareMembers");
  host.replaceChildren();
  const others = (pl.members || []).filter((m) => m.user_id !== sbUser.id);
  $("shareMembersHead").hidden = !others.length;
  for (const m of others) {
    const row = document.createElement("div");
    row.className = "sc-member-row";
    row.innerHTML = `
      <span class="sc-member-name">${esc(m.display_name || "Member")}</span>
      <button class="fds-button" data-variant="ghost" aria-label="Remove member">Remove</button>`;
    row.querySelector("button").addEventListener("click", async () => {
      await sb.from("playlist_members").delete()
        .eq("playlist_id", pl.id).eq("user_id", m.user_id);
      pl.members = pl.members.filter((x) => x.user_id !== m.user_id);
      renderMembers(pl);
    });
    host.appendChild(row);
  }
}

/* ---------------- shared notes panel ---------------- */

let plNotesCache = [];

async function openNotesDialog() {
  const pl = plById(plCurrent);
  if (!pl) return;
  if (pl.role === "guest") return renderGuestNotes(pl);
  if (!plCanSync()) return;
  const { data } = await sb.from("playlist_notes").select("*").eq("playlist_id", pl.id);
  plNotesCache = data || [];
  // filters
  const people = $("noteFilterPerson");
  people.replaceChildren(new Option("Everyone", ""));
  const names = new Map();
  for (const m of pl.members || []) names.set(m.user_id, m.display_name || "Member");
  names.set(sbUser.id, "You");
  for (const [uid, name] of names) people.appendChild(new Option(name, uid));
  const booksSel = $("noteFilterBook");
  booksSel.replaceChildren(new Option("All books", ""));
  for (const slug of [...new Set(plNotesCache.map((n) => n.slug))]) {
    booksSel.appendChild(new Option(books.get(slug)?.book.title || slug, slug));
  }
  renderPlaylistNotes();
  $("plNotesDialog").showModal();
}

function renderPlaylistNotes() {
  const pl = plById(plCurrent);
  const person = $("noteFilterPerson").value;
  const bookF = $("noteFilterBook").value;
  const host = $("plNotesList");
  host.replaceChildren();
  const rows = plNotesCache
    .filter((n) => !person || n.user_id === person)
    .filter((n) => !bookF || n.slug === bookF)
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  if (!rows.length) {
    host.innerHTML = `<p class="sc-pl-empty-sub" style="text-align:center; padding: 24px 0">No shared notes yet.</p>`;
    return;
  }
  const names = new Map((pl.members || []).map((m) => [m.user_id, m.display_name || "Member"]));
  for (const n of rows) {
    const row = document.createElement("div");
    row.className = "sc-plnote";
    const who = n.user_id === sbUser?.id ? "You" : (names.get(n.user_id) || "Member");
    row.innerHTML = `
      <span class="sc-plnote-head">
        <span class="sc-plnote-who">${esc(who)}</span>
        <span class="sc-plnote-where">${esc(books.get(n.slug)?.book.title || n.slug)} · ch. ${n.chapter}</span>
      </span>
      <blockquote class="sc-plnote-quote" data-color="${esc(n.cat_color)}">${esc(n.quote)}</blockquote>
      ${n.note ? `<p class="sc-plnote-note">${esc(n.note)}</p>` : ""}`;
    host.appendChild(row);
  }
}

// Guests: fabricated, blurred rows only — real content never reached the client.
const FAKE_NOTES = [
  "The relationship between the reader and the text is itself a kind of dialogue that unfolds over time",
  "This connects to what we covered earlier about the working alliance and its role in outcomes",
  "Worth revisiting before the exam — the distinction here is subtle but it matters",
  "Compare this with the framing in the other chapter; the two authors disagree productively",
  "A good example of theory meeting practice in a way that changes how you listen",
];

function renderGuestNotes(pl) {
  const host = $("plNotesList");
  host.replaceChildren();
  $("noteFilterPerson").parentElement.hidden = true;
  let total = 0;
  for (const [key, count] of Object.entries(pl.noteCounts || {})) {
    const [slug, n] = key.split(":");
    for (let i = 0; i < count; i++) {
      total++;
      const row = document.createElement("div");
      row.className = "sc-plnote sc-plnote-locked";
      row.setAttribute("role", "button");
      row.setAttribute("tabindex", "0");
      row.innerHTML = `
        <span class="sc-plnote-head">
          <span class="sc-plnote-who sc-blur">Member</span>
          <span class="sc-plnote-where">${esc(books.get(slug)?.book.title || slug)} · ch. ${n}</span>
        </span>
        <blockquote class="sc-plnote-quote sc-blur">${esc(FAKE_NOTES[total % FAKE_NOTES.length])}</blockquote>
        <span class="sc-plnote-lock"><i class="fa-solid fa-lock" aria-hidden="true"></i> Shared note</span>`;
      row.addEventListener("click", showNotePromo);
      host.appendChild(row);
    }
  }
  if (!total) {
    host.innerHTML = `<p class="sc-pl-empty-sub" style="text-align:center; padding: 24px 0">No shared notes yet.</p>`;
  }
  $("plNotesDialog").showModal();
}

function showNotePromo() {
  $("plNotesDialog").close();
  $("notePromoDialog").showModal();
}

/* ---------------- note dual-write hooks (called from app.js) ---------------- */

function plNoteWritten(h) {
  if (!playQueue || !plCanSync()) return;
  const pl = plById(playQueue.playlistId);
  if (!pl || !pl.shareToken) return;
  const cat = store.categories.find((c) => c.id === h.catId);
  sb.from("playlist_notes").insert({
    playlist_id: pl.id,
    user_id: sbUser.id,
    client_id: h.id,
    slug: current,
    chapter: bookState(current).chapter,
    p: h.p, w0: h.w0, w1: h.w1,
    cat_name: cat?.name || "",
    cat_color: cat?.color || "accent",
    quote: h.quote,
    note: h.note || "",
  }).then(({ error }) => {
    if (error) console.warn("playlist note not shared:", error.message);
  });
}

function plNoteRemoved(id) {
  if (!plCanSync()) return;
  sb.from("playlist_notes").delete().eq("client_id", id).eq("user_id", sbUser.id).then(() => {});
}

/* ---------------- guest deep link ---------------- */

let plPendingToken = null;

async function openSharedLink(token) {
  if (IS_DEV) { selectTopTab("playlists"); return; }
  if (typeof sb === "undefined" || !sb) { plPendingToken = token; return; }
  if (typeof sbUser !== "undefined" && sbUser) {
    // signed in: prove the token, become a member
    const { data: plId, error } = await sb.rpc("join_playlist", { tok: token });
    if (error) { selectTopTab("playlists"); return; }
    await plPull();
    return showPlaylist(plId);
  }
  // guest: listen-safe payload only
  const { data, error } = await sb.rpc("get_shared_playlist", { tok: token });
  if (error || !data) { selectTopTab("playlists"); return; }
  const existing = plById(data.id);
  if (existing) Object.assign(existing, { role: "guest" });
  else plStore.playlists.push({
    id: data.id, title: data.title, description: data.description,
    items: data.items || [], ownerId: null, shareToken: token,
    shareNotes: data.share_notes, noteCounts: data.note_counts || {},
    role: "guest", updatedAt: Date.now(),
  });
  showPlaylist(data.id);
}

const plIsGuest = () => {
  const pl = plCurrent && plById(plCurrent);
  return !!(pl && pl.role === "guest") || (!!playQueue && plById(playQueue.playlistId)?.role === "guest");
};
