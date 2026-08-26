/**
 * status-archive — Main Application Engine
 * Renders AWS incident history, regions breakdown, timeline heatmap, modal inspector, and interactive filters.
 */

const DATA_URLS = ["parsed/incidents.json", "../out/incidents.json"];
const METADATA_URLS = ["parsed/metadata.json", "../out/metadata.json"];

const SEVERITY_RANK = {
  disrupted: 4,
  impacted: 3,
  degraded: 2,
  informational: 1,
  operational: 0,
  unknown: -1,
  no_data: -2,
};

const SEVERITY_LABEL = {
  disrupted: "Disrupted",
  impacted: "Impacted",
  degraded: "Degraded",
  informational: "Informational",
  operational: "Operating Normally",
  no_data: "No Data Available",
};

const MONTHS_SHORT = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

const DAY_KEYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const REGION_NAMES = {
  "us-east-1": "US East (N. Virginia)",
  "us-east-2": "US East (Ohio)",
  "us-west-1": "US West (N. California)",
  "us-west-2": "US West (Oregon)",
  "ca-central-1": "Canada (Central)",
  "ca-west-1": "Canada West (Calgary)",
  "eu-west-1": "Europe (Ireland)",
  "eu-central-1": "Europe (Frankfurt)",
  "eu-west-2": "Europe (London)",
  "eu-west-3": "Europe (Paris)",
  "eu-north-1": "Europe (Stockholm)",
  "eu-south-1": "Europe (Milan)",
  "eu-south-2": "Europe (Spain)",
  "eu-central-2": "Europe (Zurich)",
  "ap-southeast-1": "Asia Pacific (Singapore)",
  "ap-southeast-2": "Asia Pacific (Sydney)",
  "ap-northeast-1": "Asia Pacific (Tokyo)",
  "ap-northeast-2": "Asia Pacific (Seoul)",
  "ap-northeast-3": "Asia Pacific (Osaka)",
  "ap-south-1": "Asia Pacific (Mumbai)",
  "ap-south-2": "Asia Pacific (Hyderabad)",
  "ap-southeast-3": "Asia Pacific (Jakarta)",
  "ap-southeast-4": "Asia Pacific (Melbourne)",
  "sa-east-1": "South America (São Paulo)",
  "me-central-1": "Middle East (UAE)",
  "me-south-1": "Middle East (Bahrain)",
  "af-south-1": "Africa (Cape Town)",
  "us-gov-east-1": "AWS GovCloud (US-East)",
  "us-gov-west-1": "AWS GovCloud (US-West)",
  "global": "Global Services",
};

const REGION_CODE_RE = /\b([a-z]{2,3}(?:-[a-z0-9]+)*-\d)\b/i;

// State Store
const state = {
  allIncidents: [],
  archiveMetadata: null,
  activeRegion: null,
  activeSeverity: "all",
  activeDate: null,
  searchQuery: "",
  regionSearchQuery: "",
  impactedServicesOnly: false,
  sortOrder: "newest",
  theme: localStorage.getItem("theme") || "dark",
  // Modal state
  activeModalIncident: null,
  // Strip window state
  windowDays: 90,
  stripWindowEnd: null,
  stripShowAll: false,
  stripFirstDay: null,
};

// Date utilities
function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toUTCString().replace(" GMT", " UTC");
}

function fmtShortDate(dayStr) {
  if (!dayStr) return "—";
  const [y, m, d] = dayStr.split("-").map(Number);
  return `${MONTHS_SHORT[m - 1]} ${d}, ${y}`;
}

function fmtShortDay(dayStr) {
  if (!dayStr) return "—";
  const [y, m, d] = dayStr.split("-").map(Number);
  const dateObj = new Date(Date.UTC(y, m - 1, d));
  return `${fmtShortDate(dayStr)} · ${DAY_KEYS[dateObj.getUTCDay()]}`;
}

function dayKey(iso) {
  return new Date(iso).toISOString().slice(0, 10);
}

function dayToMs(key) {
  const [y, m, d] = key.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

function keyFromMs(ms) {
  return new Date(ms).toISOString().slice(0, 10);
}

function addDays(key, n) {
  return keyFromMs(dayToMs(key) + n * 86400000);
}

function todayKey() {
  return new Date().toISOString().slice(0, 10);
}

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
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

function regionLabel(incident) {
  if (incident.region_name) return incident.region_name;
  if (incident.region) return REGION_NAMES[incident.region] || incident.region;
  const match = incident.key ? incident.key.match(REGION_CODE_RE) : null;
  if (match) {
    const code = match[1].toLowerCase();
    return REGION_NAMES[code] || code.toUpperCase();
  }
  return null;
}

function worstSeverityFromUpdates(incident) {
  let worst = "unknown";
  for (const update of incident.updates || []) {
    if ((SEVERITY_RANK[update.severity] ?? -1) > SEVERITY_RANK[worst]) {
      worst = update.severity;
    }
  }
  return worst;
}

// Data Fetching with Fallback
async function loadIncidentsData() {
  let lastErr = null;
  for (const url of DATA_URLS) {
    try {
      const resp = await fetch(url);
      if (resp.ok) {
        return await resp.json();
      }
    } catch (e) {
      lastErr = e;
    }
  }
  throw new Error(lastErr ? lastErr.message : "Failed to load incidents dataset");
}

async function loadMetadata() {
  for (const url of METADATA_URLS) {
    try {
      const resp = await fetch(url);
      if (resp.ok) {
        return await resp.json();
      }
    } catch (_) { /* ignore */ }
  }
  return null;
}

// Toast Notifications
function showToast(message) {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.innerHTML = `
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
      <polyline points="22 4 12 14.01 9 11.01"></polyline>
    </svg>
    <span>${escapeHtml(message)}</span>
  `;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(8px)";
    setTimeout(() => toast.remove(), 250);
  }, 2600);
}

