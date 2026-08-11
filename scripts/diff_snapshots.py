#!/usr/bin/env python3
"""Describe what changed between two snapshots of the feed.

The feed only holds ongoing incidents, so the interesting things are:
a new incident showing up, an incident getting a new update, or an
incident dropping off entirely (usually meaning it was resolved).
This is the machine-readable version of "what happened since the last
check", which the workflow can use to alert.

Usage: compare a previous snapshot against a current one:
    python scripts/diff_snapshots.py --previous old.rss --current new.rss
"""

import argparse
import json
import sys

from parse_snapshot import parse_snapshot_text
from rebuild import incident_key


def group_by_incident(items):
    groups = {}
    for item in items:
        groups.setdefault(incident_key(item["guid"]), []).append(item)
    for updates in groups.values():
        updates.sort(key=lambda update: update["published"])
    return groups


def diff_incidents(previous, current):
    """Diff two snapshot texts into a structured change report.

    `previous` and `current` are raw feed XML strings. The report lists
    new incidents, removed incidents, and incidents that picked up new
    updates in between.
    """
    prev_groups = group_by_incident(parse_snapshot_text(previous))
    curr_groups = group_by_incident(parse_snapshot_text(current))

    prev_keys = set(prev_groups)
    curr_keys = set(curr_groups)

    new = sorted(curr_keys - prev_keys)
    removed = sorted(prev_keys - curr_keys)

    with_new_updates = []
    for key in sorted(curr_keys & prev_keys):
        prev_guids = {update["guid"] for update in prev_groups[key]}
        added = [update for update in curr_groups[key] if update["guid"] not in prev_guids]
        if added:
            with_new_updates.append(
                {
                    "incident_key": key,
                    "new_updates": len(added),
                    "latest_severity": added[-1]["severity"],
                    "latest_title": added[-1]["title"],
                }
            )

    return {
        "previous_items": sum(len(v) for v in prev_groups.values()),
        "current_items": sum(len(v) for v in curr_groups.values()),
        "new_incidents": [
            {
                "incident_key": key,
                "updates": len(curr_groups[key]),
                "title": curr_groups[key][0]["title"],
            }
            for key in new
        ],
        "removed_incidents": [
            {
                "incident_key": key,
                "updates": len(prev_groups[key]),
                "title": prev_groups[key][0]["title"],
            }
            for key in removed
        ],
        "incidents_with_new_updates": with_new_updates,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", required=True, help="path to the previous snapshot")
    parser.add_argument("--current", required=True, help="path to the current snapshot")
    parser.add_argument("--json", action="store_true", help="print the raw report as JSON")
    args = parser.parse_args()

    with open(args.previous, "r", encoding="utf-8") as handle:
        previous = handle.read()
    with open(args.current, "r", encoding="utf-8") as handle:
        current = handle.read()

    report = diff_incidents(previous, current)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"previous: {report['previous_items']} updates | current: {report['current_items']} updates")
    for incident in report["new_incidents"]:
        print(f"NEW  {incident['incident_key'].rsplit('#', 1)[-1]}  {incident['title']}")
    for incident in report["removed_incidents"]:
        print(f"END  {incident['incident_key'].rsplit('#', 1)[-1]}  {incident['title']}")
    for incident in report["incidents_with_new_updates"]:
        print(
            f"UP   {incident['incident_key'].rsplit('#', 1)[-1]}  "
            f"+{incident['new_updates']} update(s)  [{incident['latest_severity']}]"
        )

    changed = report["new_incidents"] or report["removed_incidents"] or report["incidents_with_new_updates"]
    return 0 if changed else 1


if __name__ == "__main__":
    sys.exit(main())