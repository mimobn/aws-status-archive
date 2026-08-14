#!/usr/bin/env python3
"""Check that the rebuilt database is consistent and complete.

The rebuild is supposed to be a lossless mirror of the archived AWS
Service Health JSON files. This verifies that:

  * all three tables exist,
  * every incident has at least one update,
  * every update belongs to a known incident (no orphans),
  * every update guid is unique,
  * the database matches a fresh in-memory rebuild from data/*.json.

Exits nonzero if anything fails. Run after every rebuild, e.g. in CI.

Usage: python scripts/check_integrity.py [--db out/status.db]
"""

import argparse
import os
import sqlite3
import sys

from rebuild import DB_PATH, rebuild


def run_checks(conn, incidents):
    """Run all integrity checks against an open connection.

    Returns a list of (name, ok, detail) tuples; main() prints them.
    `incidents` is the fresh in-memory rebuild used as the reference.
    """
    results = []

    def check(name, ok, detail=""):
        results.append((name, ok, detail))

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    check("incidents table exists", "incidents" in tables)
    check("updates table exists", "updates" in tables)
    check("services table exists", "services" in tables)
    if "incidents" not in tables or "updates" not in tables:
        return results

    orphan_count = conn.execute(
        "SELECT count(*) FROM updates u "
        "LEFT JOIN incidents i ON u.incident_key = i.incident_key "
        "WHERE i.incident_key IS NULL"
    ).fetchone()[0]
    check("no orphan updates", orphan_count == 0, f"{orphan_count} orphan(s)")

    empty_incidents = conn.execute(
        "SELECT count(*) FROM incidents i "
        "LEFT JOIN updates u ON i.incident_key = u.incident_key "
        "WHERE u.guid IS NULL"
    ).fetchone()[0]
    check("every incident has updates", empty_incidents == 0, f"{empty_incidents} empty")

    duplicate_guids = conn.execute(
        "SELECT count(*) FROM (SELECT guid FROM updates GROUP BY guid HAVING count(*) > 1)"
    ).fetchone()[0]
    check("update guids are unique", duplicate_guids == 0, f"{duplicate_guids} duplicate(s)")

    orphan_services = conn.execute(
        "SELECT count(*) FROM services s "
        "LEFT JOIN incidents i ON s.incident_key = i.incident_key "
        "WHERE i.incident_key IS NULL"
    ).fetchone()[0]
    check("no orphan services", orphan_services == 0, f"{orphan_services} orphan(s)")

    expected_incidents = len(incidents)
    expected_updates = sum(incident["update_count"] for incident in incidents)
    expected_services = sum(len(incident.get("services") or {}) for incident in incidents)

    db_incidents = conn.execute("SELECT count(*) FROM incidents").fetchone()[0]
    db_updates = conn.execute("SELECT count(*) FROM updates").fetchone()[0]
    db_services = conn.execute("SELECT count(*) FROM services").fetchone()[0]

    check("incident count matches rebuild", db_incidents == expected_incidents,
          f"db {db_incidents} vs rebuild {expected_incidents}")
    check("update count matches rebuild", db_updates == expected_updates,
          f"db {db_updates} vs rebuild {expected_updates}")
    check("service count matches rebuild", db_services == expected_services,
          f"db {db_services} vs rebuild {expected_services}")

    rebuilt_by_key = {incident["key"]: incident for incident in incidents}
    for key, started_at, update_count in conn.execute(
        "SELECT incident_key, started_at, update_count FROM incidents"
    ).fetchall():
        expected = rebuilt_by_key.get(key)
        if expected is None:
            check(f"db incident {key} exists in rebuild", False)
            continue
        check(
            f"{key} matches rebuild",
            expected["update_count"] == update_count,
            f"updates db {update_count} vs rebuild {expected['update_count']}",
        )
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB_PATH)
    args = parser.parse_args()

    failures = []
    try:
        conn = sqlite3.connect(args.db)
    except sqlite3.Error as exc:
        print(f"[FAIL] could not open database {args.db}: {exc}")
        return 1

    try:
        incidents = rebuild()
        for name, ok, detail in run_checks(conn, incidents):
            print(f"[{'ok' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail and not ok else ""))
            if not ok:
                failures.append(name)
    finally:
        conn.close()

    if failures:
        print(f"\n{len(failures)} check(s) failed")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())