// Theme Management
function initTheme() {
  document.documentElement.setAttribute("data-theme", state.theme);
  const btn = document.getElementById("themeToggleBtn");
  if (btn) {
    btn.addEventListener("click", () => {
      state.theme = state.theme === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", state.theme);
      localStorage.setItem("theme", state.theme);
    });
  }
}

// Modal Inspector Dialog
function openModal(incident) {
  state.activeModalIncident = incident;
  const modal = document.getElementById("incidentModal");
  const title = document.getElementById("modalTitle");
  const sub = document.getElementById("modalSub");
  const body = document.getElementById("modalBody");
  if (!modal || !title || !body) return;

  const regLabel = regionLabel(incident) || "Global";
  const updates = incident.updates || [];
  const worstSev = worstSeverityFromUpdates(incident);

  title.textContent = incident.title;
  if (sub) sub.textContent = `${regLabel} · ${updates.length} update(s) · Started ${fmtDate(updates[0]?.published)}`;

  let servicesHtml = "";
  if (incident.services) {
    const list = Object.entries(incident.services).map(([slug, svc]) => `
      <div class="service-chip">
        <span class="dot dot-${svc.current || "unknown"}"></span>
        <span class="service-chip-name">${escapeHtml(svc.service_name || slug)}: ${escapeHtml(SEVERITY_LABEL[svc.current] || svc.current)}</span>
      </div>
    `).join("");
    servicesHtml = `
      <div style="margin-bottom:16px;">
        <h5 style="margin:0 0 8px;font-size:0.82rem;text-transform:uppercase;color:var(--text-muted);">Impacted Services (${Object.keys(incident.services).length})</h5>
        <div class="service-grid">${list}</div>
      </div>
    `;
  }

  const timelineHtml = `
    <ul class="timeline">
      ${updates.map(u => `
        <li>
          <div class="timeline-meta">
            <span class="dot dot-${u.severity}"></span>
            <span class="timeline-time">${fmtDate(u.published)}</span>
            <span class="badge badge-${u.severity}">${SEVERITY_LABEL[u.severity] ?? u.severity}</span>
          </div>
          <div class="timeline-desc">${escapeHtml(u.description) || "—"}</div>
        </li>
      `).join("")}
    </ul>
  `;

  body.innerHTML = `
    <div style="display:flex;gap:8px;align-items:center;margin-bottom:16px;">
      <span class="badge badge-${worstSev}">${SEVERITY_LABEL[worstSev] ?? worstSev}</span>
      <span class="incident-region">${escapeHtml(regLabel)}</span>
      <span style="margin-left:auto;font-size:0.75rem;color:var(--text-subtle);font-family:monospace;">Key: ${escapeHtml(incident.key)}</span>
    </div>
    ${servicesHtml}
    <h5 style="margin:0 0 8px;font-size:0.82rem;text-transform:uppercase;color:var(--text-muted);">Update History Logs</h5>
    ${timelineHtml}
  `;

  modal.hidden = false;
}

function closeModal() {
  const modal = document.getElementById("incidentModal");
  if (modal) modal.hidden = true;
  state.activeModalIncident = null;
}

// Build Day Map for Timeline Strip
function buildDayMap(incidents) {
  const byDay = {};
  let firstDay = null;
  let lastDay = null;
  for (const incident of incidents) {
    for (const update of incident.updates || []) {
      const key = dayKey(update.published);
      (byDay[key] = byDay[key] || []).push({
        severity: update.severity,
        title: update.title,
        incidentTitle: incident.title,
        incidentKey: incident.key,
      });
      if (!firstDay || key < firstDay) firstDay = key;
      if (!lastDay || key > lastDay) lastDay = key;
    }
  }
  return { byDay, firstDay, lastDay };
}

// Compute Overall Health Stats & Incident-Free Rate
function computeIncidentFreeStats(incidents, byDay, firstDay, lastDay) {
  if (!firstDay || !lastDay) {
    return { incidentFreeRate: 1.0, observedDays: 0, cleanDays: 0, calendarDays: 0, impactedDays: 0, noDataDays: 0 };
  }
  const startMs = dayToMs(firstDay);
  const endMs = dayToMs(lastDay);
  const calendarDays = Math.max(1, Math.round((endMs - startMs) / 86400000) + 1);
  const observedDays = Object.keys(byDay).length;

  let impactedDays = 0;
  for (const key in byDay) {
    const worst = worstSeverity(byDay[key].map((u) => u.severity));
    if (worst !== "operational" && worst !== "unknown" && worst !== "no_data") {
      impactedDays += 1;
    }
  }
  const cleanDays = observedDays - impactedDays;
  const noDataDays = calendarDays - observedDays;
  const incidentFreeRate = observedDays > 0 ? Math.max(0, cleanDays / observedDays) : 1.0;
  return { incidentFreeRate, observedDays, cleanDays, calendarDays, impactedDays, noDataDays };
}

