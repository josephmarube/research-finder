/**
 * Research Finder — Frontend JS
 * Handles search, filters, pagination, paper cards, modal detail view,
 * citation generation, and localStorage-backed library.
 */

"use strict";

// ─────────────────────────────────────────────────────────────
// Utilities
// ─────────────────────────────────────────────────────────────

const $ = (id) => document.getElementById(id);
const show = (el) => el && el.classList.remove("hidden");
const hide = (el) => el && el.classList.add("hidden");

function toast(msg, type = "error") {
  const el = $("toast");
  el.textContent = msg;
  el.className = `toast show ${type}`;
  clearTimeout(el._t);
  el._t = setTimeout(() => (el.className = "toast"), 3500);
}

async function apiFetch(url) {
  const resp = await fetch(url);
  const data = await resp.json();
  if (!resp.ok || data.error) throw new Error(data.error || `HTTP ${resp.status}`);
  return data;
}

function escHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fmtNum(n) {
  if (!n && n !== 0) return "—";
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function truncateAuthors(authors, max = 4) {
  if (!authors || !authors.length) return "Unknown Author";
  if (authors.length <= max) return authors.join(", ");
  return authors.slice(0, max).join(", ") + ` +${authors.length - max} more`;
}

// ─────────────────────────────────────────────────────────────
// Tab switching
// ─────────────────────────────────────────────────────────────

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const target = btn.dataset.tab;
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(`tab-${target}`).classList.add("active");
    if (target === "library") renderLibrary();
  });
});

// ─────────────────────────────────────────────────────────────
// Source + cache badges
// ─────────────────────────────────────────────────────────────

function setSourceBadge(source, cached) {
  const sb = $("sourceBadge");
  const cb = $("cacheBadge");

  sb.textContent = source === "openalex" ? "OpenAlex" : "CrossRef";
  sb.className = `source-badge ${source === "openalex" ? "openalex" : "crossref"}`;

  if (cached) {
    cb.textContent = "CACHED";
    cb.className = "cache-badge cached";
  } else {
    cb.className = "cache-badge";
  }
}

// ─────────────────────────────────────────────────────────────
// SEARCH
// ─────────────────────────────────────────────────────────────

let currentPage = 1;
let currentQuery = {};
let lastResults = [];

$("searchBtn").addEventListener("click", () => runSearch(1));
$("queryInput").addEventListener("keydown", (e) => { if (e.key === "Enter") runSearch(1); });

async function runSearch(page = 1) {
  const q       = $("queryInput").value.trim();
  const author  = $("authorInput").value.trim();
  const year    = $("yearInput").value.trim();
  const type    = $("typeSelect").value;
  const sort    = $("sortSelect").value;
  const oaOnly  = $("oaOnly").checked;

  if (!q && !author) {
    toast("Enter a keyword or author name to search");
    return;
  }

  currentPage  = page;
  currentQuery = { q, author, year, type, sort, oaOnly };

  hide($("emptyState"));
  hide($("resultsMeta"));
  show($("searchLoader"));
  $("papersList").innerHTML = "";

  const params = new URLSearchParams();
  if (q)      params.set("q", q);
  if (author) params.set("author", author);
  if (year)   params.set("year", year);
  if (type)   params.set("type", type);
  if (oaOnly) params.set("oa_only", "true");
  params.set("sort", sort);
  params.set("page", page);
  params.set("per_page", 10);

  try {
    const data = await apiFetch(`/api/search?${params}`);
    lastResults = data.results || [];
    setSourceBadge(data.source, data._cached);
    renderResults(data);
  } catch (err) {
    hide($("searchLoader"));
    show($("emptyState"));
    toast(`Search failed: ${err.message}`);
  }
}

function renderResults(data) {
  hide($("searchLoader"));
  show($("resultsArea"));

  if (!data.results || !data.results.length) {
    show($("emptyState"));
    $("emptyState").querySelector("p").textContent = "No papers found. Try different keywords or filters.";
    return;
  }

  // Meta bar
  $("resultsCount").innerHTML =
    `Found <strong>${data.total.toLocaleString()}</strong> papers · showing page ${data.page}`;
  renderPagination(data.total, data.page, data.per_page);
  show($("resultsMeta"));

  // Cards
  $("papersList").innerHTML = data.results.map((p) => paperCardHTML(p)).join("");
  attachCardListeners();
}

