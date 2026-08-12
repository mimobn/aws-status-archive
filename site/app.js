const DATA_URL = "parsed/incidents.json";

const SEVERITY_RANK = {
  disrupted: 4,
  impacted: 3,
  degraded: 2,
  informational: 1,
  operational: 0,
  unknown: -1,
};

const SEVERITY_LABEL = {
  disrupted: "Disrupted",
  impacted: "Impacted",
  degraded: "Degraded",
  informational: "Informational",
  operational: "Operating normally",
};

function fmtDate(iso) {
  const d = new Date(iso);
  return d.toUTCString().replace(" GMT", " UTC");
}

function dayKey(iso) {
  return new Date(iso).toISOString().slice(0, 10);
}

const MONTHS_SHORT = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function fmtShortDate(day) {
  const [y, m, d] = day.split("-").map(Number);
  return `${MONTHS_SHORT[m - 1]} ${d}, ${y}`;
}

function worstSeverity(candidates) {
  let worst = "unknown";
  let worstRank = -1;
  for (const s of candidates) {
    const rank = SEVERITY_RANK[s] ?? -1;
    if (rank > worstRank) {
      worstRank = rank;
      worst = s;
    }
  }
  return worst;
}

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function loadIncidents() {
  const resp = await fetch(DATA_URL);
  if (!resp.ok) {
    throw new Error(`could not load ${DATA_URL} (${resp.status})`);
  }
  return resp.json();
}

const REGION_CODE_RE = /\b([a-z]{2,3}(?:-[a-z0-9]+)*-\d)\b/i;

const REGION_NAMES = {
  "me-central-1": "Middle East (UAE)",
  "me-south-1": "Middle East (Bahrain)",
};

function regionLabel(incident) {
  if (incident.region_name) return incident.region_name;
  if (incident.region) return REGION_NAMES[incident.region] || incident.region;
  const match = incident.key.match(REGION_CODE_RE);
  if (match) {
    const code = match[1].toLowerCase();
    return REGION_NAMES[code] || code.toUpperCase();
  }
  return null;
}

function buildRegionMap(incidents) {
  const counts = {};
  for (const inc of incidents) {
    const label = regionLabel(inc);
    if (label) {
      counts[label] = (counts[label] || 0) + 1;
    }
  }
  const entries = Object.entries(counts).sort((a, b) => a[0].localeCompare(b[0]));
  return entries;
}

function renderSidebar(regions, total, activeRegion) {
  const container = document.getElementById("regionList");
  const items = [];

  const allClass = activeRegion === null ? "sidebar-item active" : "sidebar-item";
  items.push(`<a class="${allClass}" data-region="" href="#">All regions <span class="sidebar-count">${total}</span></a>`);

  for (const [label, count] of regions) {
    const cls = activeRegion === label ? "sidebar-item active" : "sidebar-item";
    items.push(`<a class="${cls}" data-region="${escapeHtml(label)}" href="#${encodeURIComponent(label)}">${escapeHtml(label)} <span class="sidebar-count">${count}</span></a>`);
  }

  container.innerHTML = items.join("");
}

function renderStats(incidents) {
  const counts = {};
  for (const incident of incidents) {
    for (const update of incident.updates) {
      counts[update.severity] = (counts[update.severity] || 0) + 1;
    }
  }
  const bySeverity = Object.entries(counts)
    .filter(([, n]) => n > 0)
    .sort((a, b) => (SEVERITY_RANK[b[0]] ?? -1) - (SEVERITY_RANK[a[0]] ?? -1));

  const updatesTotal = incidents.reduce((sum, i) => sum + i.updates.length, 0);

  const el = document.getElementById("summaryStats");
  el.innerHTML = `
    <div class="stat"><span class="stat-num">${incidents.length}</span> incidents</div>
    <div class="stat"><span class="stat-num">${updatesTotal}</span> updates</div>
    ${bySeverity
      .map(
        ([sev, n]) =>
          `<div class="stat"><span class="stat-num stat-${sev}">${n}</span> ${SEVERITY_LABEL[sev] ?? sev}</div>`
      )
      .join("")}
  `;
}