// Render KPI Summary Stats Cards
function renderStatsCards(incidents) {
  const container = document.getElementById("summaryStats");
  if (!container) return;

  const dayMap = buildDayMap(incidents);
  const { incidentFreeRate, cleanDays, calendarDays, impactedDays, noDataDays, observedDays } = computeIncidentFreeStats(
    incidents,
    dayMap.byDay,
    dayMap.firstDay,
    dayMap.lastDay
  );

  const totalUpdates = incidents.reduce((sum, i) => sum + (i.updates ? i.updates.length : 0), 0);

  // Region count
  const regionsSet = new Set();
  incidents.forEach((i) => {
    const r = regionLabel(i);
    if (r) regionsSet.add(r);
  });

  const rateFormatted = (incidentFreeRate * 100).toFixed(1) + "%";

  // Scope label for filtered vs global
  let scopeLabel = "Global archive";
  if (state.activeRegion) {
    scopeLabel = `Filtered to ${state.activeRegion}`;
  } else if (state.activeSeverity !== "all") {
    scopeLabel = `Filtered to ${SEVERITY_LABEL[state.activeSeverity] || state.activeSeverity}`;
  }

  container.innerHTML = `
    <div class="stat-card">
      <div class="stat-label">Incident-Free Rate</div>
      <div class="stat-value stat-val-operational">${rateFormatted}</div>
      <div class="stat-sub">${cleanDays} of ${observedDays} observed days</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Total Incidents</div>
      <div class="stat-value">${incidents.length}</div>
      <div class="stat-sub">${totalUpdates} status updates</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Impacted Days</div>
      <div class="stat-value ${impactedDays > 0 ? "stat-val-degraded" : "stat-val-operational"}">${impactedDays}</div>
      <div class="stat-sub">Days with active incidents</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Archive Coverage</div>
      <div class="stat-value">${observedDays}d</div>
      <div class="stat-sub">${noDataDays > 0 ? noDataDays + " days unknown · " : ""}${scopeLabel}</div>
    </div>
  `;
}

// Render Regions Sidebar Navigation
function renderSidebar(allIncidents) {
  const container = document.getElementById("regionList");
  const totalBadge = document.getElementById("regionTotalBadge");
  const mobileList = document.getElementById("mobileRegionList");
  if (!container) return;

  const counts = {};
  for (const inc of allIncidents) {
    const label = regionLabel(inc);
    if (label) {
      counts[label] = (counts[label] || 0) + 1;
    }
  }

  const entries = Object.entries(counts).sort((a, b) => a[0].localeCompare(b[0]));
  if (totalBadge) totalBadge.textContent = entries.length;

  const query = state.regionSearchQuery.toLowerCase();
  const filteredEntries = entries.filter(([label]) => label.toLowerCase().includes(query));

  const items = [];
  const allActiveClass = state.activeRegion === null ? "sidebar-item active" : "sidebar-item";
  items.push(`
    <a class="${allActiveClass}" data-region="" href="#">
      <span>All Regions</span>
      <span class="sidebar-count">${allIncidents.length}</span>
    </a>
  `);

  for (const [label, count] of filteredEntries) {
    const isActive = state.activeRegion === label;
    const cls = isActive ? "sidebar-item active" : "sidebar-item";
    items.push(`
      <a class="${cls}" data-region="${escapeHtml(label)}" href="#region=${encodeURIComponent(label)}">
        <span class="region-item-name">${escapeHtml(label)}</span>
        <span class="sidebar-count">${count}</span>
      </a>
    `);
  }

  container.innerHTML = items.join("");

  // Mobile horizontal region tab buttons
  if (mobileList) {
    const mobileBtns = entries.map(([label]) => {
      const activeCls = state.activeRegion === label ? "mobile-region-btn active" : "mobile-region-btn";
      return `<button type="button" class="${activeCls}" data-region="${escapeHtml(label)}">${escapeHtml(label)}</button>`;
    });
    mobileList.innerHTML = mobileBtns.join("");
  }
}

