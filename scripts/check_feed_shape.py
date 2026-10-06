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
from pathlib import Path

REQUIRED_FILES = ["services.json", "historyevents.json", "currentevents.json"]

# Required service row fields (region_id and region_name are optional)
SERVICE_ROW_REQUIRED_FIELDS = ["service", "service_name"]
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
# Required fields for impacted_service_status_changes entries
IMPACTED_SERVICE_STATUS_CHANGE_FIELDS = ["timestamp", "service", "current_status"]


def _is_int_like(value):
    """Check if a value is int-like (int or string of digits)."""
    if isinstance(value, int):
        return True
    if isinstance(value, str) and value.isdigit():
        return True
    return False


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
            elif not data:
                errors.append("services.json is an empty list")
            else:
                # Check ALL rows, not just first 100
                for idx, row in enumerate(data):
                    if not isinstance(row, dict):
                        errors.append(f"services.json row {idx} is not a dict")
                        continue
                    # Check required fields
                    for field in SERVICE_ROW_REQUIRED_FIELDS:
                        if field not in row:
                            errors.append(f"services.json row {idx} is missing {field!r}")
                    # Validate types: service and service_name should be strings
                    for field in SERVICE_ROW_REQUIRED_FIELDS:
                        if field in row and not isinstance(row[field], str):
                            errors.append(f"services.json row {idx} field {field!r} is not a string")
                    # Validate optional region fields (can be string or None)
                    if "region_id" in row and row["region_id"] is not None and not isinstance(row["region_id"], str):
                        errors.append(f"services.json row {idx} field 'region_id' is not a string or null")
                    if "region_name" in row and row["region_name"] is not None and not isinstance(row["region_name"], str):
                        errors.append(f"services.json row {idx} field 'region_name' is not a string or null")
        elif filename == "historyevents.json":
            if not isinstance(data, dict):
                errors.append("historyevents.json is not an object")
            else:
                for slug, events in data.items():
                    if not isinstance(events, list):
                        errors.append(f"historyevents.json value for {slug!r} is not a list")
                        continue
                    for idx, event in enumerate(events):
                        if not isinstance(event, dict):
                            errors.append(f"history events for {slug!r}: event {idx} is not a dict")
                            continue
                        # Check required fields
                        for field in EVENT_FIELDS:
                            if field not in event:
                                errors.append(f"history events for {slug!r}: event {idx} is missing {field!r}")
                        # Validate types
                        if "date" in event and not _is_int_like(event["date"]):
                            errors.append(f"history events for {slug!r}: event {idx} field 'date' is not int-like")
                        if "status" in event and not _is_int_like(event["status"]):
                            errors.append(f"history events for {slug!r}: event {idx} field 'status' is not int-like")
                        # Check event_log entries
                        event_log = event.get("event_log")
                        if not isinstance(event_log, list):
                            errors.append(f"history event log for {slug!r}: event_log is not a list")
                        else:
                            for entry in event_log:
                                if not isinstance(entry, dict):
                                    errors.append(f"history event log for {slug!r}: entry is not a dict")
                                    continue
                                for field in EVENT_LOG_FIELDS:
                                    if field not in entry:
                                        errors.append(f"history event log for {slug!r}: missing {field!r}")
                                # Validate types
                                if "timestamp" in entry and not _is_int_like(entry["timestamp"]):
                                    errors.append(f"history event log for {slug!r}: 'timestamp' is not int-like")
                                if "status" in entry and not _is_int_like(entry["status"]):
                                    errors.append(f"history event log for {slug!r}: 'status' is not int-like")
        else:  # currentevents.json
            if not isinstance(data, list):
                errors.append("currentevents.json is not a list")
            else:
                for idx, event in enumerate(data):
                    if not isinstance(event, dict):
                        errors.append(f"current event {idx} is not a dict")
                        continue
                    # Check required fields
                    for field in CURRENT_EVENT_FIELDS:
                        if field not in event:
                            errors.append(f"current event {idx} is missing {field!r}")
                    # Validate types
                    if "date" in event and not _is_int_like(event["date"]):
                        errors.append(f"current event {idx} field 'date' is not int-like")
                    if "status" in event and not _is_int_like(event["status"]):
                        errors.append(f"current event {idx} field 'status' is not int-like")
                    # Check impacted_service_status_changes entries
                    changes = event.get("impacted_service_status_changes")
                    if not isinstance(changes, list):
                        errors.append(f"current event {idx}: 'impacted_service_status_changes' is not a list")
                    else:
                        for change_idx, change in enumerate(changes):
                            if not isinstance(change, dict):
                                errors.append(f"current event {idx}: impacted_service_status_changes[{change_idx}] is not a dict")
                                continue
                            for field in IMPACTED_SERVICE_STATUS_CHANGE_FIELDS:
                                if field not in change:
                                    errors.append(f"current event {idx}: impacted_service_status_changes[{change_idx}] is missing {field!r}")
                            # Validate types
                            if "timestamp" in change and not _is_int_like(change["timestamp"]):
                                errors.append(f"current event {idx}: impacted_service_status_changes[{change_idx}] 'timestamp' is not int-like")
                            if "current_status" in change and not _is_int_like(change["current_status"]):
                                errors.append(f"current event {idx}: impacted_service_status_changes[{change_idx}] 'current_status' is not int-like")

    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    # Default --dir to data/ relative to repo root (via __file__)
    repo_root = Path(__file__).resolve().parent.parent
    default_dir = str(repo_root / "data")
    parser.add_argument("--dir", default=default_dir)
    args = parser.parse_args()

    errors = check_shape(args.dir)
    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())