function renderStrip(incidents) {
  const byDay = {};
  let firstDay = null;
  let lastDay = null;
  for (const incident of incidents) {
    for (const update of incident.updates) {
      const key = dayKey(update.published);
      (byDay[key] = byDay[key] || []).push(update.severity);
      if (!firstDay || key < firstDay) firstDay = key;
      if (!lastDay || key > lastDay) lastDay = key;
    }
  }

  const strip = document.getElementById("daysStrip");
  if (!firstDay) {
    strip.innerHTML = "";
    strip.hidden = true;
    return;
  }
  strip.hidden = false;
  strip.innerHTML = "";

  const [startY, startM, startD] = firstDay.split("-").map(Number);
  const [endY, endM, endD] = lastDay.split("-").map(Number);
  const startMs = Date.UTC(startY, startM - 1, startD);
  const endMs = Date.UTC(endY, endM - 1, endD);

  for (let ms = startMs; ms <= endMs; ms += 86400000) {
    const key = new Date(ms).toISOString().slice(0, 10);
    const severities = byDay[key];
    const sev = severities ? worstSeverity(severities) : "none";
    const cell = document.createElement("span");
    cell.className = `cell cell-${sev}`;
    if (severities) {
      cell.title = `${key}: ${SEVERITY_LABEL[sev]} (${severities.length} update(s))`;
    } else {
      cell.title = `${key}: no record`;
    }
    strip.appendChild(cell);
  }

  const labels = document.querySelectorAll(".strip-axis span");
  labels[0].textContent = fmtShortDate(firstDay);
  labels[2].textContent = fmtShortDate(lastDay);
}

function severityBadge(sev) {
  const label = SEVERITY_LABEL[sev] ?? sev;
  return `<span class="badge badge-${sev}">${label}</span>`;
}

function renderIncident(incident) {
  const updates = [...incident.updates].sort(
    (a, b) => new Date(a.published) - new Date(b.published)
  );
  const badges = [...new Set(updates.map((u) => u.severity))]
    .sort((a, b) => (SEVERITY_RANK[b] ?? -1) - (SEVERITY_RANK[a] ?? -1))
    .map(severityBadge)
    .join(" ");

  const regionLabel = incident.region_name || incident.region;
  const regionBadge = regionLabel
    ? `<span class="incident-region">${escapeHtml(regionLabel)}</span>`
    : "";

  const article = document.createElement("article");
  article.className = "incident";
  article.innerHTML = `
    <div class="incident-head">
      <h3>${escapeHtml(incident.title)}${regionBadge}</h3>
      <div class="incident-badges">${badges}</div>
    </div>
    <div class="incident-meta">
      <span>${fmtDate(updates[0].published)}</span>
      <span>→</span>
      <span>${fmtDate(updates[updates.length - 1].published)}</span>
      <span class="muted">· ${updates.length} update(s)</span>
    </div>
    <ul class="timeline">
      ${updates
        .map(
          (u) => `
        <li>
          <div class="timeline-meta">
            <span class="dot dot-${u.severity}"></span>
            <span class="timeline-time">${fmtDate(u.published)}</span>
            ${severityBadge(u.severity)}
          </div>
          <div class="timeline-desc">${escapeHtml(u.description) || "—"}</div>
        </li>`
        )
        .join("")}
    </ul>
  `;
  return article;
}

function getActiveRegion() {
  const hash = location.hash.slice(1);
  return hash ? decodeURIComponent(hash) : null;
}

function renderAll(incidents) {
  const allRegions = buildRegionMap(incidents);
  const activeRegion = getActiveRegion();

  const filtered = activeRegion
    ? incidents.filter((inc) => regionLabel(inc) === activeRegion)
    : incidents;

  renderSidebar(allRegions, incidents.length, activeRegion);
  renderStats(filtered);
  renderStrip(filtered);

  const list = document.getElementById("incidentList");
  const empty = document.getElementById("emptyState");
  list.innerHTML = "";

  if (filtered.length === 0) {
    empty.hidden = false;
  } else {
    empty.hidden = true;
    for (const incident of filtered) {
      list.appendChild(renderIncident(incident));
    }
  }
}

function renderError(message) {
  const list = document.getElementById("incidentList");
  const empty = document.getElementById("emptyState");
  list.innerHTML = "";
  empty.hidden = false;
  empty.innerHTML = message;
}

async function main() {
  const updated = document.getElementById("updatedAt");
  try {
    const incidents = await loadIncidents();
    incidents.sort((a, b) => new Date(a.started_at) - new Date(b.started_at));

    renderAll(incidents);

    document.getElementById("regionList").addEventListener("click", (e) => {
      const link = e.target.closest(".sidebar-item");
      if (!link) return;
      e.preventDefault();
      const region = link.dataset.region || null;
      if (region) {
        location.hash = encodeURIComponent(region);
      } else {
        history.pushState("", "", location.pathname + location.search);
      }
      renderAll(incidents);
    });

    window.addEventListener("hashchange", () => renderAll(incidents));

    updated.textContent = `Rendered at ${new Date().toUTCString().replace(" GMT", " UTC")} from the current archive.`;
  } catch (err) {
    renderSidebar([], 0, null);
    renderStats([]);
    renderStrip([]);
    renderError(
      `Could not load the archive (${escapeHtml(String(err.message || err))}). ` +
        "If you opened this page directly, serve it over HTTP with " +
        "<code>parsed/incidents.json</code> in place and reload."
    );
  }
}

main();