// Render Heatmap Strip Timeline
function renderDayStrip(incidents) {
  const { byDay, firstDay, lastDay } = buildDayMap(incidents);
  const strip = document.getElementById("daysStrip");
  const controls = document.getElementById("stripControls");
  const windowLabel = document.getElementById("stripWindowLabel");
  const labels = document.querySelectorAll(".strip-axis span");

  if (!strip || !firstDay) {
    if (strip) strip.hidden = true;
    if (controls) controls.hidden = true;
    return { days: [], byDay: {} };
  }

  strip.hidden = false;
  strip.innerHTML = "";
  state.stripFirstDay = firstDay;

  const today = todayKey();
  const maxDay = lastDay > today ? lastDay : today;
  const totalDays = Math.round((dayToMs(maxDay) - dayToMs(firstDay)) / 86400000) + 1;
  const historyBeyondWindow = totalDays > state.windowDays;

  if (!historyBeyondWindow) {
    state.stripWindowEnd = maxDay;
    state.stripShowAll = true;
  }

  if (state.stripWindowEnd === null || state.stripWindowEnd > maxDay) state.stripWindowEnd = maxDay;
  if (state.stripWindowEnd < firstDay) state.stripWindowEnd = firstDay;
  if (state.stripShowAll) state.stripWindowEnd = maxDay;

  const endDay = state.stripWindowEnd;
  let startDay = state.stripShowAll ? firstDay : addDays(endDay, -(state.windowDays - 1));
  if (startDay < firstDay) startDay = firstDay;

  const startMs = dayToMs(startDay);
  const endMs = dayToMs(endDay);

  const days = [];
  let index = 0;

  for (let ms = startMs; ms <= endMs; ms += 86400000, index++) {
    const key = keyFromMs(ms);
    days.push(key);
    const updates = byDay[key];
    const sev = updates ? worstSeverity(updates.map((u) => u.severity)) : "no_data";

    const cell = document.createElement("span");
    const isSelected = state.activeDate === key;
    cell.className = `bar bar-${sev}${isSelected ? " bar-selected" : ""}`;
    cell.dataset.dayIndex = String(index);
    cell.dataset.day = key;
    cell.tabIndex = 0;
    strip.appendChild(cell);
  }

  if (labels && labels.length >= 3) {
    labels[0].textContent = fmtShortDate(startDay);
    labels[2].textContent = endDay === maxDay ? "Latest (" + fmtShortDate(endDay) + ")" : fmtShortDate(endDay);
  }

  // Update strip controls UI
  if (controls) {
    controls.hidden = !historyBeyondWindow;
    const prevBtn = document.getElementById("stripPrev");
    const nextBtn = document.getElementById("stripNext");
    const todayBtn = document.getElementById("stripToday");
    const allBtn = document.getElementById("stripAll");

    if (prevBtn) prevBtn.disabled = state.stripShowAll || state.stripWindowEnd <= addDays(firstDay, state.windowDays - 1);
    if (nextBtn) nextBtn.disabled = state.stripShowAll || state.stripWindowEnd >= maxDay;
    if (todayBtn) todayBtn.disabled = state.stripShowAll || state.stripWindowEnd >= maxDay;
    if (allBtn) allBtn.classList.toggle("strip-btn-active", state.stripShowAll);

    if (windowLabel) {
      windowLabel.textContent = state.stripShowAll
        ? `All available data (${totalDays} calendar days)`
        : `Showing last ${state.windowDays} calendar days`;
    }
  }

  return { days, byDay };
}

// Tooltip Popover & Interactivity for Heatmap Strip
function attachStripTooltip(stripState) {
  const strip = document.getElementById("daysStrip");
  const tooltip = document.getElementById("stripTooltip");
  const stage = document.getElementById("stripStage");
  if (!strip || !tooltip || !stage) return;

  function positionTooltip(target) {
    const stageRect = stage.getBoundingClientRect();
    const barRect = target.getBoundingClientRect();

    let left = barRect.left - stageRect.left + barRect.width / 2;
    left = Math.max(110, Math.min(left, stageRect.width - 110));

    tooltip.style.left = `${left}px`;
    tooltip.style.top = `-10px`;
  }

  function show(target) {
    const day = target.dataset.day;
    if (!day) return;

    const updates = stripState.byDay[day] || [];
    const severity = updates.length ? worstSeverity(updates.map((u) => u.severity)) : "no_data";

    const uniqueTitles = [...new Set(updates.map((u) => u.incidentTitle || u.title))].slice(0, 3);

    const titleListHtml = uniqueTitles.length
      ? `<ul class="tooltip-incidents-list">
          ${uniqueTitles.map((t) => `<li>• ${escapeHtml(t)}</li>`).join("")}
          ${updates.length > 3 ? `<li>+ ${updates.length - 3} more update(s)</li>` : ""}
         </ul>`
      : "";

    tooltip.innerHTML = `
      <div class="tooltip-date">${fmtShortDay(day)}</div>
      <div class="tooltip-summary">
        <span class="dot dot-${severity}"></span>
        <span>${SEVERITY_LABEL[severity] ?? (severity === "no_data" ? "No Data Available" : severity)}</span>
        ${updates.length ? `<span style="margin-left:auto;font-size:0.75rem;color:var(--text-subtle);">${updates.length} event(s)</span>` : ""}
      </div>
      ${titleListHtml}
      <div style="margin-top:6px;font-size:0.7rem;color:var(--accent-primary);">Click bar to filter date</div>
    `;

    tooltip.classList.add("active");
    tooltip.setAttribute("aria-hidden", "false");
    positionTooltip(target);
  }

  function hide() {
    tooltip.classList.remove("active");
    tooltip.setAttribute("aria-hidden", "true");
  }

  // Mouse / Pointer listeners
  strip.addEventListener("pointerover", (e) => {
    const bar = e.target.closest(".bar");
    if (bar) show(bar);
  });
  strip.addEventListener("pointerleave", hide);

  strip.addEventListener("focusin", (e) => {
    if (e.target.classList.contains("bar")) show(e.target);
  });
  strip.addEventListener("focusout", hide);

  // Click on bar filters date!
  strip.addEventListener("click", (e) => {
    const bar = e.target.closest(".bar");
    if (!bar) return;
    const clickedDay = bar.dataset.day;
    if (state.activeDate === clickedDay) {
      state.activeDate = null; // toggle off
    } else {
      state.activeDate = clickedDay;
    }
    renderAll();
  });
}

