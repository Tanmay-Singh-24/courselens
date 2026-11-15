// CourseLens — frontend. Plain ES modules, no build step.
import { CourseMap } from "./map.js";
import { startField } from "./field.js";

const $ = (sel, el = document) => el.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pretty = (s) => String(s ?? "").replace(/_/g, " ");
const fmtTime = (sec) => {
  const s = Math.floor(sec || 0), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`;
};

// Source colours: assigned from the sorted library so a source keeps its colour
// everywhere (library dot, citation chip, map cluster).
// Bright on black, after the Obsidian-style graph: yellow, lavender, pink, mint…
const PALETTE = ["#f4ee4c", "#8e8cf7", "#e27cc3", "#5fd0c5", "#ff9450", "#b9d98a", "#6f8bff", "#ff6b6b"];
let sourceOrder = [];
function colorFor(name) {
  let i = sourceOrder.indexOf(name);
  if (i < 0) { sourceOrder.push(name); i = sourceOrder.length - 1; }
  return PALETTE[i % PALETTE.length];
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON error */ }
  if (!res.ok) {
    const d = body?.detail;
    throw new Error(typeof d === "string" ? d : `Request failed (${res.status}).`);
  }
  return body;
}

const threadId = sessionStorage.getItem("cl-thread") || crypto.randomUUID();
sessionStorage.setItem("cl-thread", threadId);

// ── status + library ─────────────────────────────────────────────────────────
const TYPE_LABEL = { audio: "Audio", youtube: "YouTube", pdf_text: "Slides", pdf_figure: "Figures" };

async function loadHealth() {
  const el = $("#status");
  try {
    const h = await api("/api/health");
    el.className = "status ok";
    $(".status-text", el).textContent = "live";
    $("#build").textContent = `build ${h.build}`;
    $("#ytForm").hidden = !h.youtube;
  } catch {
    el.className = "status bad";
    $(".status-text", el).textContent = "offline";
  }
}

async function loadLibrary() {
  const ul = $("#sources");
  try {
    const { sources } = await api("/api/library");
    sourceOrder = sources.map((s) => s.name);
    if (!sources.length) { ul.innerHTML = `<li class="muted">Nothing yet. Add a lecture above.</li>`; return; }
    ul.innerHTML = sources.map((s) => {
      const kinds = [...new Set(s.types.map((t) => TYPE_LABEL[t] || t))].join(" · ");
      return `<li class="source" title="${esc(s.name)}">
        <span class="swatch" style="background:${colorFor(s.name)}"></span>
        <span class="nm">${esc(pretty(s.name))}</span><span class="meta">${esc(kinds)}</span></li>`;
    }).join("");
  } catch (e) {
    ul.innerHTML = `<li class="muted">${esc(e.message)}</li>`;
  }
}

// ── uploads ──────────────────────────────────────────────────────────────────
let mapStale = true;

function uploadRow(name, msg) {
  const li = document.createElement("li");
  li.className = "upload busy";
  li.innerHTML = `<span class="name">${esc(name)}</span><span class="msg">${esc(msg)}</span>`;
  $("#uploads").prepend(li);
  return {
    done(text, ok = true) {
      li.className = `upload ${ok ? "" : "err"}`;
      $(".msg", li).textContent = text;
      if (ok) setTimeout(() => li.remove(), 12000);
    },
  };
}

function resultText(r) {
  if (r.duplicate) return "Already in your library.";
  const base = r.chunks ? `Added ${r.chunks} passage${r.chunks === 1 ? "" : "s"}.` : "Nothing readable was found.";
  return [base, ...(r.warnings || [])].join(" ");
}

async function uploadFiles(files) {
  for (const f of files) {
    const isPdf = f.name.toLowerCase().endsWith(".pdf");
    const row = uploadRow(f.name, isPdf ? "Reading text, then describing figures…" : "Transcribing audio…");
    const fd = new FormData();
    fd.append("file", f);
    try {
      row.done(resultText(await api("/api/ingest", { method: "POST", body: fd })));
      mapStale = true;
    } catch (e) {
      row.done(e.message, false);
    }
  }
  loadLibrary();
}

const dz = $("#dropzone");
$("#fileInput").addEventListener("change", (e) => { uploadFiles([...e.target.files]); e.target.value = ""; });
["dragenter", "dragover"].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
dz.addEventListener("drop", (e) => uploadFiles([...e.dataTransfer.files]));

$("#ytForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = $("#ytUrl").value.trim();
  if (!url) return;
  const row = uploadRow("YouTube video", "Downloading and transcribing…");
  try {
    row.done(resultText(await api("/api/ingest/youtube", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }),
    })));
    $("#ytUrl").value = "";
    mapStale = true;
    loadLibrary();
  } catch (err) { row.done(err.message, false); }
});

// ── media: one audio player + a figure lightbox ──────────────────────────────
const audio = $("#audio");
function setPlayerOpen(open) {
  $("#player").hidden = !open;
  // Reserve room at the bottom so the player never covers the composer or map.
  document.body.classList.toggle("has-player", open);
}
function playAudio(url, t, label) {
  setPlayerOpen(true);
  $("#playerLabel").textContent = label;
  const abs = new URL(url, location.href).href;
  const seek = () => { audio.currentTime = t || 0; audio.play().catch(() => {}); };
  if (audio.src !== abs) {
    audio.src = abs;
    audio.addEventListener("loadedmetadata", seek, { once: true });
    audio.load();
  } else seek();
}
$("#playerClose").addEventListener("click", () => { audio.pause(); setPlayerOpen(false); });

function showFigure(url, caption) {
  $("#lightboxImg").src = url;
  $("#lightboxImg").alt = caption;
  $("#lightboxCap").textContent = caption;
  $("#lightbox").hidden = false;
}
$("#lightbox").addEventListener("click", () => { $("#lightbox").hidden = true; });

function openSource(s) {
  if (s.source_type === "audio" && s.media_url) playAudio(s.media_url, s.ts_start, pretty(s.label));
  else if (s.source_type === "youtube" && s.youtube_url) window.open(`${s.youtube_url}&t=${Math.floor(s.ts_start || 0)}s`, "_blank", "noopener");
  else if (s.source_type === "pdf_figure" && s.media_url) showFigure(s.media_url, pretty(s.label));
}

function sourceAction(s) {
  if (s.source_type === "audio") return s.media_url ? `Play from ${fmtTime(s.ts_start)}` : "Audio unavailable";
  if (s.source_type === "youtube") return `Watch from ${fmtTime(s.ts_start)}`;
  if (s.source_type === "pdf_figure") return s.media_url ? `Figure, page ${s.page}` : `Figure, page ${s.page} (image unavailable)`;
  return `Page ${s.page ?? "?"}`;
}

function sourceCard(s) {
  const openable = (s.source_type === "audio" || s.source_type === "pdf_figure") ? !!s.media_url : s.source_type === "youtube";
  const el = document.createElement(openable ? "button" : "div");
  el.className = "card spot";
  const col = colorFor(s.source_name);
  const glyph = { audio: "♪", youtube: "▶", pdf_text: "¶" }[s.source_type] || "◆";
  const visual = s.source_type === "pdf_figure" && s.media_url
    ? `<img src="${esc(s.media_url)}" alt="" loading="lazy" />`
    : `<span class="ico" style="background:${col}">${glyph}</span>`;
  el.innerHTML = `${visual}<span class="t"><b>${esc(pretty(s.source_name))}</b><small>${esc(sourceAction(s))}</small></span>`;
  if (openable) el.addEventListener("click", () => openSource(s));
  return el;
}

// ── answers ──────────────────────────────────────────────────────────────────
// Light markdown: paragraphs, lists, bold, and [citation] chips that open the source.
function citeChips(inner, sources) {
  const parts = inner.split(/;\s*|,\s+(?=[A-Za-z0-9_ ]+(?:@| p\.| —))/);
  const found = parts.map((p) => {
    const t = p.trim();
    let i = sources.findIndex((s) => esc(s.label) === t);
    if (i < 0) i = sources.findIndex((s) => t.includes(esc(s.source_name)));
    return i;
  });
  if (found.some((i) => i < 0)) return null;
  return found.map((i) => {
    const s = sources[i];
    return `<button class="cite" data-src="${i}" title="${esc(sourceAction(s))}"><i style="background:${colorFor(s.source_name)}"></i>${esc(pretty(s.label))}</button>`;
  }).join(" ");
}

function inline(s, sources) {
  return s
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    // Models differ in bracket style: llama wrote [label], gpt-oss writes 【label】.
    .replace(/[\[【]([^\[\]【】]{2,160})[\]】]/g, (m, inner) => citeChips(inner, sources) ?? m);
}

// gpt-oss sometimes writes inline LaTeX ("\(O(E \log V)\)"). We don't ship a math
// renderer for one-liners like that; unwrap it into readable plain text.
function plainMath(text) {
  const sym = { log: "log", cdot: "·", times: "×", le: "≤", leq: "≤", ge: "≥", geq: "≥", to: "→", infty: "∞", approx: "≈", neq: "≠", ldots: "…", sqrt: "√" };
  return text
    .replace(/\\\(|\\\)|\\\[|\\\]/g, "")
    .replace(/\\([a-zA-Z]+)/g, (m, w) => sym[w] ?? w)
    .replace(/\{([^{}]*)\}/g, "$1");
}

function renderMarkdown(text, sources) {
  let html = "", list = null;
  for (const raw of esc(plainMath(text)).split("\n")) {
    const line = raw.trim();
    const li = line.match(/^(?:[-*•]|\d+[.)])\s+(.*)/);
    if (li) {
      const tag = /^\d/.test(line) ? "ol" : "ul";
      if (list !== tag) { if (list) html += `</${list}>`; html += `<${tag}>`; list = tag; }
      html += `<li>${inline(li[1], sources)}</li>`;
      continue;
    }
    if (list) { html += `</${list}>`; list = null; }
    if (line) html += `<p>${inline(line, sources)}</p>`;
  }
  return list ? html + `</${list}>` : html;
}

function traceBlock(r) {
  if (!r.verdicts?.length) return "";
  const last = r.verdicts[r.verdicts.length - 1];
  const items = r.verdicts.map((v) =>
    `<li><span class="pill ${v.relevant ? "yes" : "no"}">${v.relevant ? "relevant" : "not relevant"}</span> ${esc(v.reason)}</li>`).join("");
  return `<details class="trace"><summary><span>Checked its sources ${r.verdicts.length}×</span>
    <span class="pill ${last.relevant ? "yes" : "no"}">${last.relevant ? "grounded" : "refused"}</span>
    <span>${r.latency_s}s · ${r.total_tokens} tokens</span></summary><ol>${items}</ol></details>`;
}

const thread = $("#thread");
const STAGES = ["Searching your course…", "Checking the sources actually answer it…", "Writing the answer…"];

function addMessage(cls, html) {
  const div = document.createElement("div");
  div.className = `msg ${cls}`;
  div.innerHTML = html;
  thread.appendChild(div);
  div.scrollIntoView({ behavior: "smooth", block: "end" });
  return div;
}

let asking = false;
async function ask(question) {
  question = question.trim();
  if (!question || asking) return;
  asking = true;
  $("#send").disabled = true;
  $("#welcome")?.remove();
  addMessage("msg-user", `<div class="bubble">${esc(question)}</div>`);
  const bot = addMessage("msg-bot", `<div class="thinking"><span class="dots"><span></span><span></span><span></span></span><span class="stage">${STAGES[0]}</span></div>`);
  let stage = 0;
  const timer = setInterval(() => {
    stage = Math.min(stage + 1, STAGES.length - 1);
    const el = $(".stage", bot);
    if (el) el.textContent = STAGES[stage];
  }, 1800);
  try {
    const r = await api("/api/ask", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, thread_id: threadId }),
    });
    bot.innerHTML = `<div class="answer">${renderMarkdown(r.answer, r.sources)}</div>`;
    bot.querySelectorAll(".cite").forEach((b) => b.addEventListener("click", () => openSource(r.sources[+b.dataset.src])));
    if (r.sources.length) {
      const cards = document.createElement("div");
      cards.className = "cards";
      r.sources.forEach((s) => cards.appendChild(sourceCard(s)));
      bot.appendChild(cards);
    }
    bot.insertAdjacentHTML("beforeend", traceBlock(r));
  } catch (e) {
    bot.innerHTML = `<div class="answer error"><p>${esc(e.message)}</p></div>`;
  } finally {
    clearInterval(timer);
    asking = false;
    $("#send").disabled = false;
    bot.scrollIntoView({ behavior: "smooth", block: "end" });
  }
}

const STARTERS = [
  ["What is the time complexity of Dijkstra's algorithm?", "audio + timestamp"],
  ["Which sorting algorithm is slowest according to the chart?", "reads a figure"],
  ["How are hash table collisions handled?", "across lectures"],
  ["What is the capital of France?", "honest refusal"],
];
$("#starters").innerHTML = STARTERS.map(([q, tag]) =>
  `<button class="starter spot" data-q="${esc(q)}"><span class="q">${esc(q)}</span><span class="tag">${esc(tag)}</span></button>`).join("");
$("#starters").addEventListener("click", (e) => { const b = e.target.closest(".starter"); if (b) ask(b.dataset.q); });

const qBox = $("#question");
const grow = () => { qBox.style.height = "auto"; qBox.style.height = Math.min(qBox.scrollHeight, 160) + "px"; };
qBox.addEventListener("input", grow);
qBox.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#composer").requestSubmit(); }
});
$("#composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = qBox.value;
  qBox.value = "";
  grow();
  ask(q);
});

// ── course map ───────────────────────────────────────────────────────────────
const panel = $("#conceptPanel");
const map = new CourseMap($("#mapCanvas"), { colorFor, onSelect: showConcept });
const isWide = () => matchMedia("(min-width: 901px)").matches;
let conceptToken = 0;

function overlay(html) {
  const o = $("#mapOverlay");
  o.hidden = !html;
  if (html) o.innerHTML = html;
}

async function loadMap() {
  overlay(`<div class="spinner"></div><p>Building your course map…</p>`);
  try {
    const data = await api("/api/course-map");
    if (!data.nodes.length) {
      overlay(`<p><strong>No map yet.</strong><br />Add a lecture or slide deck and the concepts in it will appear here, linked by meaning.</p>`);
      return;
    }
    sourceOrder = [...new Set([...sourceOrder, ...data.sources])];
    // Legend first: it can wrap the toolbar onto two rows, and the map should
    // fit itself to the final canvas size.
    $("#legend").innerHTML = data.sources.map((s) =>
      `<button class="chip" data-src="${esc(s)}" aria-pressed="true"><span class="swatch" style="background:${colorFor(s)}"></span>${esc(pretty(s))}</button>`).join("");
    overlay(null);
    map.resize();
    map.setData(data);
    mapStale = false;
    $("#conceptList").innerHTML = data.nodes.map((n) => `<option value="${esc(n.id)}"></option>`).join("");
    const bridges = data.links.filter((l) => l.kind === "bridge").length;
    $("#mapHint").textContent = `${data.nodes.length} concepts · ${data.sources.length} sources · ${bridges} bridges across sources`;
  } catch (e) {
    overlay(`<p>${esc(e.message)}</p><button class="btn-ghost" id="mapRetry">Try again</button>`);
    $("#mapRetry")?.addEventListener("click", loadMap);
  }
}

$("#legend").addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  const off = chip.classList.toggle("off");
  chip.setAttribute("aria-pressed", String(!off));
  map.setHidden(chip.dataset.src, off);
});
$("#mapReset").addEventListener("click", () => map.fit());
$("#mapSearch").addEventListener("change", (e) => findConcept(e.target.value));
$("#mapSearch").addEventListener("keydown", (e) => { if (e.key === "Enter") findConcept(e.target.value); });
function findConcept(q) {
  q = q.trim().toLowerCase();
  if (!q) return;
  const hit = map.nodes.find((n) => n.id.toLowerCase() === q) || map.nodes.find((n) => n.id.toLowerCase().includes(q));
  if (hit) map.focus(hit.id);
}

function showSource(info) {
  const name = pretty(info.source);
  const btn = (c) => `<button class="rel" data-id="${esc(c.id)}"><span class="swatch" style="background:${colorFor(c.sources[0])}"></span>${esc(c.id)}${c.sources.length > 1 ? `<span class="bridge-tag">shared</span>` : ""}</button>`;
  $("#panelBody").innerHTML = `
    <p class="eyebrow">source</p>
    <h2>${esc(name)}</h2>
    <h4>${info.concepts.length} concept${info.concepts.length === 1 ? "" : "s"} taught here</h4>
    ${info.concepts.map(btn).join("") || `<p class="muted">No concepts found.</p>`}
    <button class="btn-primary" id="askConcept">Summarise ${esc(name)}</button>`;
  $("#panelBody").querySelectorAll(".rel").forEach((b) => b.addEventListener("click", () => map.focus(b.dataset.id)));
  $("#askConcept").addEventListener("click", () => {
    switchView("ask");
    ask(`Summarise the main ideas in ${name}.`);
  });
}

async function showConcept(info) {
  const token = ++conceptToken;
  if (!info) { panel.hidden = true; map.setInset(0); return; }
  panel.hidden = false;
  // Desktop: side panel on the right. Phone: bottom sheet, max 62% of the stage.
  map.setInset(isWide() ? 372 : 0, isWide() ? 0 : Math.round($("#mapCanvas").clientHeight * 0.62));
  map.ensureVisible(info.id);
  if (info.hub) return showSource(info);
  const related = info.neighbors.filter((n) => n.kind !== "shared").slice(0, 6);
  const sameSource = info.neighbors.filter((n) => n.kind === "shared").slice(0, 6);
  const relBtn = (n) => `<button class="rel" data-id="${esc(n.id)}">
      <span class="swatch" style="background:${colorFor(n.sources[0])}"></span>${esc(n.id)}
      ${n.kind === "bridge" ? `<span class="bridge-tag">bridge</span>` : ""}
      ${n.kind !== "shared" ? `<span class="bar" title="similarity ${n.weight.toFixed(2)}"><b style="width:${Math.round(Math.min(1, Math.max(0.12, (n.weight - 0.25) / 0.55)) * 100)}%"></b></span>` : ""}</button>`;
  $("#panelBody").innerHTML = `
    <p class="eyebrow">${info.sources.length > 1 ? `Shared by ${info.sources.length} sources` : "Concept"}</p>
    <h2>${esc(info.id)}</h2>
    <h4>Appears in</h4>
    <div class="row">${info.sources.map((s) => `<span class="chip"><span class="swatch" style="background:${colorFor(s)}"></span>${esc(pretty(s))}</span>`).join("")}</div>
    ${related.length ? `<h4>Related ideas</h4>${related.map(relBtn).join("")}` : ""}
    ${sameSource.length ? `<h4>Taught alongside</h4>${sameSource.map(relBtn).join("")}` : ""}
    <h4>Where it comes up</h4>
    <div id="passages"><p class="muted">Finding passages…</p></div>
    <button class="btn-primary" id="askConcept">Ask CourseLens about ${esc(info.id)}</button>`;
  $("#panelBody").querySelectorAll(".rel").forEach((b) => b.addEventListener("click", () => map.focus(b.dataset.id)));
  $("#askConcept").addEventListener("click", () => {
    switchView("ask");
    ask(`Explain ${info.id} using my course materials.`);
  });
  try {
    const { passages } = await api(`/api/concept?name=${encodeURIComponent(info.id)}`);
    if (token !== conceptToken) return;
    const box = $("#passages");
    box.innerHTML = "";
    passages.forEach((p) => {
      const div = document.createElement("div");
      div.className = "passage";
      const canOpen = (p.source_type === "audio" || p.source_type === "pdf_figure") ? !!p.media_url : p.source_type === "youtube";
      const verb = { audio: "Play", youtube: "Watch", pdf_figure: "View" }[p.source_type];
      div.innerHTML = `<div class="ph"><span class="swatch" style="background:${colorFor(p.source_name)}"></span>
        ${esc(pretty(p.label))}${canOpen && verb ? `<button>${verb}</button>` : ""}</div><p>${esc(p.text)}</p>`;
      div.querySelector("button")?.addEventListener("click", () => openSource(p));
      box.appendChild(div);
    });
    if (!passages.length) box.innerHTML = `<p class="muted">No passages found.</p>`;
  } catch {
    if (token === conceptToken) $("#passages").innerHTML = `<p class="muted">Couldn't load passages.</p>`;
  }
}
$("#panelClose").addEventListener("click", () => map.select(null));