function renderPagination(total, page, perPage) {
  const totalPages = Math.min(Math.ceil(total / perPage), 50); // cap at 50 pages
  const pag = $("pagination");

  if (totalPages <= 1) { pag.innerHTML = ""; return; }

  const pages = [];
  // Always show first, last, and window around current
  const window = 2;
  for (let i = 1; i <= totalPages; i++) {
    if (i === 1 || i === totalPages || (i >= page - window && i <= page + window)) {
      pages.push(i);
    }
  }

  // Insert ellipses
  const btns = [];
  let prev = null;
  for (const p of pages) {
    if (prev && p - prev > 1) btns.push("…");
    btns.push(p);
    prev = p;
  }

  pag.innerHTML =
    `<button class="page-btn" ${page === 1 ? "disabled" : ""} data-page="${page - 1}">← Prev</button>` +
    btns.map((p) =>
      p === "…"
        ? `<span style="color:var(--ink-3);padding:0 4px">…</span>`
        : `<button class="page-btn ${p === page ? "active" : ""}" data-page="${p}">${p}</button>`
    ).join("") +
    `<button class="page-btn" ${page >= totalPages ? "disabled" : ""} data-page="${page + 1}">Next →</button>`;

  pag.querySelectorAll(".page-btn:not([disabled])").forEach((btn) => {
    btn.addEventListener("click", () => runSearch(parseInt(btn.dataset.page)));
  });
}

// ─────────────────────────────────────────────────────────────
// Paper card HTML
// ─────────────────────────────────────────────────────────────

function paperCardHTML(p, inLibrary = false) {
  const saved     = isInLibrary(p.doi || p.id);
  const oaBadge   = p.is_oa ? `<span class="badge badge-oa">Open Access</span>` : "";
  const typeBadge = p.type ? `<span class="badge badge-type">${escHtml(p.type.replace(/-/g, " "))}</span>` : "";
  const srcBadge  = p.source === "openalex"
    ? `<span class="badge badge-source-oa">OpenAlex</span>`
    : `<span class="badge badge-source-cr">CrossRef</span>`;

  const authorsStr = truncateAuthors(p.authors);
  const metaParts  = [
    `<span class="authors">${escHtml(authorsStr)}</span>`,
    p.year ? `<span>${p.year}</span>` : "",
    p.venue ? `<span class="venue">${escHtml(p.venue)}</span>` : "",
  ].filter(Boolean).join(" · ");

  const concepts = (p.concepts || []).slice(0, 5)
    .map((c) => `<span class="concept-tag">${escHtml(c)}</span>`)
    .join("");

  const doiKey = p.doi || p.id;

  return `
<div class="paper-card" data-doi="${escHtml(doiKey)}">
  <div class="paper-card-top">
    <div class="paper-title" data-doi="${escHtml(doiKey)}">${escHtml(p.title)}</div>
    <div class="paper-badges">${oaBadge}${typeBadge}${srcBadge}</div>
  </div>
  <div class="paper-meta">${metaParts}</div>
  ${p.abstract ? `<div class="paper-abstract">${escHtml(p.abstract)}</div>` : ""}
  ${concepts ? `<div class="paper-concepts">${concepts}</div>` : ""}
  <div class="paper-actions">
    <span class="stat-chip" title="Cited by">📖 ${fmtNum(p.cited_by)} citations</span>
    ${p.is_oa && p.oa_url ? `<a class="btn-link" href="${escHtml(p.oa_url)}" target="_blank" rel="noopener">Read free PDF ↗</a>` : ""}
    ${p.doi ? `<a class="btn-link" href="https://doi.org/${escHtml(p.doi)}" target="_blank" rel="noopener">DOI ↗</a>` : ""}
    <span class="spacer"></span>
    <button class="btn-sm btn-outline" data-detail="${escHtml(doiKey)}">Details</button>
    ${inLibrary
      ? `<button class="btn-sm btn-outline danger" data-remove="${escHtml(doiKey)}">Remove</button>`
      : `<button class="btn-sm btn-outline ${saved ? "saved" : ""}" data-save="${escHtml(doiKey)}">${saved ? "✓ Saved" : "Save"}</button>`
    }
  </div>
</div>`;
}