// Render Service Status breakdown block per region
function renderRegionServiceStates(incidents) {
  const container = document.getElementById("regionServices");
  if (!container) return;

  const byRegion = {};
  for (const inc of incidents) {
    if (!inc.region) continue;
    (byRegion[inc.region] = byRegion[inc.region] || []).push(inc);
  }

  const codes = Object.keys(byRegion).sort((a, b) =>
    (regionLabel(byRegion[a][0]) || a).localeCompare(regionLabel(byRegion[b][0]) || b)
  );

  const blocks = [];

  for (const code of codes) {
    const regionIncidents = byRegion[code];
    const label = regionLabel(regionIncidents[0]) || code;

    if (state.activeRegion && label !== state.activeRegion) continue;

    const services = {};
    let fullMap = false;

    for (const inc of regionIncidents) {
      if (inc.services) {
        fullMap = true;
        Object.assign(services, inc.services);
      }
    }

    if (!fullMap) {
      for (const inc of regionIncidents) {
        const slug = inc.service;
        const worst = worstSeverityFromUpdates(inc);
        if (!services[slug] || (SEVERITY_RANK[worst] ?? -1) > SEVERITY_RANK[services[slug].current]) {
          services[slug] = {
            service_name: inc.service_name || slug,
            current: worst,
          };
        }
      }
    }

    let serviceEntries = Object.entries(services).sort((a, b) =>
      (a[1].service_name || a[0]).localeCompare(b[1].service_name || b[0])
    );

    if (state.impactedServicesOnly) {
      serviceEntries = serviceEntries.filter(
        ([, svc]) => svc.current && svc.current !== "operational" && svc.current !== "none"
      );
    }

    if (serviceEntries.length === 0) continue;

    let worst = "unknown";
    let impactedCount = 0;
    for (const [, svc] of serviceEntries) {
      const cur = svc.current || "unknown";
      if (SEVERITY_RANK[cur] > SEVERITY_RANK[worst]) worst = cur;
      if (cur !== "operational" && cur !== "none" && cur !== "unknown") impactedCount++;
    }

    const chips = serviceEntries
      .map(([slug, svc]) => {
        const sev = svc.current || "unknown";
        const sevLabel = SEVERITY_LABEL[sev] ?? sev;
        return `
          <span class="service-chip" title="${sevLabel} · ${escapeHtml(svc.service_name || slug)}">
            <span class="dot dot-${sev}"></span>
            <span class="service-chip-name">${escapeHtml(svc.service_name || slug)}</span>
          </span>
        `;
      })
      .join("");

    const badgeCls = `badge badge-${worst}`;
    const badgeLabel = SEVERITY_LABEL[worst] ?? worst;

    blocks.push(`
      <div class="region-services-block">
        <div class="region-aggregate">
          <span class="region-aggregate-label">${escapeHtml(label)}</span>
          <span class="${badgeCls}">${badgeLabel}</span>
          <span class="region-aggregate-text">${impactedCount} of ${serviceEntries.length} services impacted</span>
        </div>
        <div class="service-grid">${chips}</div>
      </div>
    `);
  }

  container.innerHTML = blocks.join("");
}

// Render Individual Incident Cards
function renderIncidentCard(incident) {
  const updates = [...(incident.updates || [])].sort(
    (a, b) => new Date(a.published) - new Date(b.published)
  );

  const worstSev = worstSeverityFromUpdates(incident);
  const worstBadgeHtml = `<span class="badge badge-${worstSev}">${SEVERITY_LABEL[worstSev] ?? worstSev}</span>`;

  const regLabel = regionLabel(incident);
  const regionBadge = regLabel
    ? `<span class="incident-region">${escapeHtml(regLabel)}</span>`
    : "";

  // Duration calculation
  let durationStr = "";
  if (updates.length > 1) {
    const startMs = new Date(updates[0].published).getTime();
    const endMs = new Date(updates[updates.length - 1].published).getTime();
    const diffMins = Math.round((endMs - startMs) / 60000);
    if (diffMins > 0) {
      const hrs = Math.floor(diffMins / 60);
      const mins = diffMins % 60;
        durationStr = ` · Updates span: ${hrs > 0 ? `${hrs}h ` : ""}${mins}m`;
    }
  }

  const article = document.createElement("article");
  article.className = `incident sev-${worstSev}`;
  article.id = `incident-${encodeURIComponent(incident.key)}`;
  article.dataset.key = incident.key;

  article.innerHTML = `
    <div class="incident-head">
      <div class="incident-title-row">
        <h4 class="incident-title-btn" style="cursor:pointer;" title="Click to view details">${escapeHtml(incident.title)}</h4>
        ${regionBadge}
      </div>
      <div class="incident-badges">
        ${worstBadgeHtml}
        <button type="button" class="icon-btn copy-link-btn" data-key="${escapeHtml(incident.key)}" title="Copy permalink to incident">
          🔗 Copy Link
        </button>
      </div>
    </div>

    <div class="incident-meta">
      <span>${fmtDate(updates[0]?.published)}</span>
      <span>→</span>
      <span>${fmtDate(updates[updates.length - 1]?.published)}</span>
      <span class="muted">· ${updates.length} update(s)${durationStr}</span>
    </div>

    <ul class="timeline">
      ${updates
        .map(
          (u) => `
        <li>
          <div class="timeline-meta">
            <span class="dot dot-${u.severity}"></span>
            <span class="timeline-time">${fmtDate(u.published)}</span>
            <span class="badge badge-${u.severity}">${SEVERITY_LABEL[u.severity] ?? u.severity}</span>
          </div>
          <div class="timeline-desc">${escapeHtml(u.description) || "—"}</div>
        </li>`
        )
        .join("")}
    </ul>
  `;

  return article;
}

