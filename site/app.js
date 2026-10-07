/**
 * status-archive front end.
 *
 * Renders the archived AWS incident history from parsed/incidents.json:
 * an overview with a daily status strip, the incidents that are still open,
 * and a paged incident log with a detail dialog. All state lives in `state`
 * and every change goes through render().
 */

const DATA_URL = "parsed/incidents.json";
const METADATA_URL = "parsed/metadata.json";
const PAGE_SIZE = 20;
const GRID_PAGE_SIZE = 25;
const GRID_DAYS = 7;
const DAY_MS = 86400000;
const GLOBAL_REGION = "Global Services";

// AWS numeric order: impacted (1) < degraded (2) < disrupted (3).
const SEVERITY_RANK = {
  disrupted: 3,
  degraded: 2,
  impacted: 1,
  informational: 0.5,
  operational: 0,
  resolved: 0,
  unknown: -1,
  no_data: -2,
};

const SEVERITY_LABEL = {
  disrupted: "Disrupted",
  degraded: "Degraded",
  impacted: "Impacted",
  informational: "Informational",
  operational: "Operating normally",
  resolved: "Resolved",
  unknown: "Unknown",
  no_data: "No data",
};

const FILTER_SEVERITIES = ["all", "disrupted", "degraded", "impacted"];
const THEME_MODES = ["auto", "light", "dark"];
const THEME_LABEL = { auto: "Theme: match system", light: "Theme: light", dark: "Theme: dark" };

const state = {
  incidents: [],
  metadata: null,
  region: null,
  severity: "all",
  date: null,
  query: "",
  regionQuery: "",
  sort: "newest",
  page: 1,
  view: "services",
  serviceRows: [],
  gridEnd: null,
  gridOnlyEvents: true,
  gridPage: 1,
  gridSubtitle: "",
  eventsSubtitle: "",
  calScale: window.innerWidth < 600 ? "month" : "year",
  calYear: null,
  calMonth: null,
  stripFocusDay: null,
  stripByDay: {},
  archiveSpan: null,
  modalIncident: null,
  lastFocus: null,
};

