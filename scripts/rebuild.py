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
import tempfile
from datetime import datetime, timezone

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

# Friendly names for all standard AWS regions.
REGION_NAMES = {
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
    "ap-east-1": "Asia Pacific (Hong Kong)",
    "ap-east-2": "Asia Pacific (Taipei)",
    "ap-southeast-5": "Asia Pacific (Malaysia)",
    "ap-southeast-6": "Asia Pacific (New Zealand)",
    "ap-southeast-7": "Asia Pacific (Thailand)",
    "sa-east-1": "South America (São Paulo)",
    "me-central-1": "Middle East (UAE)",
    "me-south-1": "Middle East (Bahrain)",
    "il-central-1": "Israel (Tel Aviv)",
    "mx-central-1": "Mexico (Central)",
    "af-south-1": "Africa (Cape Town)",
    "us-gov-east-1": "AWS GovCloud (US-East)",
    "us-gov-west-1": "AWS GovCloud (US-West)",
    "global": "Global Services",
}

SCHEMA = """
DROP TABLE IF EXISTS services;
DROP TABLE IF EXISTS updates;
DROP TABLE IF EXISTS incidents;
DROP TABLE IF EXISTS metadata;

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
    arn TEXT,
    open INTEGER NOT NULL DEFAULT 0,
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

CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX idx_updates_incident_key ON updates(incident_key);
CREATE INDEX idx_updates_published ON updates(published);
CREATE INDEX idx_incidents_region ON incidents(region);
"""


def load_archives():
    """Read the three archived JSON files into parsed structures.

    Reads from data/archive/ when each file exists, else falls back to raw data/.
    Also loads raw data/currentevents.json separately to compute the open flag.
    """
    archive_dir = os.path.join(DATA_DIR, "archive")

    # Read services (prefer archive, fall back to raw)
    services_path = os.path.join(archive_dir, "services.json")
    if not os.path.exists(services_path):
        services_path = os.path.join(DATA_DIR, "services.json")
    with open(services_path, encoding="utf-8") as handle:
        catalog, _ = parse_services_text(handle.read())

    # Read history events (prefer archive, fall back to raw)
    history_path = os.path.join(archive_dir, "historyevents.json")
    if not os.path.exists(history_path):
        history_path = os.path.join(DATA_DIR, "historyevents.json")
    with open(history_path, encoding="utf-8") as handle:
        history = parse_history_text(handle.read())

    # Read archived current events (prefer archive, fall back to raw)
    current_path = os.path.join(archive_dir, "currentevents.json")
    if not os.path.exists(current_path):
        current_path = os.path.join(DATA_DIR, "currentevents.json")
    with open(current_path, encoding="utf-8") as handle:
        current = parse_current_text(handle.read())

    # Also load raw currentevents.json for computing the open flag
    raw_current_path = os.path.join(DATA_DIR, "currentevents.json")
    try:
        with open(raw_current_path, encoding="utf-8") as handle:
            raw_current = parse_current_text(handle.read())
    except FileNotFoundError:
        raw_current = []

    return catalog, history, current, raw_current


