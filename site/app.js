const DATA_URL = "parsed/incidents.json";

// Worst-to-least. Higher rank wins when a day sees several severities.
const SEVERITY_RANK = {
  disruption: 4,
  impact: 3,
  degradation: 2,
  informational: 1,
  operational: 0,
  unknown: -1,
};

const SEVERITY_LABEL = {
  disruption: "Disruption",
  impact: "Impact",
  degradation: "Degradation",
  informational: "Informational",
  operational: "Operational",
};

function fmtDate(iso) {
  const d = new Date(iso);
  return d.toUTCString().replace(" GMT", " UTC");
}

function dayKey(iso) {
  return new Date(iso).toISOString().slice(0, 10);
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

async function loadIncidents() {
  const resp = await fetch(DATA_URL);
  if (!resp.ok) {
    throw new Error(`could not load ${DATA_URL} (${resp.status})`);
  }
  return resp.json();
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
    strip.hidden = true;
    return;
  }

  const start = new Date(firstDay);
  const end = new Date(lastDay);
  let cursor = new Date(start);

  for (let i = 0; cursor <= end; i++) {
    const key = cursor.toISOString().slice(0, 10);
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
    cursor.setDate(cursor.getDate() + 1);
  }

  const labels = document.querySelectorAll(".strip-axis span");
  labels[0].textContent = fmtDate(firstDay + "T00:00:00Z").slice(0, 11) + firstDay;
  labels[2].textContent = lastDay;
}

function severityBadge(sev) {
  const label = SEVERITY_LABEL[sev] ?? sev;
  return `<span class="badge badge-${sev}">${label}</span>`;
}

function renderIncident(incident) {
  const first = incident.updates[0];
  const updates = [...incident.updates].sort(
    (a, b) => new Date(a.published) - new Date(b.published)
  );
  const badges = [...new Set(updates.map((u) => u.severity))]
    .sort((a, b) => (SEVERITY_RANK[b] ?? -1) - (SEVERITY_RANK[a] ?? -1))
    .map(severityBadge)
    .join(" ");

  const article = document.createElement("article");
  article.className = "incident";
  article.innerHTML = `
    <div class="incident-head">
      <h3>${incident.title}</h3>
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

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function main() {
  const list = document.getElementById("incidentList");
  const empty = document.getElementById("emptyState");
  const updated = document.getElementById("updatedAt");
  try {
    const incidents = await loadIncidents();
    incidents.sort((a, b) => new Date(a.started_at) - new Date(b.started_at));
    renderStats(incidents);
    renderStrip(incidents);
    if (incidents.length === 0) {
      empty.hidden = false;
    } else {
      for (const incident of incidents) {
        list.appendChild(renderIncident(incident));
      }
    }
    updated.textContent = `Rendered at ${new Date().toUTCString().replace(" GMT", " UTC")} from the current archive.`;
  } catch (err) {
    list.innerHTML = `<p class="muted">Could not load the data: ${escapeHtml(String(err.message || err))}</p>`;
  }
}

main();