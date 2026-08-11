#!/usr/bin/env python3
"""Tests for the integrity checker."""

import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from check_integrity import run_checks  # noqa: E402

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


def empty_rebuild():
    return []


def one_incident_rebuild():
    return [
        {
            "key": "k1",
            "started_at": "2026-03-01T00:00:00Z",
            "last_update": "2026-03-01T01:00:00Z",
            "update_count": 1,
            "title": "t",
            "updates": [],
        }
    ]


def build_db(path, incidents, updates):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    for key, started, count, title in incidents:
        conn.execute(
            "INSERT INTO incidents VALUES (?, ?, ?, ?, ?)",
            (key, started, started, count, title),
        )
    for guid, key, published, severity, title, desc in updates:
        conn.execute(
            "INSERT INTO updates VALUES (?, ?, ?, ?, ?, ?)",
            (guid, key, published, severity, title, desc),
        )
    conn.commit()
    conn.close()


class TestIntegrityChecks(unittest.TestCase):
    def test_empty_db_fails_on_missing_tables(self):
        conn = sqlite3.connect(":memory:")
        results = run_checks(conn, empty_rebuild())
        conn.close()
        failures = [name for name, ok, _ in results if not ok]
        self.assertIn("incidents table exists", failures)

    def test_clean_db_passes(self):
        path = "/tmp/opencode/test-clean.db"
        build_db(
            path,
            [("k1", "2026-03-01T00:00:00Z", 1, "t")],
            [("g1", "k1", "2026-03-01T00:00:00Z", "impact", "t", "d")],
        )
        conn = sqlite3.connect(path)
        results = run_checks(conn, one_incident_rebuild())
        conn.close()
        os.unlink(path)
        failures = [name for name, ok, _ in results if not ok]
        self.assertEqual(failures, [])

    def test_orphan_update_fails(self):
        path = "/tmp/opencode/test-orphan.db"
        build_db(
            path,
            [("k1", "2026-03-01T00:00:00Z", 1, "t")],
            [
                ("g1", "k1", "2026-03-01T00:00:00Z", "impact", "t", "d"),
                ("g2", "ghost-key", "2026-03-01T00:00:00Z", "impact", "t", "d"),
            ],
        )
        conn = sqlite3.connect(path)
        results = run_checks(conn, one_incident_rebuild())
        conn.close()
        os.unlink(path)
        failures = [name for name, ok, _ in results if not ok]
        self.assertIn("no orphan updates", failures)

    def test_count_mismatch_fails(self):
        path = "/tmp/opencode/test-mismatch.db"
        build_db(
            path,
            [("k1", "2026-03-01T00:00:00Z", 1, "t")],
            [("g1", "k1", "2026-03-01T00:00:00Z", "impact", "t", "d")],
        )
        conn = sqlite3.connect(path)
        # reference rebuild claims 2 incidents, db has 1
        results = run_checks(conn, one_incident_rebuild() * 2)
        conn.close()
        os.unlink(path)
        failures = [name for name, ok, _ in results if not ok]
        self.assertIn("incident count matches rebuild", failures)


if __name__ == "__main__":
    unittest.main()
