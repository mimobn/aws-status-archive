#!/usr/bin/env python3
"""Rebuild incident timelines from the archived snapshots.

Git history holds every daily snapshot of the feed. This replays
them in order, dedupes the updates by guid, groups them by incident
key (the guid without its trailing timestamp), and writes out one
timeline per incident.

Rebuilding is deterministic: same history in, same output out.
"""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime

from parse_snapshot import parse_snapshot_text

SNAPSHOT_PATH = "data/aws-status.rss"
OUT_PATH = "out/incidents.json"
DB_PATH = "out/status.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS updates (
    guid TEXT PRIMARY KEY,
    incident_key TEXT NOT NULL,
    published TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS incidents (
    incident_key TEXT PRIMARY KEY,
    started_at TEXT,
    last_update TEXT,
    update_count INTEGER,
    title TEXT
);
"""


def snapshot_history():
    result = subprocess.run(
        ["git", "log", "--format=%H", "--", SNAPSHOT_PATH],
        capture_output=True,
        text=True,
        check=True,
    )
    shas = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    shas.reverse()
    return shas


def snapshot_at(sha):
    result = subprocess.run(
        ["git", "show", f"{sha}:{SNAPSHOT_PATH}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def incident_key(guid):
    # guids look like ...#multipleservices-me-central-1_1777533954
    # the timestamp suffix changes per update; the rest is the incident.
    return guid.rsplit("_", 1)[0] if "_" in guid else guid


def build_incidents_from_snapshots(snapshots):
    """Merge a list of snapshot texts into incident timelines."""
    updates = {}
    for content in snapshots:
        for item in parse_snapshot_text(content):
            updates[item["guid"]] = item

    by_key = {}
    for item in updates.values():
        by_key.setdefault(incident_key(item["guid"]), []).append(item)

    incidents = []
    for key, items in by_key.items():
        items.sort(key=lambda item: item["published"] or datetime.min)
        incidents.append(
            {
                "key": key,
                "started_at": items[0]["published"],
                "last_update": items[-1]["published"],
                "update_count": len(items),
                "title": items[0]["title"].split(":", 1)[1].strip(),
                "updates": [
                    {
                        "guid": item["guid"],
                        "published": item["published"],
                        "severity": item["severity"],
                        "title": item["title"],
                        "description": item["description"],
                    }
                    for item in items
                ],
            }
        )
    return incidents


def build_incidents(shas):
    return build_incidents_from_snapshots([snapshot_at(sha) for sha in shas])


def write_db(incidents):
    """Write incidents and their updates into SQLite.

    The rebuild is the source of truth, so this wipes and rewrites the
    tables. Running it twice in a row leaves the db byte-identical
    except for the row order.
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        conn.execute("DELETE FROM updates")
        conn.execute("DELETE FROM incidents")
        for incident in incidents:
            conn.execute(
                "INSERT INTO incidents "
                "(incident_key, started_at, last_update, update_count, title) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    incident["key"],
                    iso(incident["started_at"]),
                    iso(incident["last_update"]),
                    incident["update_count"],
                    incident["title"],
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
                        iso(update["published"]),
                        update["severity"],
                        update["title"],
                        update["description"],
                    ),
                )
        conn.commit()
    finally:
        conn.close()


def iso(value):
    return value.isoformat() if value is not None else None


def main():
    shas = snapshot_history()
    print(f"{len(shas)} snapshot(s) in history")

    incidents = build_incidents(shas)
    incidents.sort(key=lambda incident: incident["started_at"] or datetime.min)

    for incident in incidents:
        print(
            f"{incident['update_count']:2d} updates  {iso(incident['started_at'])}  "
            f"{incident['title'][:70]}"
        )

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(incidents, handle, indent=2, default=lambda value: value.isoformat())

    write_db(incidents)
    print(f"wrote {DB_PATH}")


if __name__ == "__main__":
    main()
