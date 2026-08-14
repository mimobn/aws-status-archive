#!/usr/bin/env python3
"""Tests for the snapshot diff logic."""

import sys
import unittest

sys.path.insert(0, "scripts")

from diff_snapshots import diff_incidents  # noqa: E402


def state(*pairs):
    """Build an archive state dict from (key, updates, title) tuples."""
    result = {}
    for key, updates, title in pairs:
        result[key] = {"updates": updates, "title": title}
    return result


BASE = "https://status.aws.amazon.com/#"


class TestDiffIncidents(unittest.TestCase):
    def test_identical_snapshots_report_nothing(self):
        older = state((BASE + "s3_1", 3, "S3"))
        report = diff_incidents(older, dict(older))
        self.assertEqual(report["new_incidents"], [])
        self.assertEqual(report["removed_incidents"], [])
        self.assertEqual(report["incidents_with_new_updates"], [])

    def test_new_incident_is_reported(self):
        before = state((BASE + "s3_1", 2, "S3"))
        after = state(
            (BASE + "s3_1", 2, "S3"),
            (BASE + "ec2_2", 4, "EC2"),
        )
        report = diff_incidents(before, after)
        self.assertEqual(len(report["new_incidents"]), 1)
        self.assertEqual(report["new_incidents"][0]["incident_key"], BASE + "ec2_2")

    def test_vanished_incident_is_reported(self):
        before = state((BASE + "s3_1", 3, "S3"))
        report = diff_incidents(before, state())
        self.assertEqual(len(report["removed_incidents"]), 1)
        self.assertEqual(report["removed_incidents"][0]["incident_key"], BASE + "s3_1")

    def test_new_update_on_existing_incident(self):
        before = state((BASE + "ec2_1", 2, "EC2"))
        after = state((BASE + "ec2_1", 5, "EC2"))
        report = diff_incidents(before, after)
        self.assertEqual(report["new_incidents"], [])
        self.assertEqual(len(report["incidents_with_new_updates"]), 1)
        entry = report["incidents_with_new_updates"][0]
        self.assertEqual(entry["incident_key"], BASE + "ec2_1")
        self.assertEqual(entry["new_updates"], 3)


if __name__ == "__main__":
    unittest.main()