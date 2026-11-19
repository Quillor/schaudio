/* ============================================================
   Schaudio — Quiz app.
   Lives beside the audiobook app under one shell: same appbar,
   same auth, same synced store. Quiz state is store.quiz:
     { active: <in-progress attempt|null>, attempts: [<finished>] }
   so it rides the existing user_state sync with no schema change.
   Relies on app.js globals: $, store, save, esc.
   ============================================================ */

const QUIZ_CATALOG = [
  { id: "multicultural-dev-exam-2", file: "quizzes/multicultural-dev-exam-2.json" },
];
const APP_KEY = "schaudio:app";
const quizCache = new Map(); // id -> quiz json
let quizView = { name: "list" }; // list | run | results | guide
let quizAnswered = false;

/* ---------------- state ---------------- */

function quizState() {
  const q = (store.quiz ||= {});
  if (!Array.isArray(q.attempts)) q.attempts = [];
  if (q.active === undefined) q.active = null;
  return q;
}

async function loadQuiz(id) {
  if (quizCache.has(id)) return quizCache.get(id);
  const entry = QUIZ_CATALOG.find((c) => c.id === id);
  const res = await fetch(entry.file, { cache: "no-cache" });
  const quiz = await res.json();
  quiz.byId = new Map(quiz.questions.map((q) => [q.id, q]));
  quizCache.set(id, quiz);
  return quiz;
}