/* ---------- Small utilities ---------- */

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// AWS descriptions sometimes carry <a href> links: keep only plain http(s)
// anchors and escape everything else.
function renderDescription(text) {
  return escapeHtml(text).replace(
    /&lt;a\s+href=(?:&quot;|&#39;)(https?:\/\/[^"'\s<>]+?)(?:&quot;|&#39;)[^&]*?&gt;(.*?)&lt;\/a&gt;/gi,
    (_, href, label) => `<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`
  );
}

function plainText(text) {
  return String(text ?? "").replace(/<[^>]*>/g, "").replace(/\s+/g, " ").trim();
}

function plural(n, word, pluralWord = `${word}s`) {
  return `${n.toLocaleString("en-US")} ${n === 1 ? word : pluralWord}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function fmtDay(key) {
  if (!key) return "—";
  const [y, m, d] = key.split("-").map(Number);
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

function fmtDayWithWeekday(key) {
  return `${WEEKDAYS[new Date(dayToMs(key)).getUTCDay()]}, ${fmtDay(key)}`;
}

function fmtDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()} ${hh}:${mm} UTC`;
}

function fmtDuration(startIso, endIso) {
  const minutes = Math.round((new Date(endIso) - new Date(startIso)) / 60000);
  if (!Number.isFinite(minutes) || minutes <= 0) return null;
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const mins = minutes % 60;
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${mins}m`;
  return `${mins}m`;
}

function dayKey(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.toISOString().slice(0, 10);
}

function dayToMs(key) {
  const [y, m, d] = key.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

function addDays(key, n) {
  return new Date(dayToMs(key) + n * DAY_MS).toISOString().slice(0, 10);
}

function daysBetween(a, b) {
  return Math.round((dayToMs(b) - dayToMs(a)) / DAY_MS);
}

function todayKey() {
  return new Date().toISOString().slice(0, 10);
}

function worstOf(severities) {
  let worst = "unknown";
  for (const s of severities) {
    if ((SEVERITY_RANK[s] ?? -1) > (SEVERITY_RANK[worst] ?? -1)) worst = s;
  }
  return worst;
}

function severityDot(severity) {
  return `<span class="dot dot-${escapeHtml(severity)}" aria-hidden="true"></span>`;
}

function severityBadge(severity) {
  return `<span class="badge">${severityDot(severity)}${escapeHtml(SEVERITY_LABEL[severity] || severity)}</span>`;
}

const SEVERITY_ICON = {
  disrupted: '<circle cx="12" cy="12" r="9"></circle><path d="M9 9l6 6M15 9l-6 6"></path>',
  degraded: '<path d="M12 4l9 16H3z"></path><path d="M12 10v4M12 17v.01"></path>',
  impacted: '<circle cx="12" cy="12" r="9"></circle><path d="M12 7.5v5.5M12 16.5v.01"></path>',
  resolved: '<circle cx="12" cy="12" r="9"></circle><path d="M8 12.5l3 3 5-6"></path>',
};

function severityIcon(severity) {
  const body = SEVERITY_ICON[severity] || '<circle cx="12" cy="12" r="9"></circle>';
  return `<svg class="sev-icon sev-color-${escapeHtml(severity)}" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
}

function storageGet(key) {
  try {
    return localStorage.getItem(key);
  } catch (_) {
    return null;
  }
}

function storageSet(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (_) {
    /* storage blocked: the choice just won't persist */
  }
}

/* ---------- Data preparation ---------- */

// "https://status.aws.amazon.com/#ec2-us-east-1_1790033208" -> "ec2-us-east-1_1790033208"
function shortKey(key) {
  return String(key).split("#").pop();
}

function prepare(incident) {
  const updates = [...(incident.updates || [])]
    .filter((u) => dayKey(u.published))
    .sort((a, b) => new Date(a.published) - new Date(b.published));
  const region =
    incident.region && incident.region !== "global"
      ? incident.region_name || incident.region
      : GLOBAL_REGION;
  const latest = updates[updates.length - 1] || null;
  const services = incident.services || {};
  const search = [
    incident.title,
    incident.service,
    incident.service_name,
    region,
    ...updates.map((u) => `${u.title} ${plainText(u.description)}`),
    ...Object.values(services).map((s) => s.service_name),
  ]
    .join(" ")
    .toLowerCase();

  // Status per day for as long as the incident lasted (to today if open).
  let days = {};
  const updateDays = {};
  if (updates.length) {
    const firstDay = dayKey(updates[0].published);
    const lastDay = incident.open ? todayKey() : dayKey(latest.published);
    days = dayStatuses(
      updates.map((u) => ({ at: new Date(u.published).getTime(), severity: u.severity })),
      firstDay,
      lastDay
    );
    for (const u of updates) {
      const key = dayKey(u.published);
      updateDays[key] = (updateDays[key] || 0) + 1;
    }
  }

  return {
    ...incident,
    _updates: updates,
    _days: days,
    _updateDays: updateDays,
    _region: region,
    _worst: worstOf(updates.map((u) => u.severity)),
    _latest: latest,
    _short: shortKey(incident.key),
    _search: search,
  };
}

// Severity of one day across the incidents active on it: the worst ongoing
// status, or "resolved" when the only activity was incidents recovering.
function daySeverity(entries) {
  if (!entries || entries.length === 0) return "no_data";
  const active = entries.map((e) => e.severity).filter((sev) => sev !== "resolved" && sev !== "operational");
  return active.length ? worstOf(active) : "resolved";
}

// Per-day status of one service across an incident. A status carries forward
// from the update that set it until the next one, so a multi-day incident
// fills every day it lasted; the day it recovers shows as "resolved".
function dayStatuses(timeline, firstDay, lastDay) {
  const out = {};
  let idx = 0;
  let carried = null;
  for (let key = firstDay; key <= lastDay; key = addDays(key, 1)) {
    const end = dayToMs(key) + DAY_MS;
    const today = [];
    while (idx < timeline.length && timeline[idx].at < end) {
      today.push(timeline[idx].severity);
      idx += 1;
    }
    const active = [carried, ...today].filter((sev) => sev && sev !== "operational");
    if (active.length) out[key] = worstOf(active);
    else if (today.includes("operational")) out[key] = "resolved";
    if (today.length) carried = today[today.length - 1];
  }
  return out;
}

// One row per service that ever had an archived event, with a status per day.
function buildServiceRows(incidents) {
  const rows = new Map();
  const today = todayKey();
  for (const incident of incidents) {
    if (incident._updates.length === 0) continue;
    const firstDay = dayKey(incident._updates[0].published);
    const lastUpdateDay = dayKey(incident._latest.published);
    const lastDay = incident.open ? today : lastUpdateDay;
    const incidentTimeline = incident._updates.map((u) => ({ at: new Date(u.published).getTime(), severity: u.severity }));

    const members = [[incident.service, incident.service_name || "Multiple services", incidentTimeline, lastDay]];
    for (const [slug, svc] of Object.entries(incident.services || {})) {
      if (slug === incident.service || !svc.max || svc.max === "operational") continue;
      const own = (svc.transitions || [])
        .map((t) => ({ at: new Date(t.published).getTime(), severity: t.severity }))
        .filter((t) => Number.isFinite(t.at))
        .sort((a, b) => a.at - b.at);
      // Without its own history a service follows the incident, but one AWS
      // already lists as recovered must not be carried forward to today.
      const until = !own.length && svc.current === "operational" ? lastUpdateDay : lastDay;
      members.push([slug, svc.service_name || slug, own.length ? own : incidentTimeline, until]);
    }

    for (const [slug, name, timeline, until] of members) {
      // Some service ids carry no region suffix, so the same id can appear in
      // incidents of different regions: a row is a service in one region.
      const rowKey = `${slug}|${incident._region}`;
      let row = rows.get(rowKey);
      if (!row) {
        row = { slug, name, region: incident._region, cells: {}, label: `${name} ${incident._region} ${slug}`.toLowerCase() };
        rows.set(rowKey, row);
      }
      const statuses = dayStatuses(timeline, firstDay, until);
      for (const day in statuses) {
        const existing = row.cells[day];
        if (!existing || SEVERITY_RANK[statuses[day]] > SEVERITY_RANK[existing.severity]) {
          row.cells[day] = { severity: statuses[day], incident };
        }
      }
    }
  }
  return [...rows.values()].sort((a, b) => a.name.localeCompare(b.name) || a.region.localeCompare(b.region));
}

/* ---------- Filtering ---------- */

function matches(incident, { ignoreDate = false } = {}) {
  if (state.region && incident._region !== state.region) return false;
  if (state.severity !== "all" && incident._worst !== state.severity) return false;
  if (!ignoreDate && state.date && !incident._days[state.date]) return false;
  if (state.query && !incident._search.includes(state.query.toLowerCase())) return false;
  return true;
}

function sortIncidents(list) {
  const byStart = (i) => new Date(i.started_at || 0).getTime();
  const sorted = [...list];
  if (state.sort === "oldest") sorted.sort((a, b) => byStart(a) - byStart(b));
  else if (state.sort === "updates") sorted.sort((a, b) => b._updates.length - a._updates.length);
  else sorted.sort((a, b) => byStart(b) - byStart(a));
  return sorted;
}

function buildDayMap(incidents) {
  const byDay = {};
  let first = null;
  let last = null;
  for (const incident of incidents) {
    for (const key in incident._days) {
      (byDay[key] = byDay[key] || []).push({
        severity: incident._days[key],
        incident,
        updates: incident._updateDays[key] || 0,
      });
      if (!first || key < first) first = key;
      if (!last || key > last) last = key;
    }
  }
  return { byDay, first, last };
}

/* ---------- Rendering ---------- */

function render() {
  syncControls();
  const base = state.incidents.filter((i) => matches(i, { ignoreDate: true }));
  const filtered = state.date ? base.filter((i) => matches(i)) : base;

  renderSidebar();
  renderStats(filtered);
  renderStrip(base);
  renderOpenIncidents();
  renderChips();
  renderList(sortIncidents(filtered));
  renderServiceGrid();
  renderView(filtered.length);
  renderHeaderMeta(filtered.length);
  writeHash();
}

function syncControls() {
  document.querySelectorAll("#severityFilter .seg-btn").forEach((btn) => {
    btn.setAttribute("aria-pressed", String(btn.dataset.severity === state.severity));
  });
  const search = $("globalSearchInput");
  if (search.value.trim() !== state.query) search.value = state.query;
  $("incidentSortSelect").value = state.sort;
}

function regionCounts() {
  const counts = new Map();
  for (const incident of state.incidents) {
    counts.set(incident._region, (counts.get(incident._region) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]));
}

function renderSidebar() {
  const entries = regionCounts();
  $("regionTotalBadge").textContent = entries.length;

  const q = state.regionQuery.toLowerCase();
  const items = [
    ["", "All regions", state.incidents.length],
    ...entries.filter(([name]) => name.toLowerCase().includes(q)).map(([name, count]) => [name, name, count]),
  ];
  $("regionList").innerHTML = items
    .map(([value, label, count]) => {
      const current = (state.region || "") === value;
      return `<a class="region-item" href="#" data-region="${escapeHtml(value)}"${current ? ' aria-current="true"' : ""}>
        <span class="region-name">${escapeHtml(label)}</span><span class="count-pill">${count}</span></a>`;
    })
    .join("");

  $("mobileRegionList").innerHTML = [["", "All regions"], ...entries.map(([name]) => [name, name])]
    .map(([value, label]) => {
      const pressed = (state.region || "") === value;
      return `<button type="button" class="region-pill" data-region="${escapeHtml(value)}" aria-pressed="${pressed}">${escapeHtml(label)}</button>`;
    })
    .join("");
}

function renderStats(incidents) {
  const { byDay, first, last } = buildDayMap(incidents);
  const totalUpdates = incidents.reduce((sum, i) => sum + i._updates.length, 0);
  let impactDays = 0;
  let resolvedDays = 0;
  for (const key in byDay) {
    const sev = daySeverity(byDay[key]);
    if (sev === "resolved") resolvedDays += 1;
    else if (SEVERITY_RANK[sev] > 0) impactDays += 1;
  }
  // Measure against the whole archive period so filtered views stay comparable.
  const span = state.archiveSpan;
  const spanDays = first && span ? daysBetween(span.first, span.last) + 1 : 0;
  const noDataDays = spanDays - Object.keys(byDay).length;

  const stat = (label, value, sub) => `
    <div class="stat">
      <div class="stat-label">${label}</div>
      <div class="stat-value">${value}</div>
      <div class="stat-sub">${sub}</div>
    </div>`;

  $("summaryStats").innerHTML = [
    stat("Incidents", incidents.length.toLocaleString("en-US"), plural(totalUpdates, "status update")),
    stat("Impact days", `${impactDays}<small> / ${spanDays}</small>`, "Days with an incident in progress"),
    stat("Resolved-only days", resolvedDays, "Days where incidents only recovered"),
    stat("No-data days", Math.max(0, noDataDays), "No incident open or updated"),
  ].join("");
}

const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

function monthKey(year, month, day = 1) {
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

// The calendar shows one year (a week-by-weekday heatmap) or one month (a bar
// per day), so it stays readable however many years the archive covers.
function renderStrip(incidents) {
  const { byDay, first } = buildDayMap(incidents);
  state.stripByDay = byDay;
  const strip = $("daysStrip");
  const hasData = Boolean(first);
  for (const id of ["calControls", "stripStage"]) $(id).hidden = !hasData;
  document.querySelector(".strip-axis").hidden = !hasData;
  document.querySelector(".legend").hidden = !hasData;
  if (!hasData) {
    strip.innerHTML = "";
    $("stripMonths").innerHTML = "";
    return;
  }

  const today = todayKey();
  const [firstYear, firstMonth] = [Number(first.slice(0, 4)), Number(first.slice(5, 7)) - 1];
  const [thisYear, thisMonth] = [Number(today.slice(0, 4)), Number(today.slice(5, 7)) - 1];
  const yearly = state.calScale === "year";

  // Clamp the cursor to the period the archive covers.
  let year = Math.min(Math.max(state.calYear ?? thisYear, firstYear), thisYear);
  let month = state.calMonth ?? thisMonth;
  if (year === firstYear && month < firstMonth) month = firstMonth;
  if (year === thisYear && month > thisMonth) month = thisMonth;
  state.calYear = year;
  state.calMonth = month;

  const start = yearly ? monthKey(year, 0) : monthKey(year, month);
  const end = yearly ? monthKey(year, 11, 31) : new Date(Date.UTC(year, month + 1, 0)).toISOString().slice(0, 10);
  const days = [];
  for (let key = start; key <= end; key = addDays(key, 1)) days.push(key);

  const selectable = days.filter((key) => key <= today);
  const focusDay = selectable.includes(state.stripFocusDay)
    ? state.stripFocusDay
    : selectable.includes(state.date)
      ? state.date
      : selectable[selectable.length - 1];

  const cell = (key) => {
    if (key > today) return '<span class="bar bar-future" aria-hidden="true"></span>';
    // The colour is that day's own updates; a line under it marks an incident
    // still in progress, so a months-long one doesn't hide the days around it.
    const entries = byDay[key] || [];
    const sev = daySeverity(entries.filter((e) => e.updates > 0));
    const ongoing = daySeverity(entries);
    const line = SEVERITY_RANK[ongoing] > 0 && SEVERITY_RANK[ongoing] > SEVERITY_RANK[sev] ? ongoing : null;
    const selected = key === state.date;
    const label = line
      ? `${fmtDay(key)}: ${sev === "no_data" ? "no new update" : SEVERITY_LABEL[sev]}, ${SEVERITY_LABEL[line].toLowerCase()} incident in progress`
      : `${fmtDay(key)}: ${SEVERITY_LABEL[sev]}`;
    return `<span class="bar bar-${sev}${line ? ` bar-ongoing ongoing-${line}` : ""}${selected ? " bar-selected" : ""}" role="button" data-day="${key}"
      tabindex="${key === focusDay ? 0 : -1}" aria-pressed="${selected}" aria-label="${escapeHtml(label)}"></span>`;
  };

  const months = $("stripMonths");
  if (yearly) {
    // Columns are weeks (Sunday on top); pad so Jan 1 lands on its weekday.
    const offset = new Date(dayToMs(start)).getUTCDay();
    const weeks = Math.ceil((offset + days.length) / 7);
    strip.className = "strip strip-year";
    strip.innerHTML = '<span class="bar-pad" aria-hidden="true"></span>'.repeat(offset) + days.map(cell).join("");
    months.hidden = false;
    months.style.gridTemplateColumns = `repeat(${weeks}, 1fr)`;
    months.innerHTML = MONTHS.map((name, m) => {
      const column = Math.floor((offset + daysBetween(start, monthKey(year, m))) / 7) + 1;
      const hasMonth = monthKey(year, m) <= today && monthKey(year, m, 28) >= first.slice(0, 8) + "01";
      return `<button type="button" class="month-label" style="grid-column:${column}" data-month="${m}"${hasMonth ? "" : " disabled"} aria-label="Open ${MONTH_NAMES[m]} ${year}">${name}</button>`;
    }).join("");
  } else {
    strip.className = "strip strip-month";
    strip.innerHTML = days.map(cell).join("");
    months.hidden = true;
    months.innerHTML = "";
  }

  $("stripWindowLabel").textContent = yearly ? String(year) : `${MONTH_NAMES[month]} ${year}`;
  $("stripStart").textContent = yearly ? "" : fmtDay(start);
  $("stripEnd").textContent = yearly ? "" : fmtDay(end);
  document.querySelector(".strip-axis").hidden = yearly;

  const atStart = yearly ? year <= firstYear : year === firstYear && month <= firstMonth;
  const atEnd = yearly ? year >= thisYear : year === thisYear && month >= thisMonth;
  $("stripPrev").disabled = atStart;
  $("stripNext").disabled = atEnd;
  $("stripPrev").setAttribute("aria-label", yearly ? "Previous year" : "Previous month");
  $("stripNext").setAttribute("aria-label", yearly ? "Next year" : "Next month");
  $("stripLatest").disabled = atEnd;
  document.querySelectorAll("#calScale .seg-btn").forEach((btn) => {
    btn.setAttribute("aria-pressed", String(btn.dataset.scale === state.calScale));
  });
}

function renderOpenIncidents() {
  const container = $("openIncidents");
  const open = state.incidents.filter((i) => i.open && (!state.region || i._region === state.region));

  if (open.length === 0) {
    container.innerHTML = `<p class="note">No incidents are open in the latest AWS snapshot${
      state.region ? ` for ${escapeHtml(state.region)}` : ""
    }. That means AWS has no active event posted, not that every service is confirmed healthy.</p>`;
    return;
  }

  container.innerHTML = `<div class="open-list">${open
    .map((incident) => {
      const services = Object.entries(incident.services || {});
      const affected = services
        .filter(([, s]) => s.current && s.current !== "operational")
        .sort((a, b) => (SEVERITY_RANK[b[1].current] ?? -1) - (SEVERITY_RANK[a[1].current] ?? -1));
      const shown = affected.slice(0, 24);
      const current = incident._latest ? incident._latest.severity : "unknown";
      const chips = shown
        .map(([slug, s]) => `<span class="service-chip" title="${escapeHtml(SEVERITY_LABEL[s.current] || s.current)}">${severityDot(s.current)}${escapeHtml(s.service_name || slug)}</span>`)
        .join("");
      const more =
        affected.length > shown.length
          ? `<button type="button" class="link-btn" data-open-modal="${escapeHtml(incident.key)}">+${affected.length - shown.length} more</button>`
          : "";
      const summary = services.length
        ? `${affected.length} of ${plural(services.length, "listed service")} affected`
        : "No per-service breakdown published";

      return `<article class="open-card">
        <div class="open-head">
          <div>
            <button type="button" class="incident-title" data-open-modal="${escapeHtml(incident.key)}">${escapeHtml(incident.title)}</button>
            <p class="open-meta">${escapeHtml(incident._region)} · since ${fmtDateTime(incident.started_at)} · ${summary}</p>
          </div>
          ${severityBadge(current)}
        </div>
        ${affected.length ? `<div class="service-grid">${chips}${more}</div>` : ""}
      </article>`;
    })
    .join("")}</div>`;
}

function renderChips() {
  const chips = [];
  const chip = (label, type) =>
    `<span class="chip">${escapeHtml(label)}<button type="button" class="chip-remove" data-remove="${type}" aria-label="Remove filter: ${escapeHtml(label)}">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"></path></svg></button></span>`;
  if (state.region) chips.push(chip(`Region: ${state.region}`, "region"));
  if (state.severity !== "all") chips.push(chip(`Worst: ${SEVERITY_LABEL[state.severity]}`, "severity"));
  if (state.date) chips.push(chip(`Day: ${fmtDay(state.date)}`, "date"));
  if (state.query) chips.push(chip(`Search: "${state.query}"`, "query"));
  $("activeChipsContainer").innerHTML = chips.join("");
  $("activeFiltersBar").hidden = chips.length === 0;
}

// Numbered pages: first, last and the pages around the current one.
function pagerHtml(kind, page, pages) {
  if (pages <= 1) return "";
  const wanted = new Set([1, 2, pages - 1, pages, page - 1, page, page + 1]);
  const numbers = [...wanted].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
  const items = [];
  let previous = 0;
  for (const n of numbers) {
    if (n - previous > 1) items.push('<span class="page-gap" aria-hidden="true">…</span>');
    items.push(
      `<button type="button" class="page-btn" data-pager="${kind}" data-page="${n}"${
        n === page ? ' aria-current="page"' : ""
      } aria-label="Page ${n} of ${pages}">${n}</button>`
    );
    previous = n;
  }
  const arrow = (label, target, glyph, disabled) =>
    `<button type="button" class="page-btn page-arrow" data-pager="${kind}" data-page="${target}" aria-label="${label}"${
      disabled ? " disabled" : ""
    }>${glyph}</button>`;
  return `${arrow("Previous page", page - 1, "‹", page <= 1)}${items.join("")}${arrow("Next page", page + 1, "›", page >= pages)}`;
}

function paginate(items, page, size) {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const current = Math.min(Math.max(1, page), pages);
  return { pages, page: current, shown: items.slice((current - 1) * size, current * size) };
}

function setPagers(kind, page, pages) {
  document.querySelectorAll(`.pager[data-pager="${kind}"]`).forEach((nav) => {
    nav.innerHTML = pagerHtml(kind, page, pages);
    nav.hidden = pages <= 1;
  });
}

function renderList(incidents) {
  const { pages, page, shown } = paginate(incidents, state.page, PAGE_SIZE);
  state.page = page;
  $("incidentList").innerHTML = shown.map(incidentCard).join("");
  setPagers("events", page, pages);

  state.eventsSubtitle =
    incidents.length === state.incidents.length
      ? plural(incidents.length, "event")
      : `${incidents.length} of ${plural(state.incidents.length, "event")}`;

}

function renderView(matchingIncidents) {
  const services = state.view === "services";
  document.querySelectorAll("#viewToggle .seg-btn").forEach((btn) => {
    btn.setAttribute("aria-pressed", String(btn.dataset.view === state.view));
  });
  $("servicesView").hidden = !services;
  $("eventsView").hidden = services;
  $("incidentListSubtitle").textContent = services ? state.gridSubtitle : state.eventsSubtitle;
  $("emptyState").hidden = services || matchingIncidents > 0;
}

function gridRows() {
  let rows = state.serviceRows;
  if (state.region) rows = rows.filter((row) => row.region === state.region);
  if (state.query) {
    const q = state.query.toLowerCase();
    const byLabel = rows.filter((row) => row.label.includes(q));
    // No service name matches: fall back to services of incidents that do.
    rows = byLabel.length
      ? byLabel
      : rows.filter((row) => Object.values(row.cells).some((cell) => cell.incident._search.includes(q)));
  }
  return rows;
}

function renderServiceGrid() {
  const container = $("serviceGrid");
  const rows = gridRows();
  const allDays = rows.flatMap((row) => Object.keys(row.cells)).sort();
  const today = todayKey();
  const latest = allDays[allDays.length - 1] || today;
  const end = state.gridEnd || latest;
  const days = Array.from({ length: GRID_DAYS }, (_, i) => addDays(end, -i));
  const start = days[days.length - 1];

  $("gridEndInput").value = end;
  $("gridEndInput").max = today;
  $("gridNewer").disabled = end >= today;
  $("gridLatest").disabled = end === latest;
  $("gridOnlyEvents").checked = state.gridOnlyEvents;

  const sevOk = (cell) => state.severity === "all" || cell.severity === state.severity;
  const inWindow = (row) => days.some((day) => row.cells[day] && sevOk(row.cells[day]));
  const worstInWindow = (row) => Math.max(...days.map((day) => SEVERITY_RANK[row.cells[day]?.severity] ?? -9));
  const active = rows.filter(inWindow).sort((a, b) => worstInWindow(b) - worstInWindow(a));
  const onlyActive = state.gridOnlyEvents || state.severity !== "all";
  const visible = onlyActive ? active : [...active, ...rows.filter((row) => !inWindow(row))];

  state.gridSubtitle = `${plural(rows.length, "service")} with archived events · ${active.length} affected ${fmtDay(start)} – ${fmtDay(end)}`;

  if (visible.length === 0) {
    const earlier = allDays.filter((day) => day < start).pop();
    container.innerHTML = `<div class="state">
      <p class="state-title">No reported events between ${fmtDay(start)} and ${fmtDay(end)}</p>
      <p class="state-desc">That means AWS posted nothing for these services, not that they were confirmed healthy.</p>
      ${earlier ? `<button type="button" class="btn" data-grid-end="${earlier}">Go to the previous events (${fmtDay(earlier)})</button>` : ""}
    </div>`;
    setPagers("grid", 1, 1);
    return;
  }

  const { pages, page, shown } = paginate(visible, state.gridPage, GRID_PAGE_SIZE);
  state.gridPage = page;
  setPagers("grid", page, pages);
  const head = days
    .map((day) => `<th scope="col" class="day-col">${day === today ? "Today" : escapeHtml(fmtDay(day).replace(/, \d{4}$/, ""))}</th>`)
    .join("");
  const body = shown
    .map((row) => {
      const cells = days
        .map((day) => {
          const cell = row.cells[day];
          if (!cell || !sevOk(cell)) {
            return `<td class="day-col"><span class="cell-none" title="No reported event">–<span class="sr-only">No reported event</span></span></td>`;
          }
          const label = `${fmtDay(day)}: ${SEVERITY_LABEL[cell.severity]} — ${cell.incident.title}`;
          return `<td class="day-col"><button type="button" class="cell-btn" data-open-modal="${escapeHtml(cell.incident.key)}" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}">${severityIcon(cell.severity)}</button></td>`;
        })
        .join("");
      return `<tr><th scope="row" class="svc-col"><span class="svc-name">${escapeHtml(row.name)}</span><span class="svc-region">${escapeHtml(row.region)}</span></th>${cells}</tr>`;
    })
    .join("");

  container.innerHTML = `<table class="svc-table">
      <thead><tr><th scope="col" class="svc-col">Service</th>${head}</tr></thead>
      <tbody>${body}</tbody>
    </table>
    <ul class="legend grid-legend" aria-label="Legend">
      ${["disrupted", "degraded", "impacted", "resolved"].map((sev) => `<li>${severityIcon(sev)}${SEVERITY_LABEL[sev]}</li>`).join("")}
      <li><span class="cell-none">–</span>No reported event</li>
    </ul>`;

}

function incidentCard(incident) {
  const start = incident._updates[0]?.published || incident.started_at;
  const end = incident._latest?.published;
  const duration = start && end ? fmtDuration(start, end) : null;
  const meta = [
    escapeHtml(incident._region),
    fmtDateTime(start),
    duration ? `lasted ${duration}` : null,
    plural(incident._updates.length, "update"),
  ].filter(Boolean);
  const latest = incident._latest ? plainText(incident._latest.description) : "";

  return `<article class="incident sev-${escapeHtml(incident._worst)}" data-key="${escapeHtml(incident.key)}">
    <span class="incident-rail" aria-hidden="true"></span>
    <div class="incident-body">
      <button type="button" class="incident-title" data-open-modal="${escapeHtml(incident.key)}">${escapeHtml(incident.title)}</button>
      <div class="incident-meta">${meta.map((m) => `<span>${m}</span>`).join("")}</div>
      ${latest ? `<p class="incident-latest">${escapeHtml(latest)}</p>` : ""}
    </div>
    <div class="incident-side">
      ${incident.open ? '<span class="badge badge-open">Open</span>' : ""}
      ${severityBadge(incident._worst)}
      <button type="button" class="icon-btn" data-copy="${escapeHtml(incident.key)}" aria-label="Copy link to this incident" title="Copy link">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"></path><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"></path></svg>
      </button>
    </div>
  </article>`;
}

/* ---------- Strip interaction ---------- */

function showTooltip(bar) {
  const day = bar.dataset.day;
  const entries = state.stripByDay[day] || [];
  const sev = daySeverity(entries);
  const titles = [...new Set(entries.map((e) => e.incident.title))];
  const updateCount = entries.reduce((sum, e) => sum + e.updates, 0);
  const detail = entries.length ? (updateCount ? plural(updateCount, "update") : "in progress, no new update") : "";
  const tip = $("stripTooltip");

  tip.innerHTML = `
    <div class="tooltip-date">${fmtDayWithWeekday(day)}</div>
    <div class="tooltip-status">${severityDot(sev)}${escapeHtml(SEVERITY_LABEL[sev])}${detail ? ` · ${detail}` : ""}</div>
    ${
      titles.length
        ? `<ul class="tooltip-list">${titles.slice(0, 3).map((t) => `<li>${escapeHtml(t)}</li>`).join("")}${
            titles.length > 3 ? `<li>+${plural(titles.length - 3, "more incident")}</li>` : ""
          }</ul>`
        : ""
    }`;
  tip.hidden = false;

  const stage = $("stripStage").getBoundingClientRect();
  const rect = bar.getBoundingClientRect();
  const width = tip.offsetWidth;
  const center = rect.left - stage.left + rect.width / 2;
  tip.style.left = `${Math.max(0, Math.min(center - width / 2, stage.width - width))}px`;
  tip.style.bottom = `${stage.bottom - rect.top + 8}px`;
}

function hideTooltip() {
  $("stripTooltip").hidden = true;
}

function toggleDay(day) {
  if (!state.stripByDay[day]) return;
  state.stripFocusDay = day;
  setFilter({ date: state.date === day ? null : day, gridEnd: day });
  document.querySelector(`#daysStrip .bar[data-day="${day}"]`)?.focus();
}

function setupStrip() {
  const strip = $("daysStrip");
  strip.addEventListener("pointerover", (e) => {
    const bar = e.target.closest(".bar");
    if (bar) showTooltip(bar);
  });
  strip.addEventListener("pointerleave", hideTooltip);
  strip.addEventListener("focusin", (e) => {
    if (e.target.classList.contains("bar")) showTooltip(e.target);
  });
  strip.addEventListener("focusout", hideTooltip);
  strip.addEventListener("click", (e) => {
    const bar = e.target.closest(".bar");
    if (bar) toggleDay(bar.dataset.day);
  });

  // One tab stop for the whole calendar; arrow keys move between days. In the
  // year view a column is a week, so left/right move a week and up/down a day.
  strip.addEventListener("keydown", (e) => {
    const bar = e.target.closest(".bar");
    if (!bar) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      toggleDay(bar.dataset.day);
      return;
    }
    const yearly = state.calScale === "year";
    const steps = yearly
      ? { ArrowLeft: -7, ArrowRight: 7, ArrowUp: -1, ArrowDown: 1 }
      : { ArrowLeft: -1, ArrowRight: 1 };
    const bars = [...strip.querySelectorAll(".bar[data-day]")];
    const index = bars.indexOf(bar);
    let next = null;
    if (e.key in steps) next = bars[index + steps[e.key]];
    else if (e.key === "Home") next = bars[0];
    else if (e.key === "End") next = bars[bars.length - 1];
    else return;
    e.preventDefault();
    if (!next) return;
    bar.tabIndex = -1;
    next.tabIndex = 0;
    next.focus();
    state.stripFocusDay = next.dataset.day;
  });

  const step = (direction) => {
    if (state.calScale === "year") {
      state.calYear += direction;
    } else {
      const moved = new Date(Date.UTC(state.calYear, state.calMonth + direction, 1));
      state.calYear = moved.getUTCFullYear();
      state.calMonth = moved.getUTCMonth();
    }
    render();
  };
  $("stripPrev").addEventListener("click", () => step(-1));
  $("stripNext").addEventListener("click", () => step(1));
  $("stripLatest").addEventListener("click", () => {
    state.calYear = null;
    state.calMonth = null;
    render();
  });
  $("calScale").addEventListener("click", (e) => {
    const btn = e.target.closest(".seg-btn");
    if (!btn) return;
    state.calScale = btn.dataset.scale;
    render();
  });
  // A month name in the year view opens that month.
  $("stripMonths").addEventListener("click", (e) => {
    const label = e.target.closest(".month-label");
    if (!label || label.disabled) return;
    state.calScale = "month";
    state.calMonth = Number(label.dataset.month);
    render();
  });
}

/* ---------- Incident dialog ---------- */

function focusableIn(el) {
  return [...el.querySelectorAll('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])')].filter(
    (node) => node.offsetParent !== null
  );
}

function openModal(incident) {
  if (!state.modalIncident) state.lastFocus = document.activeElement;
  state.modalIncident = incident;

  const start = incident._updates[0]?.published || incident.started_at;
  const end = incident._latest?.published;
  const duration = start && end ? fmtDuration(start, end) : null;
  $("modalTitle").textContent = incident.title;
  $("modalSub").textContent = [
    incident._region,
    `Started ${fmtDateTime(start)}`,
    duration ? `lasted ${duration}` : null,
    plural(incident._updates.length, "update"),
    incident.open ? "Open" : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const byName = (a, b) => (a[1].service_name || a[0]).localeCompare(b[1].service_name || b[0]);
  const services = Object.entries(incident.services || {})
    .filter(([, s]) => s.max && s.max !== "operational")
    .sort((a, b) => (SEVERITY_RANK[b[1].max] ?? -1) - (SEVERITY_RANK[a[1].max] ?? -1) || byName(a, b));

  const servicesHtml = services.length
    ? `<section class="modal-section">
        <h3>Affected services (${services.length}), by worst status reached</h3>
        <div class="service-grid${services.length > 30 ? " is-collapsed" : ""}">${services
          .map(([slug, s]) => {
            const now =
              incident.open && s.current && s.current !== s.max
                ? ` <span class="muted">· now ${escapeHtml((SEVERITY_LABEL[s.current] || s.current).toLowerCase())}</span>`
                : "";
            return `<span class="service-chip" title="Worst: ${escapeHtml(SEVERITY_LABEL[s.max] || s.max)}">${severityDot(s.max)}${escapeHtml(s.service_name || slug)}${now}</span>`;
          })
          .join("")}${
          services.length > 30
            ? `<button type="button" class="link-btn" data-expand-services>Show all ${services.length}</button>`
            : ""
        }</div>
      </section>`
    : "";

  const shown = (sev) => (sev === "operational" ? "resolved" : sev);
  const timeline = incident._updates
    .map(
      (u) => `<li>${severityDot(shown(u.severity))}
        <div class="timeline-meta"><span>${fmtDateTime(u.published)}</span>${severityBadge(shown(u.severity))}</div>
        <div class="timeline-desc">${renderDescription(u.description) || "—"}</div></li>`
    )
    .join("");

  $("modalBody").innerHTML = `
    ${servicesHtml}
    <section class="modal-section">
      <h3>Updates</h3>
      <ol class="timeline">${timeline}</ol>
    </section>`;

  $("incidentModal").hidden = false;
  document.body.classList.add("modal-open");
  $("modalBody").scrollTop = 0;
  $("modalCloseBtn").focus();
  writeHash();
}

function closeModal() {
  if (!state.modalIncident) return;
  $("incidentModal").hidden = true;
  document.body.classList.remove("modal-open");
  state.modalIncident = null;
  writeHash();
  if (state.lastFocus && document.contains(state.lastFocus)) state.lastFocus.focus();
  state.lastFocus = null;
}

function setupModal() {
  const overlay = $("incidentModal");
  $("modalCloseBtn").addEventListener("click", closeModal);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeModal();
  });
  overlay.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      closeModal();
      return;
    }
    if (e.key !== "Tab") return;
    const nodes = focusableIn(overlay.querySelector(".modal"));
    if (nodes.length === 0) return;
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  });
  $("modalBody").addEventListener("click", (e) => {
    const expand = e.target.closest("[data-expand-services]");
    if (!expand) return;
    expand.parentElement.classList.remove("is-collapsed");
    expand.remove();
  });
  $("modalCopyBtn").addEventListener("click", () => {
    if (state.modalIncident) copyLink(state.modalIncident.key);
  });
}

