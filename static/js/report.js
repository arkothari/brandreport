// ── Report detail page ────────────────────────────────────────────────────

const SECTION_ORDER = [
  "executive_summary",
  "brand_overview",
  "market_context",
  "positioning",
  "competitors",
  "customer_voice",
  "audience",
  "seo_geo",
  "public_market",
  "swot",
  "recommendations",
  "sources",
];

const SECTION_LABELS = {
  executive_summary: "Executive Summary",
  brand_overview:    "Brand Overview",
  market_context:    "Market & Category Context",
  positioning:       "Brand Positioning",
  competitors:       "Competitors",
  swot:              "SWOT Analysis",
  customer_voice:    "Customer Voice",
  public_market:     "Public Market Performance",
  seo_geo:           "Visibility",
  audience:          "Audience Perception",
  recommendations:   "Recommendations",
  sources:           "Sources & Citations",
};

const TOTAL_SECTIONS = SECTION_ORDER.length;

let reportId = "";
let completedCount = 0;
let currentSection = "";
let eventSource = null;
// ── Init ───────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", async () => {
  reportId = window.location.pathname.split("/").pop();
  if (!reportId) { showError("No report ID found in URL."); return; }

  initSidebarNav();
  await loadReport();
});

// ── Load report state from API ─────────────────────────────────────────────

async function loadReport() {
  try {
    const resp = await fetch(`/api/reports/${reportId}`);
    if (!resp.ok) { showError("Report not found."); return; }
    const report = await resp.json();
    renderMeta(report);

    const sections = report.report_data?.sections || {};
    for (const key of SECTION_ORDER) {
      const sec = sections[key];
      if (sec && (sec.status === "complete" || sec.status === "error")) {
        markNav(key, sec.status === "complete" ? "done" : "error");
        renderSection(key, sec.label || SECTION_LABELS[key], sec.content || "");
        completedCount++;
      }
    }
    updateProgress();

    if (report.status === "completed") { markAllDone(report); return; }
    if (report.status === "failed")    { showError(report.error_message || "Evaluation failed."); return; }

    connectSSE();
  } catch (err) {
    showError("Failed to load report: " + err.message);
  }
}

// ── SSE ────────────────────────────────────────────────────────────────────

function connectSSE() {
  if (eventSource) eventSource.close();
  eventSource = new EventSource(`/api/reports/${reportId}/stream`);

  eventSource.addEventListener("status", e => updateStatusBadge(JSON.parse(e.data).status));

  eventSource.addEventListener("section_start", e => {
    const d = JSON.parse(e.data);
    currentSection = d.section;
    markNav(d.section, "running");
    setProgressText(`Researching: ${d.label}…`);
  });

  eventSource.addEventListener("section_complete", e => {
    const d = JSON.parse(e.data);
    if (document.getElementById(`section-${d.section}`)) return;
    markNav(d.section, "done");
    renderSection(d.section, d.label, d.content);
    completedCount++;
    updateProgress();
    setProgressText(`Completed: ${d.label}`);
  });

  eventSource.addEventListener("section_error", e => {
    const d = JSON.parse(e.data);
    markNav(d.section, "error");
    completedCount++;
    updateProgress();
  });

  eventSource.addEventListener("report_complete", e => {
    const d = JSON.parse(e.data);
    setProgressText("Report complete!");
    updateProgress(true);
    updateStatusBadge("completed");
    if (d.pdf_available) showPdfButton();
    eventSource.close();
  });

  eventSource.addEventListener("report_error", e => {
    showError(JSON.parse(e.data).error || "Evaluation failed.");
    eventSource.close();
  });

  eventSource.onerror = () => {
    setTimeout(() => { if (eventSource.readyState === EventSource.CLOSED) connectSSE(); }, 3000);
  };
}

// ── Meta & sidebar helpers ─────────────────────────────────────────────────

function renderMeta(report) {
  document.title = `${report.brand_name} — Brand Report`;
  const nameEl = document.getElementById("sidebar-brand-name");
  if (nameEl) nameEl.textContent = report.brand_name;
  const metaEl = document.getElementById("sidebar-brand-meta");
  if (metaEl) metaEl.textContent = [report.industry, report.market].filter(Boolean).join(" · ") || "—";
  updateStatusBadge(report.status);
  document.getElementById("loading-card").classList.add("hidden");
}

