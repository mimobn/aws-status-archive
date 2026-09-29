#!/usr/bin/env python3
"""Tests for merge_archive.py"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from merge_archive import (
    merge_all,
    merge_currentevents,
    merge_historyevents,
    merge_services,
)


class TestMergeHistoryevents(unittest.TestCase):
    """Tests for historyevents merging."""

    def test_empty_merge(self):
        """Test merging empty data."""
        archived = {}
        new = {}
        result = merge_historyevents(archived, new)
        self.assertEqual(result, {})

    def test_new_slug_added(self):
        """Test that new slugs are added."""
        archived = {}
        new = {
            "service-us-east-1": [
                {
                    "arn": "arn:1",
                    "date": "100",
                    "event_log": [{"timestamp": 100, "status": "1", "summary": "Issue"}],
                    "status": "1",
                    "summary": "Issue",
                }
            ]
        }
        result = merge_historyevents(archived, new)
        self.assertEqual(len(result), 1)
        self.assertIn("service-us-east-1", result)
        self.assertEqual(len(result["service-us-east-1"]), 1)

    def test_union_keeps_aged_out_events(self):
        """Test that union keeps events from archived data that are not in new data."""
        archived = {
            "service-us-east-1": [
                {
                    "arn": "arn:aged",
                    "date": "100",
                    "event_log": [{"timestamp": 100, "status": "1", "summary": "Old issue"}],
                    "status": "0",
                    "summary": "[RESOLVED] Old issue",
                }
            ]
        }
        new = {
            "service-us-east-1": [
                {
                    "arn": "arn:new",
                    "date": "200",
                    "event_log": [{"timestamp": 200, "status": "1", "summary": "New issue"}],
                    "status": "1",
                    "summary": "New issue",
                }
            ]
        }
        result = merge_historyevents(archived, new)
        self.assertEqual(len(result["service-us-east-1"]), 2)

    def test_newer_version_wins(self):
        """Test that newer version replaces older fields."""
        archived = {
            "service-us-east-1": [
                {
                    "arn": "arn:1",
                    "date": "100",
                    "event_log": [{"timestamp": 100, "status": "1", "summary": "Issue"}],
                    "status": "1",
                    "summary": "Issue",
                }
            ]
        }
        new = {
            "service-us-east-1": [
                {
                    "arn": "arn:1",
                    "date": "100",
                    "event_log": [{"timestamp": 100, "status": "1", "summary": "Issue"}],
                    "status": "0",
                    "summary": "[RESOLVED] Issue",
                }
            ]
        }
        result = merge_historyevents(archived, new)
        self.assertEqual(len(result["service-us-east-1"]), 1)
        event = result["service-us-east-1"][0]
        self.assertEqual(event["status"], "0")
        self.assertEqual(event["summary"], "[RESOLVED] Issue")

    def test_event_log_union(self):
        """Test that event_log entries are unioned by (timestamp, status, message)."""
        archived = {
            "service-us-east-1": [
                {
                    "arn": "arn:1",
                    "date": "100",
                    "event_log": [
                        {"timestamp": 100, "status": "1", "summary": "Issue", "message": "msg1"},
                        {"timestamp": 200, "status": "1", "summary": "Update", "message": "msg2"},
                    ],
                    "status": "1",
                    "summary": "Issue",
                }
            ]
        }
        new = {
            "service-us-east-1": [
                {
                    "arn": "arn:1",
                    "date": "100",
                    "event_log": [
                        {"timestamp": 100, "status": "1", "summary": "Issue", "message": "msg1"},
                        {"timestamp": 300, "status": "0", "summary": "Resolved", "message": "msg3"},
                    ],
                    "status": "0",
                    "summary": "[RESOLVED] Issue",
                }
            ]
        }
        result = merge_historyevents(archived, new)
        event = result["service-us-east-1"][0]
        # Should have 3 unique entries
        self.assertEqual(len(event["event_log"]), 3)
        # Should be sorted by timestamp
        timestamps = [entry["timestamp"] for entry in event["event_log"]]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_events_sorted_by_date(self):
        """Test that events are sorted by date."""
        archived = {
            "service-us-east-1": [
                {
                    "arn": "arn:2",
                    "date": "200",
                    "event_log": [],
                    "status": "0",
                    "summary": "Event 2",
                },
                {
                    "arn": "arn:1",
                    "date": "100",
                    "event_log": [],
                    "status": "0",
                    "summary": "Event 1",
                },
            ]
        }
        new = {}
        result = merge_historyevents(archived, new)
        dates = [int(event["date"]) for event in result["service-us-east-1"]]
        self.assertEqual(dates, sorted(dates))

    def test_empty_slugs_removed(self):
        """Test that slugs with empty event lists are removed."""
        # When both archived and new have no events for a slug, it should be removed
        archived = {"service-us-east-1": []}
        new = {}
        result = merge_historyevents(archived, new)
        self.assertNotIn("service-us-east-1", result)


class TestMergeCurrentevents(unittest.TestCase):
    """Tests for currentevents merging."""

    def test_dedupe_by_arn(self):
        """Test that currentevents are deduped by arn."""
        archived = [
            {"arn": "arn:1", "date": "100", "service": "service1", "status": "1"},
            {"arn": "arn:2", "date": "100", "service": "service2", "status": "0"},
        ]
        new = [
            {"arn": "arn:1", "date": "200", "service": "service1", "status": "0"},  # Update
        ]
        result = merge_currentevents(archived, new)
        # Should have 2 items, not 3
        self.assertEqual(len(result), 2)
        # arn:1 should have latest date
        arn1_event = [e for e in result if e["arn"] == "arn:1"][0]
        self.assertEqual(arn1_event["date"], "200")

    def test_last_seen_wins(self):
        """Test that last-seen wins for same arn."""
        archived = [{"arn": "arn:1", "date": "100", "status": "1", "summary": "Old"}]
        new = [{"arn": "arn:1", "date": "100", "status": "0", "summary": "New"}]
        result = merge_currentevents(archived, new)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["summary"], "New")

    def test_sorted_by_date_then_arn(self):
        """Test that results are sorted by (date, arn)."""
        archived = []
        new = [
            {"arn": "arn:z", "date": "100", "status": "1"},
            {"arn": "arn:a", "date": "100", "status": "1"},
            {"arn": "arn:b", "date": "50", "status": "1"},
        ]
        result = merge_currentevents(archived, new)
        # Extract (date, arn) tuples
        sort_keys = [(int(e["date"]), e["arn"]) for e in result]
        self.assertEqual(sort_keys, sorted(sort_keys))


class TestMergeServices(unittest.TestCase):
    """Tests for services merging."""

    def test_union_by_service(self):
        """Test that services are unioned by 'service' field."""
        archived = [
            {"service": "service1", "service_name": "Service One", "region_id": "us-east-1"},
            {"service": "service2", "service_name": "Service Two", "region_id": "us-east-1"},
        ]
        new = [
            {"service": "service1", "service_name": "Service One", "region_id": "eu-west-1"},
            {"service": "service3", "service_name": "Service Three", "region_id": "us-east-1"},
        ]
        result = merge_services(archived, new)
        # Should have 3 services
        self.assertEqual(len(result), 3)

    def test_last_seen_wins_for_service(self):
        """Test that last-seen wins for same service."""
        archived = [{"service": "service1", "service_name": "Old Name"}]
        new = [{"service": "service1", "service_name": "New Name"}]
        result = merge_services(archived, new)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["service_name"], "New Name")

    def test_sorted_by_service(self):
        """Test that services are sorted by 'service' field."""
        archived = []
        new = [
            {"service": "zebra-service"},
            {"service": "alpha-service"},
            {"service": "beta-service"},
        ]
        result = merge_services(archived, new)
        services = [s["service"] for s in result]
        self.assertEqual(services, sorted(services))


class TestMergeAllIntegration(unittest.TestCase):
    """Integration tests for merge_all()."""

    def test_idempotence(self):
        """Test that running merge twice writes nothing the second time."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            data_dir = tmpdir / "data"
            archive_dir = tmpdir / "archive"
            data_dir.mkdir()
            archive_dir.mkdir()

            # Create initial data
            data_file = data_dir / "historyevents.json"
            data_file.write_text(
                json.dumps(
                    {
                        "service-us-east-1": [
                            {
                                "arn": "arn:1",
                                "date": "100",
                                "event_log": [{"timestamp": 100, "status": "1", "summary": "Issue"}],
                                "status": "1",
                                "summary": "Issue",
                            }
                        ]
                    }
                )
            )

            # First merge
            changes1 = merge_all(data_dir, archive_dir)
            self.assertIn("historyevents.json", changes1)

            # Second merge - should be idempotent
            changes2 = merge_all(data_dir, archive_dir)
            self.assertNotIn("historyevents.json", changes2)

    def test_bad_input_does_not_wipe_archive(self):
        """Test that bad input doesn't delete archived data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            data_dir = tmpdir / "data"
            archive_dir = tmpdir / "archive"
            data_dir.mkdir()
            archive_dir.mkdir()

            # Create archive data
            archive_file = archive_dir / "historyevents.json"
            archive_file.write_text(
                json.dumps(
                    {
                        "service-us-east-1": [
                            {
                                "arn": "arn:1",
                                "date": "100",
                                "event_log": [{"timestamp": 100, "status": "1", "summary": "Issue"}],
                                "status": "1",
                                "summary": "Issue",
                            }
                        ]
                    }
                )
            )

            # Create bad data file
            data_file = data_dir / "historyevents.json"
            data_file.write_text("not valid json")

            # Merge (should skip bad file with warning)
            merge_all(data_dir, archive_dir)

            # Archive should still have the data
            archive_data = json.loads(archive_file.read_text())
            self.assertIn("service-us-east-1", archive_data)
            self.assertEqual(len(archive_data["service-us-east-1"]), 1)

    def test_missing_files_skipped(self):
        """Test that missing input files are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            data_dir = tmpdir / "data"
            archive_dir = tmpdir / "archive"
            data_dir.mkdir()
            archive_dir.mkdir()

            # Only create one file
            (data_dir / "historyevents.json").write_text("{}")

            # Merge should complete without error
            merge_all(data_dir, archive_dir)

            # Archive should only have historyevents
            self.assertTrue((archive_dir / "historyevents.json").exists())

    def test_currentevents_all_files(self):
        """Test merging of all three file types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            data_dir = tmpdir / "data"
            archive_dir = tmpdir / "archive"
            data_dir.mkdir()
            archive_dir.mkdir()

            # Create all three files
            (data_dir / "historyevents.json").write_text(
                json.dumps({"service-us-east-1": [{"arn": "arn:1", "date": "100", "event_log": []}]})
            )
            (data_dir / "currentevents.json").write_text(
                json.dumps([{"arn": "arn:2", "date": "200", "service": "service1"}])
            )
            (data_dir / "services.json").write_text(
                json.dumps([{"service": "service1", "service_name": "Service One"}])
            )

            # Merge
            changes = merge_all(data_dir, archive_dir)

            # All files should be in archive
            self.assertTrue((archive_dir / "historyevents.json").exists())
            self.assertTrue((archive_dir / "currentevents.json").exists())
            self.assertTrue((archive_dir / "services.json").exists())

            # All should be marked as changed (first time)
            self.assertEqual(len(changes), 3)


if __name__ == "__main__":
    unittest.main()
