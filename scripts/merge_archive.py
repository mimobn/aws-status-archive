#!/usr/bin/env python3
"""Merge AWS status data into a permanent archive.

AWS keeps ~12 months of history in data/*.json files, but old incidents
eventually age out. This script creates a merged archive that preserves
all historical data by union-ing new snapshots with archived data.

Default mode: read from data/ and merge into data/archive/
--backfill-from-git: rebuild archive from entire git history
"""

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = BASE_DIR / "data"
DEFAULT_ARCHIVE_DIR = BASE_DIR / "data" / "archive"

# Import canonical_json from fetch_archive
sys.path.insert(0, str(Path(__file__).parent))
from fetch_archive import canonical_json


class ArchiveCorrupt(Exception):
    """The existing archive file can't be parsed; merging would destroy it."""


def log_key(entry):
    """Identity of an event_log entry: AWS may reword an update in place, so
    the newest text for a (timestamp, status) pair replaces the old one."""
    return (int(entry["timestamp"]), str(entry.get("status", "")))


def safe_read_json(path):
    """Read JSON file, return parsed data or None if missing/unparseable."""
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] Could not parse {path}: {e}", file=sys.stderr)
        return None


def merge_historyevents(archived, new_data):
    """Merge historyevents data.

    Union of events keyed by arn, fallback f"{slug}_{date}".
    Newest version replaces older fields.
    event_log entries unioned by (timestamp, str(status), message), sorted by timestamp.
    Slugs sorted, events sorted by int(date).
    Drop slugs with empty event lists.
    """
    if not isinstance(archived, dict):
        archived = {}
    if not isinstance(new_data, dict):
        new_data = {}

    result = dict(archived)

    # Process new events
    for slug, events in new_data.items():
        if not isinstance(events, list):
            continue

        # Initialize slug if not present
        if slug not in result:
            result[slug] = []

        # Build map of existing events by key
        existing_map = {}
        for event in result[slug]:
            key = event.get("arn") or f"{slug}_{event.get('date', '')}"
            existing_map[key] = event

        # Merge new events
        for new_event in events:
            key = new_event.get("arn") or f"{slug}_{new_event.get('date', '')}"

            if key in existing_map:
                # Merge with existing event
                old_event = existing_map[key]
                # Merge event_log entries
                old_log = {log_key(entry): entry for entry in old_event.get("event_log", [])}
                for new_entry in new_event.get("event_log", []):
                    old_log[log_key(new_entry)] = new_entry

                # Sort event_log by timestamp
                merged_log = sorted(old_log.values(), key=lambda x: int(x.get("timestamp", 0)))

                # Update event with new values (newest wins) but keep merged log
                merged_event = dict(new_event)
                merged_event["event_log"] = merged_log
                existing_map[key] = merged_event
            else:
                # Add new event
                existing_map[key] = new_event

        # Sort events by date
        result[slug] = sorted(existing_map.values(), key=lambda x: int(x.get("date", 0)))

    # Ensure all slugs have sorted events, then sort slugs and remove empty ones
    for slug in result:
        result[slug] = sorted(result[slug], key=lambda x: int(x.get("date", 0)))

    result = {k: v for k, v in sorted(result.items()) if v}

    return result


def merge_currentevents(archived, new_data):
    """Merge currentevents data.

    List of events, dedupe by arn.
    Last-seen wins.
    Sort by (int(date), arn).
    """
    if not isinstance(archived, list):
        archived = []
    if not isinstance(new_data, list):
        new_data = []

    # Build map by arn (last-seen wins)
    events_map = {}
    for event in archived:
        arn = event.get("arn")
        if arn:
            events_map[arn] = event

    for event in new_data:
        arn = event.get("arn")
        if arn:
            events_map[arn] = event

    # Sort by (date, arn)
    result = sorted(events_map.values(), key=lambda x: (int(x.get("date", 0)), x.get("arn", "")))
    return result


def merge_services(archived, new_data):
    """Merge services data.

    List of service rows, keyed by 'service'.
    Union by service (last-seen wins).
    Sort by service.
    """
    if not isinstance(archived, list):
        archived = []
    if not isinstance(new_data, list):
        new_data = []

    # Build map by service (last-seen wins)
    services_map = {}
    for service in archived:
        service_name = service.get("service")
        if service_name:
            services_map[service_name] = service

    for service in new_data:
        service_name = service.get("service")
        if service_name:
            services_map[service_name] = service

    # Sort by service
    result = sorted(services_map.values(), key=lambda x: x.get("service", ""))
    return result