def build_services(current_event):
    """Per-service availability for an event (history or current).

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


def build_incident(slug, event, catalog, current_event, raw_current_arns=None):
    """Build one incident record from a history event and its catalog row."""
    if raw_current_arns is None:
        raw_current_arns = set()

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
    if region is None:
        # Global services have no region_id
        region = "global"
    region_name = REGION_NAMES.get(region) if region else None
    if not region_name:
        region_name = row.get("region_name")

    # A slug can carry several distinct events (e.g. ec2-us-east-1 appears
    # four times), so suffix the key with the event's start so each incident
    # has a stable, unique key.
    event_dot = str(int(event["date"])) if event.get("date") else "0"
    arn = event.get("arn")

    # Determine if this incident is still open (exists in raw current events)
    is_open = 1 if arn and arn in raw_current_arns else 0

    incident = {
        "key": f"https://status.aws.amazon.com/#{slug}_{event_dot}",
        "arn": arn,
        "open": is_open,
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
    # History events carry their own per-service breakdown; a matching open
    # current event (same arn) has the fresher per-service status.
    services = build_services(event)
    if current_event and current_event.get("impacted_services"):
        services.update(build_services(current_event))
    if services:
        incident["services"] = services
    return incident


def build_incidents(catalog, history, current, raw_current=None):
    """Turn the archives into the site's incident list.

    Joins current events by ARN instead of slug. Includes current events
    whose ARN isn't in history as incidents.
    """
    if raw_current is None:
        raw_current = []

    # Build sets for quick lookup
    current_by_arn = {event.get("arn"): event for event in current if event.get("arn")}
    raw_current_arns = {event.get("arn") for event in raw_current if event.get("arn")}

    incidents = []
    processed_arns = set()

    # Process history events
    for slug, events in history.items():
        if not events:
            continue
        for event in events:
            arn = event.get("arn")
            if arn:
                processed_arns.add(arn)
            incidents.append(
                build_incident(slug, event, catalog,
                             current_by_arn.get(arn) if arn else None,
                             raw_current_arns)
            )

    # Add current events not in history
    for arn, current_event in current_by_arn.items():
        if arn not in processed_arns:
            # Create an incident from current event even if not in history
            slug = current_event.get("service")
            incidents.append(
                build_incident(slug, current_event, catalog, current_event,
                             raw_current_arns)
            )

    # Sort by started_at, with empty strings sorting first
    incidents.sort(key=lambda incident: incident["started_at"] or "")
    return incidents


def rebuild():
    """Load the archives and return the rebuilt incidents."""
    catalog, history, current, raw_current = load_archives()
    return build_incidents(catalog, history, current, raw_current)


def build_metadata(incidents):
    """Compute archive metadata from the rebuilt incident list.

    Returns a dict with:
      - total_incidents, total_updates: counts
      - archive_earliest_date, archive_latest_date: ISO date strings of the
        earliest and latest update timestamps across all incidents
      - rebuilt_at: ISO timestamp of when this rebuild ran
    """
    total_updates = sum(inc["update_count"] for inc in incidents)
    dates = []
    for inc in incidents:
        if inc.get("started_at"):
            dates.append(inc["started_at"][:10])
        if inc.get("last_update"):
            dates.append(inc["last_update"][:10])
    earliest = min(dates) if dates else None
    latest = max(dates) if dates else None
    return {
        "total_incidents": len(incidents),
        "total_updates": total_updates,
        "archive_earliest_date": earliest,
        "archive_latest_date": latest,
        "rebuilt_at": datetime.now(timezone.utc).isoformat(),
    }


def with_guids(incidents):
    """Give each update the archive's stable guid with collision handling.

    Guid format: https://status.aws.amazon.com/#{slug}_{event_date}_{unix_ts}
    If a collision occurs, append a "-n" suffix.
    """
    seen_guids = {}

    for incident in incidents:
        event_date = str(int(incident["started_at"].split("T")[0].replace("-", ""))) if incident["started_at"] else "0"

        for update in incident["updates"]:
            if "guid" not in update:
                ts = int(datetime.fromisoformat(update["published"]).timestamp())
                base_guid = f"https://status.aws.amazon.com/#{incident['service']}_{event_date}_{ts}"

                # Handle guid collisions
                guid = base_guid
                collision_count = 1
                while guid in seen_guids:
                    guid = f"{base_guid}-{collision_count}"
                    collision_count += 1

                update["guid"] = guid
                seen_guids[guid] = True


def write_db(incidents, metadata):
    """Mirror the rebuild into SQLite (wipe and rewrite).

    Writes to a temp file first, then atomically replaces the target DB.
    Metadata values are stored as JSON so types survive round-tripping.
    """
    # Write to a temp file first
    out_dir = os.path.dirname(DB_PATH)
    fd, temp_path = tempfile.mkstemp(dir=out_dir, suffix=".db")
    os.close(fd)

    try:
        conn = sqlite3.connect(temp_path)
        try:
            conn.executescript(SCHEMA)
            for incident in incidents:
                conn.execute(
                    "INSERT INTO incidents "
                    "(incident_key, arn, open, started_at, last_update, update_count, title, "
                    " region, region_name, service, service_name) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        incident["key"],
                        incident.get("arn"),
                        incident.get("open", 0),
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

            # Add snapshot_fetched_at to metadata (mtime of historyevents.json, ISO UTC)
            history_path = os.path.join(DATA_DIR, "historyevents.json")
            archive_history_path = os.path.join(DATA_DIR, "archive", "historyevents.json")
            if os.path.exists(archive_history_path):
                history_path = archive_history_path

            if os.path.exists(history_path):
                mtime = os.path.getmtime(history_path)
                snapshot_fetched_at = datetime.fromtimestamp(mtime, timezone.utc).isoformat()
            else:
                snapshot_fetched_at = None

            # Store metadata as JSON
            for key, value in metadata.items():
                conn.execute(
                    "INSERT INTO metadata (key, value) VALUES (?, ?)",
                    (key, json.dumps(value)),
                )
            if snapshot_fetched_at:
                conn.execute(
                    "INSERT INTO metadata (key, value) VALUES (?, ?)",
                    ("snapshot_fetched_at", json.dumps(snapshot_fetched_at)),
                )
            conn.commit()
        finally:
            conn.close()

        # Atomically replace the target DB
        os.makedirs(out_dir, exist_ok=True)
        os.replace(temp_path, DB_PATH)
    except Exception:
        # Clean up temp file on error
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def main():
    incidents = rebuild()
    with_guids(incidents)

    for incident in incidents:
        print(
            f"{incident['update_count']:2d} updates  {incident['started_at']}  "
            f"{incident['title'][:70]}"
        )

    metadata = build_metadata(incidents)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(incidents, handle, indent=2, ensure_ascii=False)

    metadata_path = os.path.join(os.path.dirname(OUT_PATH), "metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False)

    write_db(incidents, metadata)
    print(f"wrote {DB_PATH}")
    print(f"wrote {metadata_path}")
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    sys.exit(main())