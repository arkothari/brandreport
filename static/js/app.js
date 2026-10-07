// ── Index page: form submission + report listing ──────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  loadHealth();
  loadReports();
  document.getElementById("eval-form").addEventListener("submit", handleSubmit);
});

// ── Health badges ──────────────────────────────────────────────────────────

async function loadHealth() {
  try {
    const r = await fetch("/api/health");
    const d = await r.json();
    const wrap = document.getElementById("health-badges");
    const services = [
      { key: "anthropic", label: "Claude" },
      { key: "openai",    label: "OpenAI" },
      { key: "tavily",    label: "Tavily" },
    ];
    wrap.innerHTML = services
      .map(s => `<span class="health-badge ${d[s.key] ? "ok" : "err"}">${s.label}</span>`)
      .join("");
  } catch {}
}

// ── Form submission ─────────────────────────────────────────────────────────

async function handleSubmit(e) {
  e.preventDefault();
  const btn   = document.getElementById("submit-btn");
  const errEl = document.getElementById("form-error");

  errEl.classList.add("hidden");
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span> Starting…`;

  const brand  = document.getElementById("brand-name").value.trim();
  const industry = document.getElementById("industry").value.trim();
  const market = document.getElementById("market").value.trim();
  const competitorRaw = document.getElementById("competitors").value.trim();
  const competitors = competitorRaw ? competitorRaw.split(",").map(c => c.trim()).filter(Boolean) : [];

  try {
    const resp = await fetch("/api/reports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ brand_name: brand, industry, market, competitors }),
    });
    if (!resp.ok) {
      const d = await resp.json();
      throw new Error(d.detail || "Failed to create report");
    }
    const report = await resp.json();
    window.location.href = `/report/${report.id}`;
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.remove("hidden");
    btn.disabled = false;
    btn.innerHTML = `<span class="btn-icon">🔍</span> Generate Report`;
  }
}

// ── Reports listing ─────────────────────────────────────────────────────────

async function loadReports() {
  const loading  = document.getElementById("reports-loading");
  const empty    = document.getElementById("reports-empty");
  const tableWrap = document.getElementById("reports-table-wrap");
  const tbody    = document.getElementById("reports-tbody");

  loading.classList.remove("hidden");
  empty.classList.add("hidden");
  tableWrap.classList.add("hidden");

  try {
    const resp = await fetch("/api/reports");
    const reports = await resp.json();
    loading.classList.add("hidden");

    if (!reports.length) {
      empty.classList.remove("hidden");
      return;
    }

    tbody.innerHTML = reports.map(r => {
      const date = r.created_at ? new Date(r.created_at).toLocaleDateString() : "—";
      const statusBadge = badgeHtml(r.status);
      const actions = actionsHtml(r);
      return `
        <tr>
          <td><strong>${esc(r.brand_name)}</strong></td>
          <td>${esc(r.industry || "—")}</td>
          <td>${esc(r.market || "—")}</td>
          <td>${statusBadge}</td>
          <td>${date}</td>
          <td>${actions}</td>
        </tr>`;
    }).join("");

    tableWrap.classList.remove("hidden");
  } catch {
    loading.innerHTML = "Failed to load reports.";
  }
}

function badgeHtml(status) {
  const map = {
    pending:   ["badge-pending",  "⋯ Pending"],
    running:   ["badge-running",  '<span class="pulse">●</span> Running'],
    completed: ["badge-completed","✓ Completed"],
    failed:    ["badge-failed",   "✕ Failed"],
  };
  const [cls, label] = map[status] || ["badge-pending", status];
  return `<span class="badge ${cls}">${label}</span>`;
}

function actionsHtml(r) {
  let html = `<a href="/report/${r.id}" class="btn btn-ghost btn-sm">View</a>`;
  if (r.status === "completed" && r.pdf_path) {
    html += ` <a href="/api/reports/${r.id}/pdf" class="btn btn-success btn-sm" download>⬇ PDF</a>`;
  }
  return html;
}

function esc(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