/* ---------- Links, export, theme, toasts ---------- */

function showToast(message) {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  $("toastContainer").appendChild(toast);
  setTimeout(() => {
    toast.classList.add("toast-leaving");
    setTimeout(() => toast.remove(), 250);
  }, 2400);
}

function copyLink(key) {
  const url = `${location.origin}${location.pathname}#incident=${encodeURIComponent(shortKey(key))}`;
  if (!navigator.clipboard?.writeText) {
    showToast("Couldn't copy the link in this browser");
    return;
  }
  navigator.clipboard.writeText(url).then(
    () => showToast("Link copied"),
    () => showToast("Couldn't copy the link")
  );
}

function download(filename, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function exportIncidents(format) {
  const rows = sortIncidents(state.incidents.filter((i) => matches(i)));
  const stamp = todayKey();
  if (format === "csv") {
    const header = ["key", "title", "region", "service", "started_at", "last_update", "updates", "worst_severity", "open"];
    const lines = rows.map((i) =>
      [i.key, i.title, i._region, i.service, i.started_at, i.last_update, i._updates.length, i._worst, i.open ? "yes" : "no"]
        .map(csvCell)
        .join(",")
    );
    // BOM so spreadsheet apps read accented region names correctly.
    download(`aws-status-archive-${stamp}.csv`, `﻿${[header.join(","), ...lines].join("\n")}\n`, "text/csv;charset=utf-8");
  } else {
    const clean = rows.map(({ _updates, _region, _worst, _latest, _short, _search, ...rest }) => rest);
    download(`aws-status-archive-${stamp}.json`, JSON.stringify(clean, null, 2), "application/json");
  }
  showToast(`Exported ${plural(rows.length, "incident")} as ${format.toUpperCase()}`);
}

function setupExportMenu() {
  const button = $("exportBtn");
  const menu = $("exportMenu");
  const close = (restoreFocus) => {
    if (menu.hidden) return;
    menu.hidden = true;
    button.setAttribute("aria-expanded", "false");
    if (restoreFocus) button.focus();
  };

  button.addEventListener("click", () => {
    if (!menu.hidden) {
      close(false);
      return;
    }
    const count = state.incidents.filter((i) => matches(i)).length;
    $("exportMenuLabel").textContent = `Export ${plural(count, "incident")}${count === state.incidents.length ? "" : " (filtered)"}`;
    menu.hidden = false;
    button.setAttribute("aria-expanded", "true");
    menu.querySelector(".menu-item").focus();
  });
  menu.addEventListener("click", (e) => {
    const item = e.target.closest(".menu-item");
    if (!item) return;
    close(true);
    exportIncidents(item.dataset.format);
  });
  menu.addEventListener("keydown", (e) => {
    const items = [...menu.querySelectorAll(".menu-item")];
    const index = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") {
      e.preventDefault();
      items[(index + 1) % items.length].focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      items[(index - 1 + items.length) % items.length].focus();
    } else if (e.key === "Tab") {
      close(false);
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") close(true);
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".menu-wrap")) close(false);
  });
}

