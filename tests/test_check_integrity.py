#!/usr/bin/env python3
"""Tests for the integrity checker."""

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from check_integrity import run_checks  # noqa: E402
from rebuild import build_metadata  # noqa: E402

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
CREATE TABLE IF NOT EXISTS services (
    incident_key TEXT NOT NULL,
    service_slug TEXT NOT NULL,
    service_name TEXT,
    severity TEXT,
    max_severity TEXT,
    PRIMARY KEY (incident_key, service_slug)
);
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
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
    meta = build_metadata(one_incident_rebuild() if len(incidents) == 1 else [])
    for k, v in meta.items():
        conn.execute("INSERT INTO metadata VALUES (?, ?)", (k, str(v)))
    conn.commit()
    conn.close()


class TestIntegrityChecks(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmpdir = tmp.name

    def test_empty_db_fails_on_missing_tables(self):
        conn = sqlite3.connect(":memory:")
        results = run_checks(conn, empty_rebuild())
        conn.close()
        failures = [name for name, ok, _ in results if not ok]
        self.assertIn("incidents table exists", failures)
        self.assertIn("services table exists", failures)

    def test_clean_db_passes(self):
        path = os.path.join(self.tmpdir, "test-clean.db")
        build_db(
            path,
            [("k1", "2026-03-01T00:00:00Z", 1, "t")],
            [("g1", "k1", "2026-03-01T00:00:00Z", "impacted", "t", "d")],
        )
        conn = sqlite3.connect(path)
        self.addCleanup(conn.close)
        results = run_checks(conn, one_incident_rebuild())
        conn.close()
        failures = [name for name, ok, _ in results if not ok]
        self.assertEqual(failures, [])

    def test_orphan_update_fails(self):
        path = os.path.join(self.tmpdir, "test-orphan.db")
        build_db(
            path,
            [("k1", "2026-03-01T00:00:00Z", 1, "t")],
            [
                ("g1", "k1", "2026-03-01T00:00:00Z", "impacted", "t", "d"),
                ("g2", "ghost-key", "2026-03-01T00:00:00Z", "impacted", "t", "d"),
            ],
        )
        conn = sqlite3.connect(path)
        self.addCleanup(conn.close)
        results = run_checks(conn, one_incident_rebuild())
        conn.close()
        failures = [name for name, ok, _ in results if not ok]
        self.assertIn("no orphan updates", failures)

    def test_count_mismatch_fails(self):
        path = os.path.join(self.tmpdir, "test-mismatch.db")
        build_db(
            path,
            [("k1", "2026-03-01T00:00:00Z", 1, "t")],
            [("g1", "k1", "2026-03-01T00:00:00Z", "impacted", "t", "d")],
        )
        conn = sqlite3.connect(path)
        self.addCleanup(conn.close)
        # reference rebuild claims 2 incidents, db has 1
        results = run_checks(conn, one_incident_rebuild() * 2)
        conn.close()
        failures = [name for name, ok, _ in results if not ok]
        self.assertIn("incident count matches rebuild", failures)


if __name__ == "__main__":
    unittest.main()