function attachCardListeners() {
  // Combine search results + library list listeners
  document.querySelectorAll("[data-detail]").forEach((btn) => {
    btn.addEventListener("click", () => openModal(btn.dataset.detail));
  });

  document.querySelectorAll("[data-save]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const doi = btn.dataset.save;
      const paper = findPaper(doi);
      if (!paper) return;
      saveToLibrary(paper);
      btn.textContent = "✓ Saved";
      btn.classList.add("saved");
      toast("Paper saved to My Library", "success");
    });
  });

  document.querySelectorAll("[data-remove]").forEach((btn) => {
    btn.addEventListener("click", () => {
      removeFromLibrary(btn.dataset.remove);
      renderLibrary();
      updateLibraryCount();
    });
  });

  document.querySelectorAll(".paper-title[data-doi]").forEach((el) => {
    el.addEventListener("click", () => openModal(el.dataset.doi));
  });
}

function findPaper(doi) {
  return lastResults.find((p) => (p.doi || p.id) === doi) ||
    getLibrary().find((p) => (p.doi || p.id) === doi) || null;
}

// ─────────────────────────────────────────────────────────────
// LOCAL STORAGE LIBRARY
// ─────────────────────────────────────────────────────────────

const LIBRARY_KEY = "rf_library_v1";

function getLibrary() {
  try {
    return JSON.parse(localStorage.getItem(LIBRARY_KEY) || "[]");
  } catch {
    return [];
  }
}

function saveLibrary(items) {
  localStorage.setItem(LIBRARY_KEY, JSON.stringify(items));
  updateLibraryCount();
}

function saveToLibrary(paper) {
  const lib = getLibrary();
  if (!lib.find((p) => (p.doi || p.id) === (paper.doi || paper.id))) {
    lib.unshift({ ...paper, _savedAt: Date.now() });
    saveLibrary(lib);
  }
}

function removeFromLibrary(doi) {
  const lib = getLibrary().filter((p) => (p.doi || p.id) !== doi);
  saveLibrary(lib);
}

function isInLibrary(doi) {
  return !!getLibrary().find((p) => (p.doi || p.id) === doi);
}

function updateLibraryCount() {
  const count = getLibrary().length;
  $("libraryCount").textContent = count;
}

// Sort library
$("libSortSelect").addEventListener("change", () => renderLibrary());

function renderLibrary() {
  const lib = getLibrary();
  updateLibraryCount();

  if (!lib.length) {
    show($("libraryEmpty"));
    $("libraryList").innerHTML = "";
    return;
  }

  hide($("libraryEmpty"));

  const sort = $("libSortSelect").value;
  const sorted = [...lib].sort((a, b) => {
    if (sort === "added")    return (b._savedAt || 0) - (a._savedAt || 0);
    if (sort === "year")     return (b.year || 0) - (a.year || 0);
    if (sort === "cited_by") return (b.cited_by || 0) - (a.cited_by || 0);
    if (sort === "title")    return (a.title || "").localeCompare(b.title || "");
    return 0;
  });

  $("libraryList").innerHTML = sorted.map((p) => paperCardHTML(p, true)).join("");
  attachCardListeners();
}

// Clear library
$("clearLibraryBtn").addEventListener("click", () => {
  if (!confirm("Clear your entire library? This cannot be undone.")) return;
  localStorage.removeItem(LIBRARY_KEY);
  renderLibrary();
  toast("Library cleared");
});

// ─────────────────────────────────────────────────────────────
// MODAL — Paper detail + citations
// ─────────────────────────────────────────────────────────────

let currentModalDoi = null;
let currentCitFormat = "apa";

function openModal(doi) {
  currentModalDoi = doi;
  $("modalBody").innerHTML = `<div class="modal-loading"><div class="spinner"></div><span>Loading…</span></div>`;
  $("citationOutput").textContent = "Select a format above…";
  show($("modalOverlay"));
  document.body.style.overflow = "hidden";
  loadPaperDetail(doi);
}