// Active Filter Chips Bar
function renderActiveFiltersBar() {
  const container = document.getElementById("activeFiltersBar");
  const chipsWrapper = document.getElementById("activeChipsContainer");
  if (!container || !chipsWrapper) return;

  const chips = [];

  if (state.activeRegion) {
    chips.push(`
      <span class="filter-chip">
        Region: ${escapeHtml(state.activeRegion)}
        <span class="filter-chip-remove" data-remove="region">✕</span>
      </span>
    `);
  }

  if (state.activeSeverity !== "all") {
    chips.push(`
      <span class="filter-chip">
        Severity: ${escapeHtml(SEVERITY_LABEL[state.activeSeverity] || state.activeSeverity)}
        <span class="filter-chip-remove" data-remove="severity">✕</span>
      </span>
    `);
  }

  if (state.activeDate) {
    chips.push(`
      <span class="filter-chip">
        Date: ${fmtShortDate(state.activeDate)}
        <span class="filter-chip-remove" data-remove="date">✕</span>
      </span>
    `);
  }

  if (state.searchQuery) {
    chips.push(`
      <span class="filter-chip">
        Query: "${escapeHtml(state.searchQuery)}"
        <span class="filter-chip-remove" data-remove="query">✕</span>
      </span>
    `);
  }

  if (chips.length > 0) {
    container.hidden = false;
    chipsWrapper.innerHTML = chips.join("");
  } else {
    container.hidden = true;
    chipsWrapper.innerHTML = "";
  }
}

// Apply Filters to Incident List
function filterIncidents(incidents) {
  return incidents.filter((inc) => {
    // 1. Region Filter
    if (state.activeRegion && regionLabel(inc) !== state.activeRegion) {
      return false;
    }

    // 2. Severity Filter
    if (state.activeSeverity !== "all") {
      const worst = worstSeverityFromUpdates(inc);
      if (worst !== state.activeSeverity) return false;
    }

    // 3. Date Filter (incident overlaps or has update on activeDate)
    if (state.activeDate) {
      const hasDate = (inc.updates || []).some(
        (u) => dayKey(u.published) === state.activeDate
      );
      if (!hasDate) return false;
    }

    // 4. Global Search Query
    if (state.searchQuery) {
      const q = state.searchQuery.toLowerCase();
      const matchTitle = inc.title && inc.title.toLowerCase().includes(q);
      const matchService = inc.service && inc.service.toLowerCase().includes(q);
      const matchDesc = (inc.updates || []).some(
        (u) => u.description && u.description.toLowerCase().includes(q)
      );
      if (!matchTitle && !matchService && !matchDesc) return false;
    }

    return true;
  });
}

// Sort Filtered Incidents
function sortIncidents(incidents) {
  const sorted = [...incidents];
  if (state.sortOrder === "newest") {
    sorted.sort((a, b) => new Date(b.started_at || 0) - new Date(a.started_at || 0));
  } else if (state.sortOrder === "oldest") {
    sorted.sort((a, b) => new Date(a.started_at || 0) - new Date(b.started_at || 0));
  } else if (state.sortOrder === "updates") {
    sorted.sort((a, b) => (b.updates ? b.updates.length : 0) - (a.updates ? a.updates.length : 0));
  }
  return sorted;
}

// Primary Render Orchestrator
function renderAll() {
  const filtered = filterIncidents(state.allIncidents);
  const sorted = sortIncidents(filtered);

  renderSidebar(state.allIncidents);
  renderStatsCards(filtered);
  renderRegionServiceStates(filtered);
  renderActiveFiltersBar();

  const stripState = renderDayStrip(filtered);
  attachStripTooltip(stripState);

  const list = document.getElementById("incidentList");
  const empty = document.getElementById("emptyState");
  const subtitle = document.getElementById("incidentListSubtitle");

  if (subtitle) {
    subtitle.textContent = `Showing ${sorted.length} of ${state.allIncidents.length} incidents`;
  }

  if (!list || !empty) return;
  list.innerHTML = "";

  if (sorted.length === 0) {
    empty.hidden = false;
  } else {
    empty.hidden = true;
    for (const incident of sorted) {
      list.appendChild(renderIncidentCard(incident));
    }
  }
}