def merge_all(data_dir, archive_dir):
    """Merge all data files from data_dir into archive_dir.

    Returns dict of {filename: (old_content, new_content)} for changed files.
    """
    archive_dir.mkdir(parents=True, exist_ok=True)

    changes = {}

    # Process each file
    for fname in ["historyevents.json", "currentevents.json", "services.json"]:
        data_path = data_dir / fname
        archive_path = archive_dir / fname

        # Read current archive. A present-but-unreadable archive must never be
        # replaced, or every aged-out event it holds would be lost.
        archived_data = safe_read_json(archive_path)
        if archived_data is None:
            if archive_path.exists():
                raise ArchiveCorrupt(f"{archive_path} exists but could not be read; refusing to overwrite")
            archived_data = {} if fname == "historyevents.json" else []

        # Read new data
        new_data = safe_read_json(data_path)
        if new_data is None:
            if not archive_path.exists():
                print(f"[WARN] Skipping {fname}: file not found and no archive", file=sys.stderr)
            continue

        # Merge
        if fname == "historyevents.json":
            merged = merge_historyevents(archived_data, new_data)
        elif fname == "currentevents.json":
            merged = merge_currentevents(archived_data, new_data)
        else:  # services.json
            merged = merge_services(archived_data, new_data)

        # Write if changed
        new_text = canonical_json(merged)
        old_text = archive_path.read_text(encoding="utf-8") if archive_path.exists() else None

        if new_text != old_text:
            archive_path.write_text(new_text, encoding="utf-8")
            changes[fname] = (old_text, new_text)
            try:
                rel_path = archive_path.relative_to(BASE_DIR)
            except ValueError:
                rel_path = archive_path
            print(f"updated: {rel_path}")
        else:
            print(f"no change: {fname}")

    return changes


def backfill_from_git(data_dir, archive_dir):
    """Rebuild archive from git history.

    List commits oldest->newest with:
      git log --reverse --format=%H -- data/historyevents.json data/currentevents.json data/services.json
    For each commit, git show <sha>:data/<file> (skip missing/unparseable).
    Then merge working-tree files last.
    """
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Get list of commits
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "--reverse",
                "--format=%H",
                "--",
                "data/historyevents.json",
                "data/currentevents.json",
                "data/services.json",
            ],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(f"[WARN] git log failed: {result.stderr}", file=sys.stderr)
            commits = []
        else:
            commits = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
    except Exception as e:
        print(f"[WARN] Could not run git log: {e}", file=sys.stderr)
        commits = []

    print(f"[INFO] Found {len(commits)} commits to backfill", file=sys.stderr)

    # Seed from the existing archive so a backfill can only ever add data.
    archive_data = {}
    for fname, empty in (("historyevents.json", {}), ("currentevents.json", []), ("services.json", [])):
        path = archive_dir / fname
        existing = safe_read_json(path)
        if existing is None and path.exists():
            raise ArchiveCorrupt(f"{path} exists but could not be read; refusing to overwrite")
        archive_data[fname] = existing if existing is not None else empty

    # Process each commit
    for sha in commits:
        for fname in ["historyevents.json", "currentevents.json", "services.json"]:
            try:
                result = subprocess.run(
                    ["git", "show", f"{sha}:data/{fname}"],
                    cwd=BASE_DIR,
                    capture_output=True,
                    text=False,
                    check=False,
                )
                if result.returncode != 0:
                    continue

                # Decode JSON
                try:
                    data = json.loads(result.stdout.decode("utf-8"))
                except Exception:
                    continue

                # Merge into archive
                if fname == "historyevents.json":
                    archive_data[fname] = merge_historyevents(archive_data[fname], data)
                elif fname == "currentevents.json":
                    archive_data[fname] = merge_currentevents(archive_data[fname], data)
                else:  # services.json
                    archive_data[fname] = merge_services(archive_data[fname], data)
            except Exception as e:
                print(f"[WARN] Could not process {sha}:{fname}: {e}", file=sys.stderr)
                continue

    print(f"[INFO] Backfill complete, merging working-tree files", file=sys.stderr)

    # Merge working-tree files last
    for fname in ["historyevents.json", "currentevents.json", "services.json"]:
        data_path = data_dir / fname
        new_data = safe_read_json(data_path)
        if new_data is not None:
            if fname == "historyevents.json":
                archive_data[fname] = merge_historyevents(archive_data[fname], new_data)
            elif fname == "currentevents.json":
                archive_data[fname] = merge_currentevents(archive_data[fname], new_data)
            else:  # services.json
                archive_data[fname] = merge_services(archive_data[fname], new_data)

    # Write archive files
    changes = {}
    for fname, merged in archive_data.items():
        archive_path = archive_dir / fname
        new_text = canonical_json(merged)
        old_text = archive_path.read_text(encoding="utf-8") if archive_path.exists() else None

        if new_text != old_text:
            archive_path.write_text(new_text, encoding="utf-8")
            changes[fname] = (old_text, new_text)
            try:
                rel_path = archive_path.relative_to(BASE_DIR)
            except ValueError:
                rel_path = archive_path
            print(f"updated: {rel_path}")
        else:
            print(f"no change: {fname}")

    return changes


def main():
    parser = argparse.ArgumentParser(description="Merge AWS status data into permanent archive")
    parser.add_argument(
        "--backfill-from-git",
        action="store_true",
        help="Rebuild archive from entire git history",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Path to data directory (default: data/)",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=DEFAULT_ARCHIVE_DIR,
        help="Path to archive directory (default: data/archive/)",
    )

    args = parser.parse_args()

    try:
        if args.backfill_from_git:
            backfill_from_git(args.data_dir, args.archive_dir)
        else:
            merge_all(args.data_dir, args.archive_dir)
    except ArchiveCorrupt as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