function currentTheme() {
  const saved = storageGet("theme");
  return THEME_MODES.includes(saved) ? saved : "auto";
}

function applyTheme(mode) {
  if (mode === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", mode);
  const next = THEME_MODES[(THEME_MODES.indexOf(mode) + 1) % THEME_MODES.length];
  const btn = $("themeToggleBtn");
  btn.setAttribute("aria-label", `${THEME_LABEL[mode]}. Switch to ${next === "auto" ? "system" : next}.`);
  btn.title = THEME_LABEL[mode];
}

function setupTheme() {
  applyTheme(currentTheme());
  $("themeToggleBtn").addEventListener("click", () => {
    const next = THEME_MODES[(THEME_MODES.indexOf(currentTheme()) + 1) % THEME_MODES.length];
    storageSet("theme", next);
    applyTheme(next);
  });
}

/* ---------- URL hash ---------- */

function writeHash() {
  const params = new URLSearchParams();
  if (state.region) params.set("region", state.region);
  if (state.severity !== "all") params.set("sev", state.severity);
  if (state.date) params.set("date", state.date);
  if (state.query) params.set("q", state.query);
  if (state.view === "events") params.set("view", "events");
  if (state.modalIncident) params.set("incident", state.modalIncident._short);
  const target = params.toString() ? `#${params}` : "";
  if (location.hash !== target) {
    history.replaceState(null, "", `${location.pathname}${location.search}${target}`);
  }
}

function readHash() {
  // URLSearchParams already decodes values; never decode twice.
  const params = new URLSearchParams(location.hash.slice(1));
  const region = params.get("region");
  const sev = params.get("sev");
  const date = params.get("date");

  state.region = region && state.incidents.some((i) => i._region === region) ? region : null;
  state.severity = FILTER_SEVERITIES.includes(sev) ? sev : "all";
  state.date = date && /^\d{4}-\d{2}-\d{2}$/.test(date) && !Number.isNaN(dayToMs(date)) ? date : null;
  state.query = (params.get("q") || "").trim();
  state.view = params.get("view") === "events" ? "events" : "services";
  if (state.date) {
    state.calYear = Number(state.date.slice(0, 4));
    state.calMonth = Number(state.date.slice(5, 7)) - 1;
  }
  state.page = 1;
  state.gridPage = 1;

  const wanted = params.get("incident");
  return wanted ? state.incidents.find((i) => i.key === wanted || i._short === wanted) || null : null;
}

/* ---------- Event wiring ---------- */

function setFilter(changes) {
  Object.assign(state, { page: 1, gridPage: 1 }, changes);
  render();
}

function setupEvents() {
  $("regionList").addEventListener("click", (e) => {
    const item = e.target.closest(".region-item");
    if (!item) return;
    e.preventDefault();
    setFilter({ region: item.dataset.region || null });
  });
  $("mobileRegionList").addEventListener("click", (e) => {
    const pill = e.target.closest(".region-pill");
    if (pill) setFilter({ region: pill.dataset.region || null });
  });
  $("sidebarSearchInput").addEventListener("input", (e) => {
    state.regionQuery = e.target.value;
    renderSidebar();
  });

  let searchTimer = null;
  $("globalSearchInput").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    const value = e.target.value.trim();
    searchTimer = setTimeout(() => setFilter({ query: value }), 150);
  });

  $("severityFilter").addEventListener("click", (e) => {
    const btn = e.target.closest(".seg-btn");
    if (btn) setFilter({ severity: btn.dataset.severity });
  });

  $("activeChipsContainer").addEventListener("click", (e) => {
    const btn = e.target.closest(".chip-remove");
    if (!btn) return;
    const reset = { region: { region: null }, severity: { severity: "all" }, date: { date: null }, query: { query: "" } };
    setFilter(reset[btn.dataset.remove] || {});
    $("globalSearchInput").focus();
  });

  const clearAll = () => setFilter({ region: null, severity: "all", date: null, query: "" });
  $("clearAllFiltersBtn").addEventListener("click", clearAll);
  $("emptyStateResetBtn").addEventListener("click", clearAll);

  $("incidentSortSelect").addEventListener("change", (e) => setFilter({ sort: e.target.value }));

  $("viewToggle").addEventListener("click", (e) => {
    const btn = e.target.closest(".seg-btn");
    if (btn) setFilter({ view: btn.dataset.view });
  });
  const gridEnd = () => $("gridEndInput").value || todayKey();
  const clampDay = (day) => (day > todayKey() ? todayKey() : day);
  $("gridOlder").addEventListener("click", () => setFilter({ gridEnd: addDays(gridEnd(), -GRID_DAYS) }));
  $("gridNewer").addEventListener("click", () => setFilter({ gridEnd: clampDay(addDays(gridEnd(), GRID_DAYS)) }));
  $("gridLatest").addEventListener("click", () => setFilter({ gridEnd: null }));
  $("gridEndInput").addEventListener("change", (e) => {
    if (/^\d{4}-\d{2}-\d{2}$/.test(e.target.value)) setFilter({ gridEnd: clampDay(e.target.value) });
  });
  $("gridOnlyEvents").addEventListener("change", (e) => setFilter({ gridOnlyEvents: e.target.checked }));
  $("serviceGrid").addEventListener("click", (e) => {
    const jump = e.target.closest("[data-grid-end]");
    if (jump) setFilter({ gridEnd: jump.dataset.gridEnd });
  });
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".page-btn");
    if (!btn || btn.disabled) return;
    const kind = btn.dataset.pager;
    const fromBottom = Boolean(btn.closest(".pager-bottom"));
    if (kind === "grid") state.gridPage = Number(btn.dataset.page);
    else state.page = Number(btn.dataset.page);
    render();
    // Paging from below the list: bring the top of the new page into view.
    if (fromBottom) $("logTitle").scrollIntoView({ block: "start" });
    document.querySelector(`.pager${fromBottom ? ".pager-bottom" : ":not(.pager-bottom)"}[data-pager="${kind}"] [aria-current="page"]`)?.focus();
  });

  // Titles and cards open the dialog; the copy button copies a link.
  document.addEventListener("click", (e) => {
    const copy = e.target.closest("[data-copy]");
    if (copy) {
      copyLink(copy.dataset.copy);
      return;
    }
    if (e.target.closest("a") || e.target.closest(".modal-overlay")) return;
    const opener = e.target.closest("[data-open-modal]") || e.target.closest(".incident");
    if (!opener) return;
    const key = opener.dataset.openModal || opener.dataset.key;
    const incident = state.incidents.find((i) => i.key === key);
    if (incident) openModal(incident);
  });

  window.addEventListener("hashchange", () => {
    const incident = readHash();
    render();
    if (incident) openModal(incident);
    else closeModal();
  });
}