// Parse Hash State from Location Bar
function parseUrlHash() {
  const hash = window.location.hash.slice(1);
  if (!hash) return;

  const params = new URLSearchParams(hash);
  const region = params.get("region");
  const date = params.get("date");
  const sev = params.get("sev");
  const incKey = params.get("incident");

  if (region) state.activeRegion = region;
  if (date) state.activeDate = date;
  if (sev) state.activeSeverity = sev;

  if (incKey) {
    const inc = state.allIncidents.find(i => i.key === incKey || i.key === decodeURIComponent(incKey));
    if (inc) {
      setTimeout(() => {
        openModal(inc);
        const card = document.getElementById(`incident-${encodeURIComponent(inc.key)}`);
        if (card) {
          card.scrollIntoView({ behavior: "smooth", block: "center" });
          card.classList.add("incident-highlight");
          setTimeout(() => card.classList.remove("incident-highlight"), 3000);
        }
      }, 100);
    }
  }
}

// Data Export Handler (CSV & JSON)
function exportDataset() {
  const filtered = filterIncidents(state.allIncidents);
  const jsonBlob = new Blob([JSON.stringify(filtered, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(jsonBlob);

  const a = document.createElement("a");
  a.href = url;
  a.download = `aws-status-archive-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);

  showToast(`Exported ${filtered.length} incidents to JSON`);
}

// Attach Event Listeners
function setupEventListeners() {
  // Region Selection Click (Desktop Sidebar)
  const regionList = document.getElementById("regionList");
  if (regionList) {
    regionList.addEventListener("click", (e) => {
      const link = e.target.closest(".sidebar-item");
      if (!link) return;
      e.preventDefault();
      const region = link.dataset.region || null;
      state.activeRegion = region;
      renderAll();
    });
  }

  // Mobile Region Tabs
  const mobileList = document.getElementById("mobileRegionList");
  if (mobileList) {
    mobileList.addEventListener("click", (e) => {
      const btn = e.target.closest(".mobile-region-btn");
      if (!btn) return;
      state.activeRegion = btn.dataset.region || null;
      renderAll();
    });
  }

  // Sidebar Region Search Input
  const sidebarSearch = document.getElementById("sidebarSearchInput");
  if (sidebarSearch) {
    sidebarSearch.addEventListener("input", (e) => {
      state.regionSearchQuery = e.target.value;
      renderSidebar(state.allIncidents);
    });
  }

  // Global Search Input
  const globalSearch = document.getElementById("globalSearchInput");
  const clearBtn = document.getElementById("searchClearBtn");
  if (globalSearch) {
    globalSearch.addEventListener("input", (e) => {
      state.searchQuery = e.target.value;
      if (clearBtn) clearBtn.hidden = !e.target.value;
      renderAll();
    });
  }
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      state.searchQuery = "";
      if (globalSearch) globalSearch.value = "";
      clearBtn.hidden = true;
      renderAll();
    });
  }

  // Severity Filter Buttons
  const sevGroup = document.querySelector(".severity-filter-group");
  if (sevGroup) {
    sevGroup.addEventListener("click", (e) => {
      const btn = e.target.closest(".sev-filter-btn");
      if (!btn) return;
      sevGroup.querySelectorAll(".sev-filter-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.activeSeverity = btn.dataset.severity || "all";
      renderAll();
    });
  }

  // Active Filter Chips Removal
  const chipsContainer = document.getElementById("activeChipsContainer");
  if (chipsContainer) {
    chipsContainer.addEventListener("click", (e) => {
      const removeBtn = e.target.closest(".filter-chip-remove");
      if (!removeBtn) return;
      const type = removeBtn.dataset.remove;
      if (type === "region") state.activeRegion = null;
      if (type === "severity") state.activeSeverity = "all";
      if (type === "date") state.activeDate = null;
      if (type === "query") {
        state.searchQuery = "";
        const gs = document.getElementById("globalSearchInput");
        if (gs) gs.value = "";
      }
      renderAll();
    });
  }

  // Clear All Filters Button
  const clearAllBtn = document.getElementById("clearAllFiltersBtn");
  const emptyResetBtn = document.getElementById("emptyStateResetBtn");
  const resetHandler = () => {
    state.activeRegion = null;
    state.activeSeverity = "all";
    state.activeDate = null;
    state.searchQuery = "";
    const gs = document.getElementById("globalSearchInput");
    if (gs) gs.value = "";
    document.querySelectorAll(".sev-filter-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.severity === "all");
    });
    renderAll();
  };
  if (clearAllBtn) clearAllBtn.addEventListener("click", resetHandler);
  if (emptyResetBtn) emptyResetBtn.addEventListener("click", resetHandler);

  // Impacted Services Only Toggle
  const impactedToggle = document.getElementById("impactedOnlyToggle");
  if (impactedToggle) {
    impactedToggle.addEventListener("change", (e) => {
      state.impactedServicesOnly = e.target.checked;
      renderAll();
    });
  }

  // Incident Sort Select
  const sortSelect = document.getElementById("incidentSortSelect");
  if (sortSelect) {
    sortSelect.addEventListener("change", (e) => {
      state.sortOrder = e.target.value;
      renderAll();
    });
  }

  // Export Button
  const exportBtn = document.getElementById("exportDataBtn");
  if (exportBtn) exportBtn.addEventListener("click", exportDataset);

  // Modal event listeners
  const modalClose = document.getElementById("modalCloseBtn");
  const modalOverlay = document.getElementById("incidentModal");
  const modalCopy = document.getElementById("modalCopyBtn");
  const modalRaw = document.getElementById("modalRawBtn");

  if (modalClose) modalClose.addEventListener("click", closeModal);
  if (modalOverlay) {
    modalOverlay.addEventListener("click", (e) => {
      if (e.target === modalOverlay) closeModal();
    });
  }
  if (modalCopy) {
    modalCopy.addEventListener("click", () => {
      if (state.activeModalIncident) {
        const linkUrl = `${window.location.origin}${window.location.pathname}#incident=${encodeURIComponent(state.activeModalIncident.key)}`;
        navigator.clipboard.writeText(linkUrl).then(() => {
          showToast("Incident permalink copied!");
        });
      }
    });
  }
  if (modalRaw) {
    modalRaw.addEventListener("click", () => {
      if (state.activeModalIncident) {
        const jsonStr = JSON.stringify(state.activeModalIncident, null, 2);
        const w = window.open();
        if (w) {
          w.document.write(`<pre style="font-family:monospace;padding:16px;background:#0f172a;color:#f8fafc;white-space:pre-wrap;">${escapeHtml(jsonStr)}</pre>`);
        }
      }
    });
  }

  // Incident title click opens Modal
  const incidentList = document.getElementById("incidentList");
  if (incidentList) {
    incidentList.addEventListener("click", (e) => {
      const titleBtn = e.target.closest(".incident-title-btn");
      if (!titleBtn) return;
      const card = titleBtn.closest(".incident");
      if (!card) return;
      const key = card.dataset.key;
      const inc = state.allIncidents.find(i => i.key === key);
      if (inc) openModal(inc);
    });
  }

  // Keyboard shortcut (Escape closes modal)
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });

  // Copy Permalink Delegation
  document.addEventListener("click", (e) => {
    const copyBtn = e.target.closest(".copy-link-btn");
    if (!copyBtn) return;
    const key = copyBtn.dataset.key;
    const linkUrl = `${window.location.origin}${window.location.pathname}#incident=${encodeURIComponent(key)}`;
    navigator.clipboard.writeText(linkUrl).then(() => {
      showToast("Incident permalink copied to clipboard!");
    });
  });

  // Strip Navigation Controls
  const prevBtn = document.getElementById("stripPrev");
  const nextBtn = document.getElementById("stripNext");
  const todayBtn = document.getElementById("stripToday");
  const allBtn = document.getElementById("stripAll");

  if (prevBtn) {
    prevBtn.addEventListener("click", () => {
      if (!state.stripShowAll) state.stripWindowEnd = addDays(state.stripWindowEnd, -state.windowDays);
      renderAll();
    });
  }
  if (nextBtn) {
    nextBtn.addEventListener("click", () => {
      if (!state.stripShowAll) state.stripWindowEnd = addDays(state.stripWindowEnd, state.windowDays);
      renderAll();
    });
  }
  if (todayBtn) {
    todayBtn.addEventListener("click", () => {
      state.stripShowAll = false;
      state.stripWindowEnd = todayKey();
      renderAll();
    });
  }
  if (allBtn) {
    allBtn.addEventListener("click", () => {
      state.stripShowAll = !state.stripShowAll;
      if (state.stripShowAll) state.stripWindowEnd = null;
      renderAll();
    });
  }
}