function updateStatusBadge(status) {
  const map = { pending: ["badge-pending","⋯ Pending"], running: ["badge-running","● Running"],
                completed: ["badge-completed","✓ Completed"], failed: ["badge-failed","✕ Failed"] };
  const [cls, label] = map[status] || ["badge-pending", status];
  const el = document.getElementById("sidebar-status");
  if (el) el.innerHTML = `<span class="badge ${cls}">${label}</span>`;
}

function initSidebarNav() {
  const nav = document.getElementById("sidebar-nav");
  if (!nav) return;
  nav.innerHTML = SECTION_ORDER.map(key => `
    <a href="#section-${key}" class="sidebar-nav-item pending" id="nav-${key}">
      <span class="nav-state-icon">○</span>
      <span class="nav-label">${SECTION_LABELS[key]}</span>
    </a>`).join("");
}

function markNav(key, state) {
  const el = document.getElementById(`nav-${key}`);
  if (!el) return;
  el.className = `sidebar-nav-item ${state}`;
  const icons = { done:"✓", running:"⟳", error:"✕", pending:"○" };
  el.querySelector(".nav-state-icon").textContent = icons[state] || "○";
}

function updateProgress(done = false) {
  const count = done ? TOTAL_SECTIONS : completedCount;
  const pct = Math.round((count / TOTAL_SECTIONS) * 100);
  const bar  = document.getElementById("sidebar-progress-bar");
  const frac = document.getElementById("sidebar-progress-fraction");
  if (bar)  bar.style.width = `${pct}%`;
  if (frac) frac.textContent = `${count} / ${TOTAL_SECTIONS}`;
}

function setProgressText(text) {
  const el = document.getElementById("sidebar-progress-text");
  if (el) el.textContent = text;
}

function showPdfButton() {
  const btn = document.getElementById("sidebar-pdf-btn");
  if (btn) btn.classList.remove("hidden");
}

function downloadPdf() { window.location.href = `/api/reports/${reportId}/pdf`; }

// ── Section rendering ──────────────────────────────────────────────────────

function renderSection(key, label, content) {
  if (document.getElementById(`section-${key}`)) return;

  const container = document.getElementById("sections-container");
  const div = document.createElement("div");
  div.id = `section-${key}`;
  div.className = `section-card${key === "executive_summary" ? " exec-summary" : ""}${key === "sources" ? " sources-section" : ""}`;

  const sectionNum = SECTION_ORDER.indexOf(key) + 1;
  const bodyHtml = buildSectionBody(key, content);

  div.innerHTML = `
    <div class="section-card-header">
      <span class="section-num">${String(sectionNum).padStart(2, "0")}</span>
      <span class="section-label">${esc(label)}</span>
    </div>
    <div class="section-card-body">${bodyHtml}</div>`;

  insertInOrder(container, div, key);
  div.scrollIntoView({ behavior: "smooth", block: "nearest" });

  // Post-render hooks
  if (key === "public_market")  initStockQuote(div, content);
  if (key === "customer_voice") initSentimentIndicator(div, content);
}

// ── Section body builders ──────────────────────────────────────────────────

function buildSectionBody(key, content) {
  if (key === "swot")            return renderSwotGrid(content);
  if (key === "seo_geo")         return renderVisibilitySection(content);
  if (key === "recommendations")  return renderRecommendations(content);
  if (key === "public_market")   return renderPublicMarketBody(content);
  if (key === "customer_voice")  return renderCustomerVoiceBody(content);
  return `<div class="md-content">${renderMarkdown(content)}</div>`;
}