// ── views, drawer, keys ──────────────────────────────────────────────────────
function switchView(name) {
  document.querySelectorAll(".tab").forEach((t) => {
    const on = t.dataset.view === name;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", String(on));
  });
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
  map.setActive(name === "map");
  if (name === "ask") kickField();
  if (name === "map") {
    requestAnimationFrame(() => map.resize());
    if (mapStale) loadMap();
  }
  closeLibrary();
}
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchView(t.dataset.view)));

const lib = $("#library"), scrim = $("#scrim");
function closeLibrary() { lib.classList.remove("open"); scrim.hidden = true; }
$("#libraryToggle").addEventListener("click", () => { lib.classList.add("open"); scrim.hidden = false; });
$("#libraryClose").addEventListener("click", closeLibrary);
scrim.addEventListener("click", closeLibrary);

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!$("#lightbox").hidden) $("#lightbox").hidden = true;
  else if (!panel.hidden) map.select(null);
  else closeLibrary();
});

loadHealth();
loadLibrary();

// ── textures ─────────────────────────────────────────────────────────────────
const kickField = startField($("#field"), { isActive: () => $("#view-ask").classList.contains("active") });

// Cursor spotlight on cards: one listener, writes the pointer position into the
// hovered card's --mx/--my so its radial glow follows the mouse.
document.addEventListener("pointermove", (e) => {
  const el = e.target.closest?.(".spot");
  if (!el) return;
  const r = el.getBoundingClientRect();
  el.style.setProperty("--mx", `${e.clientX - r.left}px`);
  el.style.setProperty("--my", `${e.clientY - r.top}px`);
}, { passive: true });