// Application Entry Point
async function init() {
  initTheme();
  setupEventListeners();

  const updatedAtEl = document.getElementById("updatedAt");
  try {
    const [incidents, metadata] = await Promise.all([
      loadIncidentsData(),
      loadMetadata(),
    ]);
    state.allIncidents = incidents;
    state.archiveMetadata = metadata;

    parseUrlHash();
    renderAll();

    if (updatedAtEl) {
      const totalUpdates = incidents.reduce((sum, i) => sum + (i.updates ? i.updates.length : 0), 0);
      const freshness = metadata && metadata.archive_latest_date
        ? ` · Archive covers ${metadata.archive_earliest_date} to ${metadata.archive_latest_date}`
        : "";
      updatedAtEl.textContent = `${incidents.length} incidents · ${totalUpdates} updates${freshness}`;
    }
  } catch (err) {
    console.error("Initialization error:", err);
    if (updatedAtEl) {
      updatedAtEl.textContent = "Error loading archived data";
    }
    const list = document.getElementById("incidentList");
    const empty = document.getElementById("emptyState");
    if (list && empty) {
      list.innerHTML = "";
      empty.hidden = false;
      empty.innerHTML = `
        <div style="color:var(--impacted);font-weight:600;margin-bottom:8px;">Failed to load status archive dataset</div>
        <div style="font-size:0.8rem;color:var(--text-muted);">${escapeHtml(err.message)}</div>
      `;
    }
  }
}

document.addEventListener("DOMContentLoaded", init);