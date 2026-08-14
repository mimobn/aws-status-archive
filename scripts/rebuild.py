#!/usr/bin/env python3
"""Rebuild incident timelines from the archived AWS Service Health JSON.

The archives recorded in data/ come straight from the state behind AWS's
"Service history" table (see fetch_archive.py). Unlike the old RSS feeds,
historyevents.json already carries ~12 months of incident history, so the
rebuild no longer replays git history: it merges

  * services.json      - the service/region catalog (display names)
  * historyevents.json - every incident with its full update log
  * currentevents.json - still-open events plus the per-service
                         availability breakdown

into out/incidents.json (the site's data file) and out/status.db (the
API's mirror). The two Middle East multiple-service events keep their
region-level incidents, enriched with the per-service map so the site
can show each service's availability inside its region.

Severity follows the AWS numeric status codes (0 operational, 1 impacted,
2 degraded, 3 disrupted; see parse_status.py). Rebuilding is
deterministic: same data in, same output out.
"""

import json
import os
import sqlite3
import sys
from datetime import datetime

from parse_status import (
    clean_title,
    event_log_updates,
    extract_region,
    iso,
    parse_current_text,
    parse_history_text,
    parse_services_text,
    severity,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "out", "incidents.json")
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "out", "status.db")

# Friendly names for the regions the site has historically shown. Unknown
# region codes fall back to the short name in the services.json catalog.
REGION_NAMES = {
    "me-central-1": "Middle East (UAE)",
    "me-south-1": "Middle East (Bahrain)",
}

SCHEMA = """
DROP TABLE IF EXISTS services;
DROP TABLE IF EXISTS updates;
DROP TABLE IF EXISTS incidents;

CREATE TABLE updates (
    guid TEXT PRIMARY KEY,
    incident_key TEXT NOT NULL,
    published TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE incidents (
    incident_key TEXT PRIMARY KEY,
    started_at TEXT,
    last_update TEXT,
    update_count INTEGER,
    title TEXT,
    region TEXT,
    region_name TEXT,
    service TEXT,
    service_name TEXT
);

CREATE TABLE services (
    incident_key TEXT NOT NULL,
    service_slug TEXT NOT NULL,
    service_name TEXT,
    severity TEXT,
    max_severity TEXT,
    PRIMARY KEY (incident_key, service_slug)
);
"""


def load_archives():
    """Read the three archived JSON files into parsed structures."""
    with open(os.path.join(DATA_DIR, "services.json"), encoding="utf-8") as handle:
        catalog, _ = parse_services_text(handle.read())
    with open(os.path.join(DATA_DIR, "historyevents.json"), encoding="utf-8") as handle:
        history = parse_history_text(handle.read())
    with open(os.path.join(DATA_DIR, "currentevents.json"), encoding="utf-8") as handle:
        current = parse_current_text(handle.read())
    return catalog, history, current


def build_services(current_event):
    """Per-service availability for a still-open event.

    Returns a {service_slug: {...}} map with the display name, the current
    severity, the worst severity reached, and the status transitions the
    service went through during the event.
    """
    services = {}
    for slug, info in (current_event.get("impacted_services") or {}).items():
        services[slug] = {
            "service_name": info.get("service_name"),
            "current": severity(info.get("current")),
            "max": severity(info.get("max")),
        }
    transitions = {}
    for entry in current_event.get("impacted_service_status_changes") or []:
        transitions.setdefault(entry.get("service"), []).append(
            {
                "published": iso(entry.get("timestamp")),
                "severity": severity(entry.get("current_status")),
                "previous": severity(entry.get("previous_status")),
            }
        )
    for slug, service in services.items():
        service["transitions"] = sorted(
            transitions.get(slug, []), key=lambda t: t["published"]
        )
    return services


def build_incident(slug, event, catalog, current_event):
    """Build one incident record from a history event and its catalog row."""
    updates = event_log_updates(event)
    started = updates[0]["published"] if updates else None
    last = updates[-1]["published"] if updates else None
    if started is None and event.get("date"):
        started = iso(event["date"])
    # Prefer the first update's summary: it carries the incident's own
    # distinguishing title (e.g. "Increased Connectivity Issues" for
    # Bahrain), whereas the event-level summary is generic.
    title = updates[0]["title"] if updates else clean_title(event.get("summary"))

    row = catalog.get(slug) or {}
    region = extract_region(slug, catalog)
    region_name = REGION_NAMES.get(region) if region else None
    if not region_name:
        region_name = row.get("region_name")

    # A slug can carry several distinct events (e.g. ec2-us-east-1 appears
    # four times), so suffix the key with the event's start so each incident
    # has a stable, unique key.
    event_dot = str(int(event["date"])) if event.get("date") else "0"

    incident = {
        "key": f"https://status.aws.amazon.com/#{slug}_{event_dot}",
        "started_at": started,
        "last_update": last,
        "update_count": len(updates),
        "title": title,
        "service": slug,
        "service_name": row.get("service_name"),
        "region": region,
        "region_name": region_name,
        "updates": updates,
    }
    if current_event and current_event.get("impacted_services"):
        incident["services"] = build_services(current_event)
    return incident


def build_incidents(catalog, history, current):
    """Turn the archives into the site's incident list."""
    current_by_slug = {event.get("service"): event for event in current}
    incidents = []
    for slug, events in history.items():
        if not events:
            continue
        for event in events:
            incidents.append(
                build_incident(slug, event, catalog, current_by_slug.get(slug))
            )
    incidents.sort(key=lambda incident: incident["started_at"] or datetime.min)
    return incidents


def rebuild():
    """Load the archives and return the rebuilt incidents."""
    catalog, history, current = load_archives()
    return build_incidents(catalog, history, current)


def with_guids(incident):
    """Give each update the archive's stable guid (slug + unix timestamp)."""
    for update in incident["updates"]:
        if "guid" not in update:
            ts = int(datetime.fromisoformat(update["published"]).timestamp())
            update["guid"] = f"https://status.aws.amazon.com/#{incident['service']}_{ts}"


def write_db(incidents):
    """Mirror the rebuild into SQLite (wipe and rewrite)."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        for incident in incidents:
            conn.execute(
                "INSERT INTO incidents "
                "(incident_key, started_at, last_update, update_count, title, "
                " region, region_name, service, service_name) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    incident["key"],
                    incident["started_at"],
                    incident["last_update"],
                    incident["update_count"],
                    incident["title"],
                    incident["region"],
                    incident["region_name"],
                    incident["service"],
                    incident["service_name"],
                ),
            )
            for update in incident["updates"]:
                conn.execute(
                    "INSERT INTO updates "
                    "(guid, incident_key, published, severity, title, description) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        update["guid"],
                        incident["key"],
                        update["published"],
                        update["severity"],
                        update["title"],
                        update["description"],
                    ),
                )
            for slug, service in (incident.get("services") or {}).items():
                conn.execute(
                    "INSERT INTO services "
                    "(incident_key, service_slug, service_name, severity, max_severity) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        incident["key"],
                        slug,
                        service.get("service_name"),
                        service.get("current"),
                        service.get("max"),
                    ),
                )
        conn.commit()
    finally:
        conn.close()


def main():
    incidents = rebuild()
    for incident in incidents:
        with_guids(incident)
        print(
            f"{incident['update_count']:2d} updates  {incident['started_at']}  "
            f"{incident['title'][:70]}"
        )

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(incidents, handle, indent=2, ensure_ascii=False)

    write_db(incidents)
    print(f"wrote {DB_PATH}")


if __name__ == "__main__":
    sys.exit(main())