function closeModal() {
  hide($("modalOverlay"));
  document.body.style.overflow = "";
  currentModalDoi = null;
}

$("modalClose").addEventListener("click", closeModal);
$("modalOverlay").addEventListener("click", (e) => {
  if (e.target === $("modalOverlay")) closeModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeModal();
});

async function loadPaperDetail(doi) {
  // Try to use cached paper first (from search results or library)
  const cached = findPaper(doi);

  if (cached) {
    renderModal(cached);
    loadCitation(doi, currentCitFormat);
    return;
  }

  try {
    const data = await apiFetch(`/api/paper?doi=${encodeURIComponent(doi)}`);
    renderModal(data);
    loadCitation(doi, currentCitFormat);
  } catch (err) {
    $("modalBody").innerHTML = `<p style="color:var(--red);padding:32px 0">Error: ${escHtml(err.message)}</p>`;
    toast(`Could not load paper details: ${err.message}`);
  }
}

function renderModal(p) {
  const authorsStr = (p.authors || []).join(", ") || "Unknown Author";
  const concepts   = (p.concepts || [])
    .map((c) => `<span class="concept-tag">${escHtml(c)}</span>`)
    .join("");

  $("modalBody").innerHTML = `
    <h2 class="modal-title">${escHtml(p.title)}</h2>
    <div class="modal-authors">${escHtml(authorsStr)}</div>
    ${p.venue ? `<div class="modal-venue">${escHtml(p.venue)}${p.year ? `, ${p.year}` : ""}</div>` : ""}
    <div class="modal-stats">
      ${p.year     ? `<div class="modal-stat"><span class="modal-stat-label">Year</span><span class="modal-stat-val">${p.year}</span></div>` : ""}
      ${p.cited_by !== undefined ? `<div class="modal-stat"><span class="modal-stat-label">Citations</span><span class="modal-stat-val">${fmtNum(p.cited_by)}</span></div>` : ""}
      ${p.type     ? `<div class="modal-stat"><span class="modal-stat-label">Type</span><span class="modal-stat-val">${escHtml(p.type)}</span></div>` : ""}
      <div class="modal-stat"><span class="modal-stat-label">Open Access</span><span class="modal-stat-val">${p.is_oa ? "✓ Yes" : "No"}</span></div>
    </div>
    ${p.abstract ? `<div class="modal-abstract">${escHtml(p.abstract)}</div>` : ""}
    ${concepts ? `<div class="modal-concepts">${concepts}</div>` : ""}
    <div class="modal-links">
      ${p.doi      ? `<a class="btn-sm btn-outline" href="https://doi.org/${escHtml(p.doi)}" target="_blank">DOI ↗</a>` : ""}
      ${p.is_oa && p.oa_url ? `<a class="btn-sm btn-primary" href="${escHtml(p.oa_url)}" target="_blank">Read Free PDF ↗</a>` : ""}
      ${p.url && p.source === "openalex" ? `<a class="btn-sm btn-outline" href="${escHtml(p.url)}" target="_blank">OpenAlex ↗</a>` : ""}
    </div>
  `;
}

// Citation format buttons
document.querySelectorAll(".cite-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".cite-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentCitFormat = btn.dataset.fmt;
    if (currentModalDoi) loadCitation(currentModalDoi, currentCitFormat);
  });
});

async function loadCitation(doi, fmt) {
  $("citationOutput").textContent = "Generating…";
  try {
    const data = await apiFetch(`/api/cite?doi=${encodeURIComponent(doi)}&format=${fmt}`);
    $("citationOutput").textContent = data.citation || "No citation data available";
  } catch (err) {
    $("citationOutput").textContent = `Error: ${err.message}`;
  }
}

$("copyCiteBtn").addEventListener("click", () => {
  const text = $("citationOutput").textContent;
  if (!text || text === "Select a format above…") return;
  navigator.clipboard.writeText(text).then(() => {
    toast("Citation copied to clipboard", "success");
  }).catch(() => {
    toast("Could not copy — please select and copy manually");
  });
});

// ─────────────────────────────────────────────────────────────
// Initialise
// ─────────────────────────────────────────────────────────────

updateLibraryCount();

// Focus search on load
$("queryInput").focus();
