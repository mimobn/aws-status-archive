#!/usr/bin/env python3
"""Describe what changed between two archived JSON states.

Compares two data/ snapshots of the AWS Service Health archives and
reports new incidents, removed incidents, and incidents that picked up
new updates in between. This is the machine-readable version of
"what happened since the last check".

Usage: compare a previous snapshot against a current one:
    python scripts/diff_snapshots.py --previous old/ --current new/

Each side is a directory containing services.json, historyevents.json
and currentevents.json (the artifacts fetch_archive.py writes).
"""

import argparse
import json
import os
import sys


def _strip_title_prefix(title):
    """Strip [RESOLVED] or similar prefixes from incident title (case-insensitive)."""
    import re
    # Match [ANYTHING] at the start of the string, case-insensitive
    return re.sub(r'^\[[^\]]+\]\s*', '', title, flags=re.IGNORECASE)


def load_state(directory):
    """Load the three JSON archives from a directory into incident keys.

    Returns a dict of {incident_key: {updates, title}}.
    If historyevents.json is missing, empty, or invalid, treats as empty state
    and prints a warning to stderr.
    """
    history_path = os.path.join(directory, "historyevents.json")
    if not os.path.exists(history_path):
        return {}

    try:
        with open(history_path, encoding="utf-8") as handle:
            history = json.load(handle)
    except (json.JSONDecodeError, IOError) as exc:
        print(f"[WARN] {directory}/historyevents.json: {exc} — treating as empty", file=sys.stderr)
        return {}

    if not isinstance(history, dict):
        print(f"[WARN] {directory}/historyevents.json is not a dict — treating as empty", file=sys.stderr)
        return {}

    if not history:
        return {}

    incidents = {}
    for slug, events in history.items():
        if not events:
            continue
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, dict):
                continue
            event_dot = str(int(event["date"])) if event.get("date") else "0"
            key = f"https://status.aws.amazon.com/#{slug}_{event_dot}"
            title = event.get("summary") or slug
            # Strip [RESOLVED] and similar prefixes
            title = _strip_title_prefix(title)
            incidents[key] = {
                "updates": len(event.get("event_log") or []),
                "title": title,
            }
    return incidents


def diff_incidents(previous, current):
    """Diff two archive states into a structured change report.

    `previous` and `current` are dicts of {incident_key: {...}}. The
    report lists new incidents, removed incidents, and incidents that
    picked up new updates in between.
    """
    prev_keys = set(previous)
    curr_keys = set(current)

    new = sorted(curr_keys - prev_keys)
    removed = sorted(prev_keys - curr_keys)

    with_new_updates = []
    for key in sorted(curr_keys & prev_keys):
        prev_count = previous[key]["updates"]
        curr_count = current[key]["updates"]
        if curr_count > prev_count:
            with_new_updates.append(
                {
                    "incident_key": key,
                    "new_updates": curr_count - prev_count,
                    "title": current[key]["title"],
                }
            )

    return {
        "previous_items": sum(v["updates"] for v in previous.values()),
        "current_items": sum(v["updates"] for v in current.values()),
        "new_incidents": [
            {
                "incident_key": key,
                "updates": current[key]["updates"],
                "title": current[key]["title"],
            }
            for key in new
        ],
        "removed_incidents": [
            {
                "incident_key": key,
                "updates": previous[key]["updates"],
                "title": previous[key]["title"],
            }
            for key in removed
        ],
        "incidents_with_new_updates": with_new_updates,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", required=True, help="directory with the previous snapshot")
    parser.add_argument("--current", required=True, help="directory with the current snapshot")
    parser.add_argument("--json", action="store_true", help="print the raw report as JSON")
    parser.add_argument("--exit-code", action="store_true", help="exit 1 if unchanged (text mode only)")
    args = parser.parse_args()

    report = diff_incidents(load_state(args.previous), load_state(args.current))

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"previous: {report['previous_items']} updates | current: {report['current_items']} updates")
    for incident in report["new_incidents"]:
        print(f"NEW  {incident['incident_key'].rsplit('#', 1)[-1]}  {incident['title']}")
    for incident in report["removed_incidents"]:
        print(f"AGED-OUT  {incident['incident_key'].rsplit('#', 1)[-1]}  {incident['title']}")
    for incident in report["incidents_with_new_updates"]:
        print(
            f"UP   {incident['incident_key'].rsplit('#', 1)[-1]}  "
            f"+{incident['new_updates']} update(s)"
        )

    changed = report["new_incidents"] or report["removed_incidents"] or report["incidents_with_new_updates"]
    # Default to 0 (success) unless --exit-code flag is set
    if args.exit_code:
        return 0 if changed else 1
    else:
        return 0


if __name__ == "__main__":
    sys.exit(main())