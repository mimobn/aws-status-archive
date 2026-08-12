#!/usr/bin/env python3
"""Tests for the snapshot parser and the incident rebuild."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from parse_snapshot import parse_snapshot_text  # noqa: E402
from rebuild import build_incidents_from_snapshots  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "all.rss")


def fixture_text():
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        return handle.read()


class TestParseSnapshot(unittest.TestCase):
    def test_parses_every_item(self):
        items = parse_snapshot_text(fixture_text())
        self.assertEqual(len(items), 36)

    def test_classifies_severity(self):
        items = parse_snapshot_text(fixture_text())
        severities = {item["severity"] for item in items}
        self.assertEqual(severities, {"disrupted", "impacted", "degraded"})
        self.assertNotIn("unknown", severities)

    def test_publishes_are_timezone_aware(self):
        items = parse_snapshot_text(fixture_text())
        for item in items:
            self.assertIsNotNone(item["published"].tzinfo)


class TestRebuild(unittest.TestCase):
    def test_grouping_by_incident_key(self):
        incidents = build_incidents_from_snapshots([fixture_text()])
        keys = sorted(incident["key"].rsplit("#", 1)[-1] for incident in incidents)
        self.assertEqual(
            keys,
            ["multipleservices-me-central-1", "multipleservices-me-south-1"],
        )
        self.assertEqual(incidents[0]["update_count"], 23)
        self.assertEqual(incidents[1]["update_count"], 13)

    def test_same_snapshot_twice_does_not_duplicate(self):
        incidents = build_incidents_from_snapshots([fixture_text(), fixture_text()])
        total_updates = sum(incident["update_count"] for incident in incidents)
        self.assertEqual(total_updates, 36)


if __name__ == "__main__":
    unittest.main()