/* ---------- Startup ---------- */

async function loadJson(url) {
  const response = await fetch(url, { cache: "no-cache" });
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}

function renderHeaderMeta(filtered) {
  const meta = state.metadata;
  const range =
    meta?.archive_earliest_date && meta?.archive_latest_date
      ? `${fmtDay(meta.archive_earliest_date)} – ${fmtDay(meta.archive_latest_date)}`
      : "";
  // With filters on, say what the numbers below cover.
  const scope = [
    state.region,
    state.severity !== "all" ? `worst status ${SEVERITY_LABEL[state.severity].toLowerCase()}` : null,
    state.date ? fmtDay(state.date) : null,
    state.query ? `"${state.query}"` : null,
  ].filter(Boolean);
  $("updatedAt").textContent = scope.length
    ? `${filtered} of ${plural(state.incidents.length, "incident")} · ${scope.join(" · ")}`
    : `Archive covers ${range || "the period AWS has published"}`;
  const rebuilt = meta?.rebuilt_at ? dayKey(meta.rebuilt_at) : null;
  $("rebuiltAt").textContent = rebuilt ? ` · last rebuilt ${fmtDay(rebuilt)}` : "";
}

async function init() {
  setupTheme();
  setupStrip();
  setupModal();
  setupExportMenu();
  setupEvents();

  try {
    const [incidents, metadata] = await Promise.all([loadJson(DATA_URL), loadJson(METADATA_URL).catch(() => null)]);
    state.incidents = incidents.map(prepare);
    state.serviceRows = buildServiceRows(state.incidents);
    const all = buildDayMap(state.incidents);
    state.archiveSpan = all.first ? { first: all.first, last: all.last } : null;
    state.metadata = metadata;
  } catch (err) {
    console.error(err);
    $("loadingState").hidden = true;
    $("errorState").hidden = false;
    $("errorMessage").textContent = `${err.message}. To run the site locally, use "uv run python scripts/serve.py".`;
    $("updatedAt").textContent = "Archive unavailable";
    $("dailyBlock").hidden = true;
    return;
  }

  $("loadingState").hidden = true;
  const incident = readHash();
  render();
  if (incident) openModal(incident);
}

document.addEventListener("DOMContentLoaded", init);
