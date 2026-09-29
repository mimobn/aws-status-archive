#!/usr/bin/env python3
"""Tests for archive shape (schema drift) checks."""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from check_feed_shape import check_shape  # noqa: E402


def write_dir(files):
    """Write {filename: value} into a temp dir and return its path."""
    directory = tempfile.mkdtemp()
    for filename, value in files.items():
        with open(os.path.join(directory, filename), "w", encoding="utf-8") as handle:
            if isinstance(value, str):
                handle.write(value)
            else:
                json.dump(value, handle)
    return directory


def cleanup_dir(directory):
    """Clean up a temp directory."""
    if os.path.exists(directory):
        shutil.rmtree(directory)


SERVICE = {
    "event_type_code": "AWS_EC2_OPERATIONAL_ISSUE",
    "launch_date": 1661731200,
    "locale": ["US"],
    "region_id": "us-east-1",
    "region_name": "N. Virginia",
    "service": "ec2-us-east-1",
    "service_name": "Amazon Elastic Compute Cloud",
}

# Global service row without region_id/region_name
GLOBAL_SERVICE = {
    "event_type_code": "AWS_MULTIPLE_SERVICES_OPERATIONAL_ISSUE",
    "launch_date": 1661731200,
    "locale": ["GLOBAL"],
    "service": "multipleservices",
    "service_name": "Multiple services",
}

EVENT = {
    "arn": "arn:aws:health:us-east-1::event/E/A/E_1",
    "date": "1772369485",
    "status": "1",
    "summary": "Increased Error Rates",
    "event_log": [
        {"timestamp": 1772369485, "status": "1", "summary": "Increased Error Rates",
         "message": "investigating"}
    ],
}

CURRENT = {
    "date": "1772369485",
    "arn": "arn:aws:health:me-central-1::event/MULTIPLE_SERVICES/AWS_MULTIPLE_SERVICES_OPERATIONAL_ISSUE/AWS_MULTIPLE_SERVICES_OPERATIONAL_ISSUE_5E6B8_EF2498889B5",
    "region_name": "UAE",
    "service": "multipleservices-me-central-1",
    "service_name": "Multiple services",
    "status": "3",
    "summary": "Increased Error Rates",
    "event_log": [{"timestamp": 1772369485, "status": "3", "summary": "s", "message": "m"}],
    "impacted_services": {},
    "impacted_service_status_changes": [],
}


def good_dir():
    return write_dir(
        {
            "services.json": [SERVICE],
            "historyevents.json": {"ec2-us-east-1": [EVENT]},
            "currentevents.json": [CURRENT],
        }
    )


class TestCheckShape(unittest.TestCase):
    def setUp(self):
        self.directories_to_cleanup = []

    def tearDown(self):
        for directory in self.directories_to_cleanup:
            cleanup_dir(directory)

    def _track_dir(self, directory):
        """Track a directory for cleanup in tearDown."""
        self.directories_to_cleanup.append(directory)
        return directory

    def test_valid_archive_passes(self):
        directory = self._track_dir(good_dir())
        self.assertEqual(check_shape(directory), [])

    def test_missing_file_fails(self):
        directory = self._track_dir(write_dir({}))
        errors = check_shape(directory)
        self.assertEqual(len(errors), 3)

    def test_history_entry_missing_field_fails(self):
        bad = dict(EVENT)
        del bad["summary"]
        directory = self._track_dir(
            write_dir(
                {
                    "services.json": [SERVICE],
                    "historyevents.json": {"ec2-us-east-1": [bad]},
                    "currentevents.json": [CURRENT],
                }
            )
        )
        errors = check_shape(directory)
        self.assertTrue(any("'summary'" in e for e in errors))

    def test_current_event_missing_field_fails(self):
        bad = dict(CURRENT)
        del bad["impacted_services"]
        directory = self._track_dir(
            write_dir(
                {
                    "services.json": [SERVICE],
                    "historyevents.json": {"ec2-us-east-1": [EVENT]},
                    "currentevents.json": [bad],
                }
            )
        )
        errors = check_shape(directory)
        self.assertTrue(any("missing 'impacted_services'" in e for e in errors))

    def test_not_json_fails(self):
        directory = self._track_dir(
            write_dir(
                {
                    "services.json": "totally not json",
                    "historyevents.json": "nope",
                    "currentevents.json": "nope",
                }
            )
        )
        errors = check_shape(directory)
        self.assertTrue(any("not valid JSON" in e for e in errors))

    def test_empty_history_is_fine(self):
        directory = self._track_dir(
            write_dir(
                {
                    "services.json": [SERVICE],
                    "historyevents.json": {},
                    "currentevents.json": [CURRENT],
                }
            )
        )
        self.assertEqual(check_shape(directory), [])

    def test_global_service_without_region_id_passes(self):
        """Global services without region_id/region_name should be valid."""
        directory = self._track_dir(
            write_dir(
                {
                    "services.json": [GLOBAL_SERVICE],
                    "historyevents.json": {},
                    "currentevents.json": [CURRENT],
                }
            )
        )
        self.assertEqual(check_shape(directory), [])

    def test_empty_services_list_fails(self):
        """Empty services list should fail."""
        directory = self._track_dir(
            write_dir(
                {
                    "services.json": [],
                    "historyevents.json": {},
                    "currentevents.json": [CURRENT],
                }
            )
        )
        errors = check_shape(directory)
        self.assertTrue(any("empty list" in e for e in errors))

    def test_service_with_non_string_field_fails(self):
        """Service with non-string service_name should fail."""
        bad_service = dict(SERVICE)
        bad_service["service_name"] = 123  # Should be a string
        directory = self._track_dir(
            write_dir(
                {
                    "services.json": [bad_service],
                    "historyevents.json": {},
                    "currentevents.json": [CURRENT],
                }
            )
        )
        errors = check_shape(directory)
        self.assertTrue(any("not a string" in e for e in errors))

    def test_event_with_non_int_like_date_fails(self):
        """Event with non-int-like date should fail."""
        bad_event = dict(EVENT)
        bad_event["date"] = "not-a-number"  # Should be int-like
        directory = self._track_dir(
            write_dir(
                {
                    "services.json": [SERVICE],
                    "historyevents.json": {"ec2-us-east-1": [bad_event]},
                    "currentevents.json": [CURRENT],
                }
            )
        )
        errors = check_shape(directory)
        self.assertTrue(any("not int-like" in e for e in errors))

    def test_impacted_service_status_change_missing_field_fails(self):
        """impacted_service_status_changes entry missing required field should fail."""
        bad_current = dict(CURRENT)
        bad_current["impacted_service_status_changes"] = [
            {"timestamp": 1772369485, "service": "ec2"}  # Missing current_status
        ]
        directory = self._track_dir(
            write_dir(
                {
                    "services.json": [SERVICE],
                    "historyevents.json": {},
                    "currentevents.json": [bad_current],
                }
            )
        )
        errors = check_shape(directory)
        self.assertTrue(any("'current_status'" in e for e in errors))


if __name__ == "__main__":
    unittest.main()