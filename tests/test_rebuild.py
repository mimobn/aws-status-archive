#!/usr/bin/env python3
"""Tests for the JSON archive parser and the incident rebuild."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from parse_status import (  # noqa: E402
    clean_title,
    event_log_updates,
    extract_region,
    iso,
    severity,
    service_days,
    worst_transition_severity,
)
from rebuild import build_incidents, parse_current_text, parse_history_text, parse_services_text  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


def load_fixtures():
    catalog, _ = parse_services_text(fixture("services.json"))
    history = parse_history_text(fixture("historyevents.json"))
    current = parse_current_text(fixture("currentevents.json"))
    return catalog, history, current


class TestParseStatus(unittest.TestCase):
    def test_severity_mapping(self):
        self.assertEqual(severity("0"), "operational")
        self.assertEqual(severity("1"), "impacted")
        self.assertEqual(severity("2"), "degraded")
        self.assertEqual(severity("3"), "disrupted")

    def test_clean_title_strips_resolved_prefix(self):
        self.assertEqual(clean_title("[RESOLVED] Fable 5"), "Fable 5")
        self.assertEqual(clean_title("Increased Error Rates"), "Increased Error Rates")

    def test_iso_handles_seconds_and_millis(self):
        self.assertEqual(iso(1772369485), "2026-03-01T12:51:25+00:00")
        self.assertEqual(iso(1772369485000), "2026-03-01T12:51:25+00:00")

    def test_extract_region_from_slug(self):
        catalog = {}
        self.assertEqual(extract_region("ec2-me-central-1", catalog), "me-central-1")
        self.assertEqual(extract_region("s3-us-gov-east-1", catalog), "us-gov-east-1")

    def test_extract_region_falls_back_to_catalog(self):
        catalog = {"cloudfront": {"region_id": "us-east-1"}}
        self.assertEqual(extract_region("cloudfront", catalog), "us-east-1")

    def test_event_log_updates_are_sorted_and_cleaned(self):
        events = {"multipleservices-me-central-1": [{"summary": "Increased Error Rates", "event_log": [
            {"timestamp": 1772404099, "status": "3", "summary": "Increased Error Rates", "message": "later"},
            {"timestamp": 1772369485, "status": "1", "summary": "[IN PROGRESS] Increased Error Rates", "message": "first"},
        ]}]}
        catalog = {}
        incident = build_incidents(catalog, events, [])[0]
        self.assertEqual(incident["update_count"], 2)
        self.assertEqual(incident["updates"][0]["published"], "2026-03-01T12:51:25+00:00")
        self.assertEqual(incident["updates"][0]["title"], "Increased Error Rates")
        self.assertEqual(incident["updates"][1]["severity"], "disrupted")

    def test_service_days_starts_operational(self):
        transitions = [{"timestamp": 1772369485000, "current_status": "3"}]
        days = service_days(transitions, "2026-02-28", "2026-03-02")
        self.assertEqual(days["2026-02-28"], "operational")
        self.assertEqual(days["2026-03-01"], "disrupted")
        self.assertEqual(days["2026-03-02"], "disrupted")

    def test_worst_transition_severity(self):
        transitions = [
            {"current_status": "1"},
            {"current_status": "3"},
            {"current_status": "0"},
        ]
        self.assertEqual(worst_transition_severity(transitions), "disrupted")


class TestRebuild(unittest.TestCase):
    def test_builds_all_events(self):
        catalog, history, current = load_fixtures()
        incidents = build_incidents(catalog, history, current)
        self.assertEqual(len(incidents), 2)

    def test_region_incidents_get_per_service_breakdown(self):
        catalog, history, current = load_fixtures()
        incidents = build_incidents(catalog, history, current)
        me = [i for i in incidents if i["region"] == "me-central-1"][0]
        self.assertEqual(me["region_name"], "Middle East (UAE)")
        self.assertEqual(me["update_count"], 2)
        services = me["services"]
        self.assertEqual(services["ec2-me-central-1"]["current"], "disrupted")
        self.assertEqual(services["cloudfront"]["current"], "operational")
        self.assertEqual(len(services["cloudfront"]["transitions"]), 2)

    def test_non_current_event_has_no_services(self):
        catalog, history, current = load_fixtures()
        incidents = build_incidents(catalog, history, current)
        me_south = [i for i in incidents if i["region"] == "me-south-1"][0]
        self.assertNotIn("services", me_south)
        self.assertEqual(me_south["update_count"], 1)


if __name__ == "__main__":
    unittest.main()