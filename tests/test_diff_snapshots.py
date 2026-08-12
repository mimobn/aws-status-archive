#!/usr/bin/env python3
"""Tests for the snapshot diff logic."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from diff_snapshots import diff_incidents  # noqa: E402


def feed(*items):
    """Build a minimal RSS 2.0 string from (title, guid, pubdate, desc) tuples."""
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0"><channel><title>t</title><link>l</link>',
    ]
    for title, guid, pubdate, desc in items:
        parts.append(
            "<item><title>%s</title><guid>%s</guid>"
            "<pubDate>%s</pubDate><description>%s</description></item>"
            % (title, guid, pubdate, desc)
        )
    parts.append("</channel></rss>")
    return "".join(parts)


BASE = "https://status.aws.amazon.com/#"


class TestDiffIncidents(unittest.TestCase):
    def test_identical_snapshots_report_nothing(self):
        older = feed(
            ("Service impact: S3", BASE + "s3_1", "Mon, 01 Mar 2026 10:00:00 PST", "d"),
        )
        report = diff_incidents(older, older)
        self.assertEqual(report["new_incidents"], [])
        self.assertEqual(report["removed_incidents"], [])
        self.assertEqual(report["incidents_with_new_updates"], [])

    def test_new_incident_is_reported(self):
        before = feed(("Service impact: S3", BASE + "s3_2", "Mon, 01 Mar 2026 10:00:00 PST", "d"))
        after = feed(
            ("Service impact: S3", BASE + "s3_2", "Mon, 01 Mar 2026 10:00:00 PST", "d"),
            ("Service disruption: EC2", BASE + "ec2_3", "Tue, 02 Mar 2026 11:00:00 PST", "d"),
        )
        report = diff_incidents(before, after)
        self.assertEqual(len(report["new_incidents"]), 1)
        self.assertEqual(report["new_incidents"][0]["incident_key"], BASE + "ec2")

    def test_vanished_incident_is_reported(self):
        before = feed(("Service impact: S3", BASE + "s3_4", "Mon, 01 Mar 2026 10:00:00 PST", "d"))
        report = diff_incidents(before, feed())
        # empty current feed: every incident vanishes
        self.assertEqual(len(report["removed_incidents"]), 1)
        self.assertEqual(report["removed_incidents"][0]["incident_key"], BASE + "s3")

    def test_new_update_on_existing_incident(self):
        before = feed(("Service impact: EC2", BASE + "ec2_5", "Mon, 01 Mar 2026 10:00:00 PST", "d"))
        after = feed(
            ("Service impact: EC2", BASE + "ec2_5", "Mon, 01 Mar 2026 10:00:00 PST", "d"),
            ("Service disruption: EC2", BASE + "ec2_6", "Mon, 01 Mar 2026 11:00:00 PST", "d"),
        )
        report = diff_incidents(before, after)
        self.assertEqual(report["new_incidents"], [])
        self.assertEqual(len(report["incidents_with_new_updates"]), 1)
        entry = report["incidents_with_new_updates"][0]
        self.assertEqual(entry["incident_key"], BASE + "ec2")
        self.assertEqual(entry["new_updates"], 1)
        self.assertEqual(entry["latest_severity"], "disrupted")


if __name__ == "__main__":
    unittest.main()