#!/usr/bin/env python3
"""Check that the archived data still matches the shape we know how to parse.

AWS warns the status data "format is subject to change". If they ever
rework it, this is what notices first: instead of parsing garbage into
silently wrong incidents, we fail loudly and let a human look.

It checks each of the three JSON archives carries the fields the
pipeline depends on. An empty history is fine - that just means nothing
is broken right now.

Usage: python scripts/check_feed_shape.py [--dir data]
"""

import argparse
import json
import os
import sys

REQUIRED_FILES = ["services.json", "historyevents.json", "currentevents.json"]

SERVICE_ROW_FIELDS = ["service", "service_name", "region_id", "region_name"]
EVENT_FIELDS = ["arn", "date", "event_log", "status", "summary"]
EVENT_LOG_FIELDS = ["timestamp", "status", "summary"]
CURRENT_EVENT_FIELDS = [
    "date",
    "arn",
    "event_log",
    "impacted_service_status_changes",
    "impacted_services",
    "region_name",
    "service",
    "service_name",
    "status",
    "summary",
]


def check_shape(directory):
    """Return a list of shape problems; empty list means it looks fine."""
    errors = []

    for filename in REQUIRED_FILES:
        path = os.path.join(directory, filename)
        if not os.path.exists(path):
            errors.append(f"missing archive file: {filename}")
            continue
        with open(path, encoding="utf-8") as handle:
            try:
                data = json.load(handle)
            except json.JSONDecodeError as exc:
                errors.append(f"{filename} is not valid JSON: {exc}")
                continue

        if filename == "services.json":
            if not isinstance(data, list):
                errors.append("services.json is not a list")
            else:
                for idx, row in enumerate(data[:100]):
                    for field in SERVICE_ROW_FIELDS:
                        if field not in row:
                            errors.append(f"services.json row {idx} is missing {field!r}")
                            break
        elif filename == "historyevents.json":
            if not isinstance(data, dict):
                errors.append("historyevents.json is not an object")
            else:
                for slug, events in data.items():
                    for idx, event in enumerate(events):
                        for field in EVENT_FIELDS:
                            if field not in event:
                                errors.append(f"history events for {slug!r}: event {idx} is missing {field!r}")
                        for entry in event.get("event_log") or []:
                            for field in EVENT_LOG_FIELDS:
                                if field not in entry:
                                    errors.append(f"history event log for {slug!r}: missing {field!r}")
        else:  # currentevents.json
            if not isinstance(data, list):
                errors.append("currentevents.json is not a list")
            else:
                for event in data:
                    for field in CURRENT_EVENT_FIELDS:
                        if field not in event:
                            errors.append(f"current event is missing {field!r}")

    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="data")
    args = parser.parse_args()

    errors = check_shape(args.dir)
    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())