// SWOT 2×2 grid — robust parser handles ## Heading, **Heading**, or plain heading variants
function renderSwotGrid(md) {
  const q = { strengths:"", weaknesses:"", opportunities:"", threats:"" };
  let cur = null;

  for (const line of md.split("\n")) {
    // Strip markdown syntax (#, *, _) from the line for matching
    const plain = line.replace(/[#*_]/g, "").trim().toLowerCase();
    if      (plain.startsWith("strength"))    cur = "strengths";
    else if (plain.startsWith("weakness"))    cur = "weaknesses";
    else if (plain.startsWith("opportunit"))  cur = "opportunities";
    else if (plain.startsWith("threat"))      cur = "threats";
    else if (cur) q[cur] += line + "\n";
  }

  // Fallback: if a quadrant is empty, extract from unstructured content
  const allEmpty = Object.values(q).every(v => !v.trim());
  if (allEmpty) {
    // Single-block fallback — try to split on any delimiter
    const chunks = md.split(/\n{2,}/);
    const keys = ["strengths", "weaknesses", "opportunities", "threats"];
    chunks.forEach((chunk, i) => { if (keys[i]) q[keys[i]] = chunk; });
  }

  // Ensure each quadrant has at least a placeholder if still empty
  const placeholders = {
    strengths:     "_Review the full analysis above for strengths._",
    weaknesses:    "_Review the full analysis above for weaknesses._",
    opportunities: "_Review the full analysis above for opportunities._",
    threats:       "_Review the full analysis above for threats._",
  };
  for (const [k, v] of Object.entries(q)) {
    if (!v.trim()) q[k] = placeholders[k];
  }

  const cell = (k, t) =>
    `<div class="swot-cell swot-${k}">
       <div class="swot-cell-title">${t}</div>
       <div class="md-content">${renderMarkdown(q[k])}</div>
     </div>`;

  return `<div class="swot-grid">
    ${cell("strengths","Strengths")}${cell("weaknesses","Weaknesses")}
    ${cell("opportunities","Opportunities")}${cell("threats","Threats")}
  </div>`;
}

// Visibility section — two integrated panels
function renderVisibilitySection(md) {
  const parts = { seo:"", geo:"" };
  let cur = null;
  for (const line of md.split("\n")) {
    if      (/\*\*1\.\s*SEO/i.test(line) || /^##?\s*SEO/i.test(line))  cur = "seo";
    else if (/\*\*2\.\s*GEO/i.test(line) || /^##?\s*GEO/i.test(line))  cur = "geo";
    else if (cur) parts[cur] += line + "\n";
  }
  if (!parts.seo && !parts.geo) return `<div class="md-content">${renderMarkdown(md)}</div>`;
  return `<div class="visibility-panels">
    <div class="vis-panel vis-seo"><div class="vis-panel-title">🔍 SEO Visibility</div><div class="md-content">${renderMarkdown(parts.seo||md)}</div></div>
    <div class="vis-panel vis-geo"><div class="vis-panel-title">🤖 GEO Visibility</div><div class="md-content">${renderMarkdown(parts.geo||"")}</div></div>
  </div>`;
}

// Public market — strip metadata comment, add 52-week quote strip placeholder
function renderPublicMarketBody(content) {
  const clean = content.replace(/<!-- STOCK:[^>]+ -->\n?/, "");
  return `<div class="md-content">${renderMarkdown(clean)}</div>
          <div class="stock-quote-strip hidden" id="sq-strip-public_market"></div>`;
}

// Customer Voice — sentiment indicator + two-panel layout for ratings vs themes
function renderCustomerVoiceBody(content) {
  return `<div class="sentiment-indicator hidden" id="sentiment-indicator"></div>
          <div class="md-content">${renderMarkdown(content)}</div>`;
}

// Recommendations — parse ### headers + Priority/Timeline lines into cards
function renderRecommendations(md) {
  const recBlocks = md.split(/(?=###\s)/);
  const cards = recBlocks
    .map(block => {
      const titleM = block.match(/###\s+(.+)/);
      if (!titleM) return null;
      const title = titleM[1].trim();
      const body = block.replace(/###\s+.+\n/, "");
      const priM = body.match(/\*\*Priority:\*\*\s*(High|Medium|Low)/i);
      const timeM = body.match(/\*\*Timeline:\*\*\s*([^\n*]+)/i);
      const priority = priM ? priM[1] : null;
      const timeline = timeM ? timeM[1].trim() : null;
      const rationale = body.replace(/\*\*Priority:\*\*[^\n]*/i, "").replace(/\*\*Timeline:\*\*[^\n]*/i, "").trim();
      const priClass = priority ? `pri-${priority.toLowerCase()}` : "";
      const badges = [
        priority ? `<span class="rec-badge ${priClass}">${priority}</span>` : "",
        timeline ? `<span class="rec-badge pri-time">${timeline}</span>` : "",
      ].join("");
      return `<div class="rec-card">
        <div class="rec-card-header">
          <span class="rec-title">${esc(title)}</span>
          <div class="rec-badges">${badges}</div>
        </div>
        <div class="rec-rationale md-content">${renderMarkdown(rationale)}</div>
      </div>`;
    })
    .filter(Boolean);

  if (!cards.length) return `<div class="md-content">${renderMarkdown(md)}</div>`;
  return `<div class="rec-cards">${cards.join("")}</div>`;
}

// ── Stock trend comparison (1-year % return vs category benchmark) ────────

async function initStockQuote(sectionEl, content) {
  const m = content.match(/<!-- STOCK:(\w+)\|COMPARE:(\w+) -->/);
  if (!m) return;
  const [, ticker, compare] = m;

  try {
    const resp = await fetch(`/api/stock-quote?ticker=${ticker}&compare=${compare}`);
    const data = await resp.json();
    if (data.error || !data.stock) return;

    const strip = sectionEl.querySelector(".stock-quote-strip");
    if (!strip) return;

    const stockPct  = data.stock?.change_pct;
    const benchPct  = data.benchmark?.change_pct;

    if (stockPct == null) return;

    const fmtPct = n => (n >= 0 ? "+" : "") + n.toFixed(1) + "%";
    const dirCls = n => n >= 0 ? "sq-up" : "sq-down";
    const arrow  = n => n >= 0 ? "↑" : "↓";

    let verdict = "";
    let verdictCls = "";
    if (benchPct != null) {
      const diff = stockPct - benchPct;
      const sameDir = (stockPct >= 0) === (benchPct >= 0);
      if (Math.abs(diff) < 3) {
        verdict = "Tracking category"; verdictCls = "sq-verdict-neutral";
      } else if (diff > 0) {
        verdict = "Outperforming category"; verdictCls = "sq-verdict-up";
      } else {
        verdict = "Underperforming category"; verdictCls = "sq-verdict-down";
      }
      if (!sameDir) {
        verdict = stockPct >= 0 ? "Rising while category declines" : "Declining while category rises";
        verdictCls = stockPct >= 0 ? "sq-verdict-up" : "sq-verdict-down";
      }
    }

    strip.innerHTML = `
      <div class="sq-trend-row">
        <div class="sq-trend-item">
          <span class="sq-tag">${esc(ticker)}</span>
          <span class="sq-pct ${dirCls(stockPct)}">${arrow(stockPct)} ${fmtPct(stockPct)}</span>
          <span class="sq-period">1-year return</span>
        </div>
        ${benchPct != null ? `
        <div class="sq-trend-divider">vs</div>
        <div class="sq-trend-item">
          <span class="sq-tag sq-tag-compare">${esc(compare)} <span class="sq-tag-sub">category</span></span>
          <span class="sq-pct ${dirCls(benchPct)}">${arrow(benchPct)} ${fmtPct(benchPct)}</span>
          <span class="sq-period">1-year return</span>
        </div>
        ` : ""}
        ${verdict ? `<div class="sq-verdict ${verdictCls}">${esc(verdict)}</div>` : ""}
      </div>
    `;
    strip.classList.remove("hidden");
  } catch (_) { /* gracefully skip if Yahoo Finance is unreachable */ }
}

// ── Sentiment indicator ────────────────────────────────────────────────────

function initSentimentIndicator(sectionEl, content) {
  const lower = content.toLowerCase();
  let polarity = "mixed";
  let cls = "sentiment-mixed";
  let icon = "◑";
  if (/overall sentiment.*positive|predominantly positive|largely positive|mostly positive/i.test(content)) {
    polarity = "Positive"; cls = "sentiment-positive"; icon = "↑";
  } else if (/overall sentiment.*negative|predominantly negative|largely negative/i.test(content)) {
    polarity = "Negative"; cls = "sentiment-negative"; icon = "↓";
  } else if (/overall sentiment.*mixed|mixed sentiment/i.test(content)) {
    polarity = "Mixed"; cls = "sentiment-mixed"; icon = "◑";
  }
  const el = sectionEl.querySelector(".sentiment-indicator");
  if (el) {
    el.className = `sentiment-indicator ${cls}`;
    el.innerHTML = `<span class="sentiment-icon">${icon}</span> Overall Sentiment: <strong>${polarity}</strong>`;
    el.classList.remove("hidden");
  }
}

// ── Utilities ──────────────────────────────────────────────────────────────

function insertInOrder(container, newEl, key) {
  const targetIdx = SECTION_ORDER.indexOf(key);
  for (const child of container.children) {
    if (SECTION_ORDER.indexOf(child.id.replace("section-", "")) > targetIdx) {
      container.insertBefore(newEl, child);
      return;
    }
  }
  container.appendChild(newEl);
}

function renderMarkdown(md) {
  if (!md) return "<p><em>No content available.</em></p>";
  try { return marked.parse(md, { breaks: true, gfm: true }); }
  catch { return `<p>${esc(md)}</p>`; }
}

function markAllDone(report) {
  for (const key of SECTION_ORDER) markNav(key, "done");
  updateProgress(true);
  setProgressText("Report complete!");
  updateStatusBadge("completed");
  if (report.pdf_path) showPdfButton();
}

function showError(msg) {
  document.getElementById("loading-card").classList.add("hidden");
  document.getElementById("error-message").textContent = msg;
  document.getElementById("error-card").classList.remove("hidden");
}

function esc(str) {
  return String(str || "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ── Chat drawer ────────────────────────────────────────────────────────────

(function initChat() {
  const fab     = document.getElementById("chat-fab");
  const drawer  = document.getElementById("chat-drawer");
  const closeBtn = document.getElementById("chat-close");
  const messages = document.getElementById("chat-messages");
  const input   = document.getElementById("chat-input");
  const sendBtn = document.getElementById("chat-send");

  let history = [];   // [{role, content}]
  let busy    = false;

  function openDrawer()  { drawer.classList.add("open"); input.focus(); }
  function closeDrawer() { drawer.classList.remove("open"); }

  fab.addEventListener("click", openDrawer);
  closeBtn.addEventListener("click", closeDrawer);

  // Auto-resize textarea
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
    sendBtn.disabled = !input.value.trim() || busy;
  });

  input.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!sendBtn.disabled) sendMessage(); }
  });
  sendBtn.addEventListener("click", sendMessage);

  function appendMsg(role, content, streaming = false) {
    // Remove empty-state placeholder
    const empty = messages.querySelector(".chat-empty");
    if (empty) empty.remove();

    const wrap = document.createElement("div");
    wrap.className = `chat-msg ${role}`;
    const bubble = document.createElement("div");
    bubble.className = "chat-msg-bubble md-content";
    if (streaming) bubble.dataset.streaming = "1";
    if (content) bubble.innerHTML = renderMarkdown(content);
    wrap.appendChild(bubble);
    messages.appendChild(wrap);
    messages.scrollTop = messages.scrollHeight;
    return bubble;
  }

  function showTyping() {
    const dot = document.createElement("div");
    dot.className = "chat-typing";
    dot.id = "chat-typing";
    dot.innerHTML = "<span></span><span></span><span></span>";
    messages.appendChild(dot);
    messages.scrollTop = messages.scrollHeight;
  }
  function removeTyping() {
    const dot = document.getElementById("chat-typing");
    if (dot) dot.remove();
  }

  async function sendMessage() {
    const text = input.value.trim();
    if (!text || busy) return;

    busy = true;
    sendBtn.disabled = true;
    input.value = "";
    input.style.height = "auto";

    appendMsg("user", text);
    history.push({ role: "user", content: text });

    showTyping();

    try {
      const resp = await fetch(`/api/chat/${reportId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history: history.slice(0, -1) }),
      });

      removeTyping();

      if (!resp.ok) {
        appendMsg("assistant", "Sorry, something went wrong. Please try again.");
        busy = false; sendBtn.disabled = false; return;
      }

      const bubble = appendMsg("assistant", "", true);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let full = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        full += decoder.decode(value, { stream: true });
        bubble.innerHTML = renderMarkdown(full);
        messages.scrollTop = messages.scrollHeight;
      }

      delete bubble.dataset.streaming;
      history.push({ role: "assistant", content: full });
      // Keep history bounded to 10 turns
      if (history.length > 20) history = history.slice(-20);
    } catch (err) {
      removeTyping();
      appendMsg("assistant", "Network error — please check your connection and try again.");
    }

    busy = false;
    sendBtn.disabled = !input.value.trim();
    input.focus();
  }
})();
