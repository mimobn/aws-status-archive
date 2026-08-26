#!/usr/bin/env python3
"""Tests for archive metadata, metric semantics, and edge cases.

Verifies that:
- Archive metadata is computed correctly
- service_days handles all edge cases (no_data, gaps, multiple transitions)
- build_metadata matches rebuild output
- Timestamp handling is consistent at timezone boundaries
"""

import json
import os
import sqlite3
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from rebuild import build_metadata, build_incidents  # noqa: E402
from parse_status import (  # noqa: E402
    iso,
    service_days,
    worst_transition_severity,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


class TestArchiveMetadata(unittest.TestCase):
    def test_build_metadata_from_incidents(self):
        incidents = [
            {
                "key": "k1",
                "started_at": "2026-03-01T12:00:00+00:00",
                "last_update": "2026-03-02T14:00:00+00:00",
                "update_count": 3,
                "title": "t1",
                "updates": [],
            },
            {
                "key": "k2",
                "started_at": "2026-02-28T10:00:00+00:00",
                "last_update": "2026-02-28T12:00:00+00:00",
                "update_count": 1,
                "title": "t2",
                "updates": [],
            },
        ]
        meta = build_metadata(incidents)
        self.assertEqual(meta["total_incidents"], 2)
        self.assertEqual(meta["total_updates"], 4)
        self.assertEqual(meta["archive_earliest_date"], "2026-02-28")
        self.assertEqual(meta["archive_latest_date"], "2026-03-02")
        self.assertIn("rebuilt_at", meta)

    def test_build_metadata_empty(self):
        meta = build_metadata([])
        self.assertEqual(meta["total_incidents"], 0)
        self.assertEqual(meta["total_updates"], 0)
        self.assertIsNone(meta["archive_earliest_date"])
        self.assertIsNone(meta["archive_latest_date"])


class TestServiceDaysEdgeCases(unittest.TestCase):
    def test_no_data_with_empty_transitions(self):
        days = service_days([], "2026-03-01", "2026-03-03")
        for day, state in days.items():
            self.assertEqual(state, "no_data", f"{day} should be no_data")

    def test_no_data_before_first_transition(self):
        transitions = [{"timestamp": 1772369485000, "current_status": "3"}]
        days = service_days(transitions, "2026-02-28", "2026-03-02")
        self.assertEqual(days["2026-02-28"], "no_data")

    def test_operational_after_resolved_transition(self):
        transitions = [
            {"timestamp": 1772369485000, "current_status": "3"},
            {"timestamp": 1772542285000, "current_status": "0"},
        ]
        days = service_days(transitions, "2026-03-01", "2026-03-04")
        # After resolution, state persists as operational
        self.assertEqual(days["2026-03-03"], "operational")

    def test_multiple_transitions_same_day_picks_last(self):
        transitions = [
            {"timestamp": 1772369485000, "current_status": "1"},
            {"timestamp": 1772373085000, "current_status": "3"},
        ]
        days = service_days(transitions, "2026-03-01", "2026-03-02")
        # Both on same day; last transition should apply
        self.assertEqual(days["2026-03-01"], "disrupted")

    def test_day_count_matches_window(self):
        transitions = [{"timestamp": 1772369485000, "current_status": "1"}]
        days = service_days(transitions, "2026-03-01", "2026-03-05")
        self.assertEqual(len(days), 5)

    def test_handles_string_timestamps(self):
        transitions = [{"timestamp": "1772369485", "current_status": "2"}]
        days = service_days(transitions, "2026-03-01", "2026-03-02")
        self.assertEqual(days["2026-03-01"], "degraded")

    def test_handles_date_field_instead_of_timestamp(self):
        transitions = [{"date": 1772369485, "status": "3"}]
        days = service_days(transitions, "2026-03-01", "2026-03-02")
        self.assertEqual(days["2026-03-01"], "disrupted")


class TestWorstTransitionSeverity(unittest.TestCase):
    def test_empty_returns_unknown(self):
        self.assertEqual(worst_transition_severity([]), "unknown")

    def test_no_data_status_yields_worst_real_severity(self):
        transitions = [
            {"current_status": None},
            {"current_status": "2"},
        ]
        self.assertEqual(worst_transition_severity(transitions), "degraded")

    def test_all_no_data_returns_unknown(self):
        transitions = [
            {"current_status": None},
            {"current_status": None},
        ]
        self.assertEqual(worst_transition_severity(transitions), "unknown")


class TestTimezoneHandling(unittest.TestCase):
    def test_iso_preserves_utc(self):
        result = iso(1772369485)
        self.assertTrue(result.endswith("+00:00"))

    def test_iso_millis_and_seconds_equal(self):
        from_sec = iso(1772369485)
        from_millis = iso(1772369485000)
        self.assertEqual(from_sec, from_millis)

    def test_midnight_utc_boundary(self):
        # 2026-03-01 00:00:00 UTC = 1772323200
        result = iso(1772323200)
        self.assertEqual(result[:10], "2026-03-01")

    def test_23_59_utc_belongs_to_same_day(self):
        # 2026-02-28 23:59:59 UTC = 1772323199
        result = iso(1772323199)
        self.assertEqual(result[:10], "2026-02-28")


if __name__ == "__main__":
    unittest.main()