function shuffle(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

const pct = (s, t) => (t ? Math.round((s / t) * 100) : 0);
const LETTERS = ["A", "B", "C", "D", "E", "F"];

function fmtDate(ts) {
  return new Date(ts).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/* ---------------- app switcher ---------------- */

const APP_LABELS = { books: "Audiobooks", quiz: "Quiz" };

function selectApp(app, { persist = true } = {}) {
  if (app !== "quiz") app = "books";
  document.body.dataset.app = app;
  for (const b of document.querySelectorAll(".sc-appswitch-item")) {
    b.setAttribute("aria-checked", String(b.dataset.app === app));
  }
  $("appSwitchLabel").textContent = APP_LABELS[app];
  if (persist) { try { localStorage.setItem(APP_KEY, app); } catch { /* private mode */ } }
  if (app === "quiz") quizRender();
}

function toggleAppMenu(force) {
  const menu = $("appSwitchMenu"), btn = $("appSwitchBtn");
  const show = force ?? menu.hidden;
  menu.hidden = !show;
  btn.setAttribute("aria-expanded", String(show));
  if (show) menu.querySelector('[aria-checked="true"]')?.focus();
}

/* ---------------- rendering ---------------- */

function quizRender() {
  if (document.body.dataset.app !== "quiz") return;
  const host = $("quizMain");
  if (!host) return;
  if (quizView.name === "run") return renderRun(host);
  if (quizView.name === "results") return renderResults(host);
  if (quizView.name === "guide") return renderGuide(host);
  if (quizView.name === "attempt") return renderAttempt(host);
  return renderList(host);
}

async function renderList(host) {
  const st = quizState();
  const quizzes = await Promise.all(QUIZ_CATALOG.map((c) => loadQuiz(c.id)));
  host.innerHTML = "";

  const head = document.createElement("div");
  head.className = "sc-library-head";
  head.innerHTML = `<h2 class="sc-home-heading">Quizzes</h2>`;
  host.appendChild(head);

  for (const quiz of quizzes) {
    const mine = st.attempts.filter((a) => a.quizId === quiz.id);
    const best = mine.reduce((m, a) => Math.max(m, pct(a.score, a.total)), 0);
    const active = st.active && st.active.quizId === quiz.id ? st.active : null;
    const answered = active ? Object.keys(active.answers).length : 0;

    const card = document.createElement("section");
    card.className = "sc-quiz-card";
    card.innerHTML = `
      <div class="sc-quiz-card-meta">
        <h3 class="sc-quiz-card-title">${esc(quiz.title)}</h3>
        <p class="sc-quiz-card-sub">${esc(quiz.subtitle)}</p>
        <p class="sc-quiz-card-stats">
          <span>${quiz.questions.length} questions</span>
          <span>${mine.length} attempt${mine.length === 1 ? "" : "s"}</span>
          ${mine.length ? `<span>Best ${best}%</span>` : ""}
        </p>
      </div>
      <div class="sc-quiz-card-actions">
        <button class="fds-button" data-variant="primary" data-act="start">
          <i class="fa-solid fa-play" aria-hidden="true"></i>
          ${active ? `Resume · ${answered}/${active.order.length}` : (mine.length ? "Retake quiz" : "Start quiz")}
        </button>
        ${active ? `<button class="fds-button" data-variant="ghost" data-act="restart">Start over</button>` : ""}
        <button class="fds-button" data-variant="secondary" data-act="guide">
          <i class="fa-regular fa-book-open" aria-hidden="true"></i> Answer guide
        </button>
      </div>`;
    card.querySelector('[data-act="start"]').addEventListener("click", () => startQuiz(quiz.id));
    card.querySelector('[data-act="restart"]')?.addEventListener("click", () => startQuiz(quiz.id, { fresh: true }));
    card.querySelector('[data-act="guide"]').addEventListener("click", () => { quizView = { name: "guide", quizId: quiz.id }; quizRender(); });
    host.appendChild(card);
  }

  // history
  const hh = document.createElement("h2");
  hh.className = "sc-home-heading";
  hh.textContent = "Score history";
  host.appendChild(hh);

  const list = st.attempts.slice().sort((a, b) => b.finishedAt - a.finishedAt);
  if (!list.length) {
    const empty = document.createElement("p");
    empty.className = "sc-quiz-empty";
    empty.textContent = "No finished quizzes yet. Your scores, and the questions you missed, will show up here.";
    host.appendChild(empty);
    return;
  }
  const ul = document.createElement("div");
  ul.className = "sc-quiz-history";
  for (const a of list) {
    const quiz = quizCache.get(a.quizId);
    const p = pct(a.score, a.total);
    const row = document.createElement("button");
    row.className = "sc-quiz-hist";
    row.innerHTML = `
      <span class="sc-quiz-hist-score" data-tier="${p >= 80 ? "good" : p >= 60 ? "ok" : "low"}">${p}%</span>
      <span class="sc-quiz-hist-meta">
        <span class="sc-quiz-hist-title">${esc(quiz ? quiz.title : a.quizId)}</span>
        <span class="sc-quiz-hist-sub">${a.score}/${a.total} correct · ${fmtDate(a.finishedAt)} · ${a.wrong.length} missed</span>
      </span>
      <i class="fa-solid fa-chevron-right sc-quiz-hist-caret" aria-hidden="true"></i>`;
    row.addEventListener("click", () => { quizView = { name: "attempt", attemptId: a.id }; quizRender(); });
    ul.appendChild(row);
  }
  host.appendChild(ul);
}

function missedList(quiz, wrong) {
  const ol = document.createElement("ol");
  ol.className = "sc-quiz-missed";
  for (const w of wrong) {
    const q = quiz.byId.get(w.qid);
    if (!q) continue;
    const li = document.createElement("li");
    li.innerHTML = `
      <p class="sc-quiz-missed-topic">Ch. ${q.chapter} · ${esc(q.topic)}</p>
      <p class="sc-quiz-missed-q">${esc(q.prompt)}</p>
      <p class="sc-quiz-missed-yours"><i class="fa-solid fa-xmark" aria-hidden="true"></i> Your answer: ${w.picked == null ? "<em>skipped</em>" : esc(q.choices[w.picked])}</p>
      <p class="sc-quiz-missed-right"><i class="fa-solid fa-check" aria-hidden="true"></i> Correct: ${esc(q.choices[q.answer])}</p>
      <p class="sc-quiz-missed-why">${esc(q.explanation)}</p>`;
    ol.appendChild(li);
  }
  return ol;
}

/* ---------------- run ---------------- */

async function startQuiz(id, { fresh = false } = {}) {
  const st = quizState();
  const quiz = await loadQuiz(id);
  if (fresh || !st.active || st.active.quizId !== id) {
    const order = shuffle(quiz.questions.map((q) => q.id));
    const choiceOrder = {};
    for (const q of quiz.questions) choiceOrder[q.id] = shuffle(q.choices.map((_, i) => i));
    st.active = { id: `a${Date.now()}`, quizId: id, startedAt: Date.now(), order, choiceOrder, answers: {} };
    save();
  }
  quizView = { name: "run" };
  quizAnswered = false;
  quizRender();
}

function activeIndex(a) {
  const i = a.order.findIndex((qid) => !(qid in a.answers));
  return i === -1 ? a.order.length : i;
}

function renderRun(host) {
  const st = quizState();
  const a = st.active;
  const quiz = a && quizCache.get(a.quizId);
  if (!a || !quiz) { quizView = { name: "list" }; return quizRender(); }

  // While feedback is showing, stay on the question just answered.
  let i = activeIndex(a);
  if (quizAnswered) i = Math.max(0, i - 1);
  if (i >= a.order.length) return finishQuiz();

  const qid = a.order[i];
  const q = quiz.byId.get(qid);
  const order = a.choiceOrder[qid];
  const picked = a.answers[qid];
  const score = Object.entries(a.answers).filter(([id, c]) => quiz.byId.get(id)?.answer === c).length;
  const done = Object.keys(a.answers).length;

  host.innerHTML = `
    <div class="sc-quiz-run">
      <div class="sc-quiz-runbar">
        <button class="fds-button" data-variant="ghost" id="quizQuit">
          <i class="fa-regular fa-arrow-left" aria-hidden="true"></i> Save &amp; exit
        </button>
        <span class="sc-quiz-count">Question ${i + 1} of ${a.order.length}</span>
        <span class="sc-quiz-tally" aria-label="${score} correct so far">${score}/${done} correct</span>
      </div>
      <span class="fds-progress sc-quiz-progress" role="progressbar" aria-valuemin="0" aria-valuemax="${a.order.length}" aria-valuenow="${done}">
        <span class="fds-progress-bar" style="inline-size:${pct(done, a.order.length)}%"></span>
      </span>
      <p class="sc-quiz-topic">Chapter ${q.chapter} · ${esc(q.topic)}</p>
      <h2 class="sc-quiz-prompt" id="quizPrompt">${esc(q.prompt)}</h2>
      <div class="sc-quiz-choices" role="group" aria-labelledby="quizPrompt">
        ${order.map((ci, k) => {
          let state = "";
          if (quizAnswered) state = ci === q.answer ? "correct" : ci === picked ? "wrong" : "dim";
          return `<button class="sc-quiz-choice" data-ci="${ci}" ${state ? `data-state="${state}"` : ""} ${quizAnswered ? "disabled" : ""}>
            <span class="sc-quiz-letter">${LETTERS[k]}</span>
            <span class="sc-quiz-choice-text">${esc(q.choices[ci])}</span>
            ${state === "correct" ? `<i class="fa-solid fa-check sc-quiz-mark" aria-label="Correct answer"></i>` : ""}
            ${state === "wrong" ? `<i class="fa-solid fa-xmark sc-quiz-mark" aria-label="Your answer"></i>` : ""}
          </button>`;
        }).join("")}
      </div>
      <div class="sc-quiz-feedback" id="quizFeedback" ${quizAnswered ? "" : "hidden"} aria-live="polite">
        ${quizAnswered ? `
          <p class="sc-quiz-verdict" data-ok="${picked === q.answer}">
            ${picked === q.answer ? "Correct" : "Not quite"}
          </p>
          <p class="sc-quiz-why"><strong>Answer guide:</strong> ${esc(q.explanation)}</p>
          <button class="fds-button" data-variant="primary" id="quizNext">
            ${i + 1 >= a.order.length ? "See results" : "Next question"} <i class="fa-regular fa-arrow-right" aria-hidden="true"></i>
          </button>` : ""}
      </div>
    </div>`;

  $("quizQuit").addEventListener("click", () => { quizView = { name: "list" }; quizAnswered = false; quizRender(); });
  host.querySelectorAll(".sc-quiz-choice").forEach((b) => b.addEventListener("click", () => answer(qid, Number(b.dataset.ci))));
  const next = $("quizNext");
  if (next) { next.addEventListener("click", nextQuestion); next.focus({ preventScroll: true }); }
  if (!quizAnswered) host.scrollTop = 0;
}

function answer(qid, ci) {
  const a = quizState().active;
  if (!a || quizAnswered || qid in a.answers) return;
  a.answers[qid] = ci;
  quizAnswered = true;
  save();
  quizRender();
}

function nextQuestion() {
  quizAnswered = false;
  quizRender();
  $("quizMain").scrollTop = 0;
}

async function finishQuiz() {
  const st = quizState();
  const a = st.active;
  const quiz = await loadQuiz(a.quizId);
  const wrong = [];
  let score = 0;
  for (const qid of a.order) {
    const q = quiz.byId.get(qid);
    const picked = a.answers[qid];
    if (picked === q.answer) score++;
    else wrong.push({ qid, picked: picked ?? null });
  }
  const rec = { id: a.id, quizId: a.quizId, startedAt: a.startedAt, finishedAt: Date.now(), score, total: a.order.length, wrong };
  st.attempts.push(rec);
  st.active = null;
  save();
  quizView = { name: "results", attemptId: rec.id };
  quizAnswered = false;
  quizRender();
}

function renderResults(host) {
  const st = quizState();
  const a = st.attempts.find((x) => x.id === quizView.attemptId);
  const quiz = a && quizCache.get(a.quizId);
  if (!a || !quiz) { quizView = { name: "list" }; return quizRender(); }
  const p = pct(a.score, a.total);
  host.innerHTML = `
    <div class="sc-quiz-results">
      <p class="sc-quiz-topic">${esc(quiz.title)}</p>
      <p class="sc-quiz-bigscore" data-tier="${p >= 80 ? "good" : p >= 60 ? "ok" : "low"}">${p}%</p>
      <p class="sc-quiz-results-sub">${a.score} of ${a.total} correct · ${a.wrong.length} to review</p>
      <div class="sc-quiz-card-actions">
        <button class="fds-button" data-variant="primary" id="quizRetake"><i class="fa-regular fa-rotate-right" aria-hidden="true"></i> Retake</button>
        <button class="fds-button" data-variant="secondary" id="quizDone">Back to quizzes</button>
      </div>
      ${a.wrong.length ? `<h2 class="sc-home-heading">What you missed</h2>` : `<p class="sc-quiz-empty">Perfect score — nothing to review.</p>`}
    </div>`;
  if (a.wrong.length) host.querySelector(".sc-quiz-results").appendChild(missedList(quiz, a.wrong));
  $("quizRetake").addEventListener("click", () => startQuiz(a.quizId, { fresh: true }));
  $("quizDone").addEventListener("click", () => { quizView = { name: "list" }; quizRender(); });
  host.scrollTop = 0;
}

function renderAttempt(host) {
  const a = quizState().attempts.find((x) => x.id === quizView.attemptId);
  const quiz = a && quizCache.get(a.quizId);
  if (!a || !quiz) { quizView = { name: "list" }; return quizRender(); }
  const p = pct(a.score, a.total);
  host.innerHTML = `
    <div class="sc-quiz-results">
      <button class="fds-button" data-variant="ghost" id="attemptBack"><i class="fa-regular fa-arrow-left" aria-hidden="true"></i> Score history</button>
      <p class="sc-quiz-topic sc-quiz-attempt-eyebrow">${esc(quiz.title)} · ${fmtDate(a.finishedAt)}</p>
      <p class="sc-quiz-bigscore" data-tier="${p >= 80 ? "good" : p >= 60 ? "ok" : "low"}">${p}%</p>
      <p class="sc-quiz-results-sub">${a.score} of ${a.total} correct · ${a.wrong.length} missed</p>
      ${a.wrong.length ? `<h2 class="sc-home-heading">What you missed</h2>` : `<p class="sc-quiz-empty">Perfect score — nothing missed.</p>`}
    </div>`;
  if (a.wrong.length) host.querySelector(".sc-quiz-results").appendChild(missedList(quiz, a.wrong));
  $("attemptBack").addEventListener("click", () => { quizView = { name: "list" }; quizRender(); });
  host.scrollTop = 0;
}

/* ---------------- answer guide ---------------- */

async function renderGuide(host) {
  const quiz = await loadQuiz(quizView.quizId);
  const byCh = new Map();
  for (const q of quiz.questions) {
    if (!byCh.has(q.chapter)) byCh.set(q.chapter, []);
    byCh.get(q.chapter).push(q);
  }
  let n = 0;
  host.innerHTML = `
    <div class="sc-quiz-guide">
      <button class="fds-button" data-variant="ghost" id="guideBack"><i class="fa-regular fa-arrow-left" aria-hidden="true"></i> Quizzes</button>
      <h2 class="sc-home-heading">Answer guide</h2>
      <p class="sc-quiz-card-sub">${esc(quiz.title)} · ${quiz.questions.length} questions, drawn only from the study guide.</p>
      ${[...byCh.entries()].map(([ch, qs]) => `
        <h3 class="sc-quiz-guide-ch">Chapter ${ch}</h3>
        <ol class="sc-quiz-guide-list" start="${n + 1}">
          ${qs.map((q) => { n++; return `
            <li>
              <p class="sc-quiz-missed-topic">${esc(q.topic)}</p>
              <p class="sc-quiz-missed-q">${esc(q.prompt)}</p>
              <ul class="sc-quiz-guide-choices">
                ${q.choices.map((c, ci) => `<li ${ci === q.answer ? 'data-correct="true"' : ""}>${ci === q.answer ? '<i class="fa-solid fa-check" aria-label="Correct"></i> ' : ""}${esc(c)}</li>`).join("")}
              </ul>
              <p class="sc-quiz-missed-why">${esc(q.explanation)}</p>
            </li>`; }).join("")}
        </ol>`).join("")}
    </div>`;
  $("guideBack").addEventListener("click", () => { quizView = { name: "list" }; quizRender(); });
  host.scrollTop = 0;
}

/* ---------------- keyboard ---------------- */

document.addEventListener("keydown", (e) => {
  if (document.body.dataset.app !== "quiz" || document.body.dataset.view !== "home") return;
  if (quizView.name !== "run" || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.target.closest("input, textarea, select")) return;
  if (quizAnswered && e.key === "Enter" && e.target.id !== "quizNext") { e.preventDefault(); nextQuestion(); return; }
  if (quizAnswered) return;
  const k = e.key.toUpperCase();
  const idx = /^[1-4]$/.test(k) ? Number(k) - 1 : LETTERS.indexOf(k);
  if (idx < 0 || idx > 3) return;
  const btn = document.querySelectorAll(".sc-quiz-choice")[idx];
  if (btn) { e.preventDefault(); btn.click(); }
});

/* ---------------- boot ---------------- */

(function quizBoot() {
  $("appSwitchBtn").addEventListener("click", () => toggleAppMenu());
  for (const b of document.querySelectorAll(".sc-appswitch-item")) {
    b.addEventListener("click", () => { selectApp(b.dataset.app); toggleAppMenu(false); $("appSwitchBtn").focus(); });
  }
  document.addEventListener("pointerdown", (e) => {
    if (!$("appSwitchMenu").hidden && !e.target.closest(".sc-appswitch")) toggleAppMenu(false);
  });
  $("appSwitchMenu").addEventListener("keydown", (e) => {
    const items = [...document.querySelectorAll(".sc-appswitch-item")];
    const i = items.indexOf(document.activeElement);
    if (e.key === "Escape") { e.preventDefault(); toggleAppMenu(false); $("appSwitchBtn").focus(); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length].focus();
    } else if (e.key === "Tab") toggleAppMenu(false);
  });
  let app = "books";
  try { app = localStorage.getItem(APP_KEY) || "books"; } catch { /* private mode */ }
  selectApp(app, { persist: false });
})();
