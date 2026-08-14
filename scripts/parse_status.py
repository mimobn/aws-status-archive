#!/usr/bin/env python3
"""Parse the AWS Service Health Dashboard JSON archives.

AWS publishes the data behind its Service history table as three JSON
files (see fetch_archive.py for the URLs):

  * services.json      -- the service + region catalog with display names
  * historyevents.json -- resolved/open incidents with full update logs
  * currentevents.json -- open incidents, including the list of affected
                          services and per-service status transitions

This module turns those files into structured records the rebuild can
group into region incidents with a per-service availability breakdown.

Severity comes from the AWS numeric status codes, which the status page
colors the same way as the site does:

    0 -> operational      (Operating normally)
    1 -> impacted         (Impacted)
    2 -> degraded         (Degraded)
    3 -> disrupted        (Disrupted)
"""

import json
import re
from datetime import datetime, timezone

UTC = timezone.utc

STATUS_TO_SEVERITY = {
    "0": "operational",
    "1": "impacted",
    "2": "degraded",
    "3": "disrupted",
}

RESOLVED_PREFIXES = ("[RESOLVED] ", "[IN PROGRESS] ", "[CLOSED] ")

# Region codes look like me-central-1, us-east-1, us-gov-east-1, ...
REGION_CODE_RE = re.compile(r"\b([a-z]{2,3}(?:-[a-z0-9]+)*-\d)\b", re.IGNORECASE)


def severity(status):
    """Map an AWS numeric status to a site severity label."""
    return STATUS_TO_SEVERITY.get(str(status), "unknown")


def clean_title(value):
    """Drop noisy brackets AWS prefixes summaries with."""
    value = value or ""
    for prefix in RESOLVED_PREFIXES:
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value


def iso(ms_or_sec):
    """ISO timestamp for a unix time (milliseconds or seconds)."""
    ms = int(ms_or_sec)
    if ms < 100000000000:  # looks like seconds, not milliseconds
        ms *= 1000
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat()


def parse_services_text(content):
    """Parse services.json into {service_slug: row} plus the raw list."""
    rows = json.loads(content)
    catalog = {row["service"]: row for row in rows}
    return catalog, rows


def parse_history_text(content):
    """Parse historyevents.json into {service_slug: [event, ...]}."""
    return json.loads(content)


def parse_current_text(content):
    """Parse currentevents.json into a list of open-incident records."""
    return json.loads(content)


def event_log_updates(event):
    """Flatten an event's update log into the site's update records."""
    seen = set()
    updates = []
    for entry in event.get("event_log", []):
        try:
            stamp = int(entry["timestamp"])
        except (KeyError, TypeError, ValueError):
            continue
        if stamp in seen:
            continue
        seen.add(stamp)
        updates.append(
            {
                "published": iso(stamp),
                "severity": severity(entry.get("status")),
                "title": clean_title(entry.get("summary") or event.get("summary")),
                "description": entry.get("message") or "",
            }
        )
    updates.sort(key=lambda u: u["published"])
    return updates


def extract_region(slug, catalog):
    """Find the region code for a service slug (or None for global roads)."""
    match = REGION_CODE_RE.search(slug)
    if match:
        return match.group(1).lower()
    row = catalog.get(slug) or {}
    region_id = row.get("region_id")
    return region_id.lower() if region_id else None


def day_start_ms(day):
    """UTC midnight of a YYYY-MM-DD day, as milliseconds."""
    y, m, d = (int(part) for part in day.split("-"))
    return int(datetime(y, m, d, tzinfo=UTC).timestamp()) * 1000


def service_days(transitions, first_day, last_day):
    """Per-day severity for a service across an incident window.

    `transitions` is a list of {"timestamp"/"date" (unix), "status"/"previous_status"
    ...} entries sorted by time. Each day takes the severity of the most
    recent transition at or before that day; days before the first
    transition are operational.
    """
    events = []
    for trans in transitions:
        try:
            stamp = int(trans.get("timestamp") or trans.get("date"))
        except (TypeError, ValueError):
            continue
        if stamp < 100000000000:
            stamp *= 1000
        status = trans.get("status") or trans.get("current_status")
        events.append((stamp, severity(status)))
    events.sort()

    days = {}
    current = "operational"
    year, month, day = (int(part) for part in first_day.split("-"))
    cursor = int(datetime(year, month, day, tzinfo=UTC).timestamp()) * 1000
    end = day_start_ms(last_day)
    idx = 0
    while cursor <= end:
        # A transition applies to the day it happens on, so compare against
        # the end of the current day (start of the next one).
        while idx < len(events) and events[idx][0] < cursor + 86400000:
            current = events[idx][1]
            idx += 1
        days[datetime.fromtimestamp(cursor / 1000, UTC).strftime("%Y-%m-%d")] = current
        cursor += 86400000
    return days


def worst_transition_severity(transitions):
    """Worst severity reached across an incident's per-service transitions."""
    rank = {"disrupted": 4, "impacted": 3, "degraded": 2, "informational": 1, "operational": 0, "unknown": -1}
    worst = "unknown"
    for trans in transitions:
        status = trans.get("current_status")
        label = severity(status)
        if rank.get(label, -1) > rank.get(worst, -1):
            worst = label
    return worst