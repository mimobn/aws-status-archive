#!/usr/bin/env python3
"""Tests for archive shape (schema drift) checks."""

import json
import os
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


SERVICE = {
    "event_type_code": "AWS_EC2_OPERATIONAL_ISSUE",
    "launch_date": 1661731200,
    "locale": ["US"],
    "region_id": "us-east-1",
    "region_name": "N. Virginia",
    "service": "ec2-us-east-1",
    "service_name": "Amazon Elastic Compute Cloud",
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
    def test_valid_archive_passes(self):
        self.assertEqual(check_shape(good_dir()), [])

    def test_missing_file_fails(self):
        directory = write_dir({})
        errors = check_shape(directory)
        self.assertEqual(len(errors), 3)

    def test_history_entry_missing_field_fails(self):
        bad = dict(EVENT)
        del bad["summary"]
        directory = write_dir(
            {
                "services.json": [SERVICE],
                "historyevents.json": {"ec2-us-east-1": [bad]},
                "currentevents.json": [CURRENT],
            }
        )
        errors = check_shape(directory)
        self.assertTrue(any("'summary'" in e for e in errors))

    def test_current_event_missing_field_fails(self):
        bad = dict(CURRENT)
        del bad["impacted_services"]
        directory = write_dir(
            {
                "services.json": [SERVICE],
                "historyevents.json": {"ec2-us-east-1": [EVENT]},
                "currentevents.json": [bad],
            }
        )
        errors = check_shape(directory)
        self.assertTrue(any("missing 'impacted_services'" in e for e in errors))

    def test_not_json_fails(self):
        directory = write_dir(
            {
                "services.json": "totally not json",
                "historyevents.json": "nope",
                "currentevents.json": "nope",
            }
        )
        errors = check_shape(directory)
        self.assertTrue(any("not valid JSON" in e for e in errors))

    def test_empty_history_is_fine(self):
        directory = write_dir(
            {
                "services.json": [SERVICE],
                "historyevents.json": {},
                "currentevents.json": [CURRENT],
            }
        )
        self.assertEqual(check_shape(directory), [])


if __name__ == "__main__":
    unittest.main()