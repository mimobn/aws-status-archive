#!/usr/bin/env python3
"""Comprehensive tests for the read-only status API."""

import contextlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Add repo root to path so we can import api.main
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
import api.main


class TestAPIWithTempDatabase(unittest.TestCase):
    """Test API endpoints with a temporary SQLite database."""

    @classmethod
    def setUpClass(cls):
        """Create a temporary database with test schema and data."""
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.temp_dir.name, "test.db")
        cls._build_test_database()

    @classmethod
    def tearDownClass(cls):
        """Clean up temporary database."""
        cls.temp_dir.cleanup()

    @classmethod
    def _build_test_database(cls):
        """Build a test database with the new schema including arn and open columns."""
        conn = sqlite3.connect(cls.db_path)
        try:
            # Create schema with new columns
            conn.executescript("""
                DROP TABLE IF EXISTS services;
                DROP TABLE IF EXISTS updates;
                DROP TABLE IF EXISTS incidents;
                DROP TABLE IF EXISTS metadata;

                CREATE TABLE updates (
                    guid TEXT PRIMARY KEY,
                    incident_key TEXT NOT NULL,
                    published TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL
                );

                CREATE TABLE incidents (
                    incident_key TEXT PRIMARY KEY,
                    started_at TEXT,
                    last_update TEXT,
                    update_count INTEGER,
                    title TEXT,
                    region TEXT,
                    region_name TEXT,
                    service TEXT,
                    service_name TEXT,
                    arn TEXT,
                    open INTEGER
                );

                CREATE TABLE services (
                    incident_key TEXT NOT NULL,
                    service_slug TEXT NOT NULL,
                    service_name TEXT,
                    severity TEXT,
                    max_severity TEXT,
                    PRIMARY KEY (incident_key, service_slug)
                );

                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)

            # Insert test data
            conn.execute(
                "INSERT INTO incidents "
                "(incident_key, started_at, last_update, update_count, title, "
                " region, region_name, service, service_name, arn, open) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "https://status.aws.amazon.com/#ec2-us-east-1_1772369485",
                    "2026-08-01T10:00:00Z",
                    "2026-08-01T12:00:00Z",
                    3,
                    "EC2 Connectivity Issues",
                    "us-east-1",
                    "US East (N. Virginia)",
                    "ec2",
                    "EC2",
                    "arn:aws:ec2:us-east-1::instance/i-1234",
                    1,
                ),
            )
            conn.execute(
                "INSERT INTO incidents "
                "(incident_key, started_at, last_update, update_count, title, "
                " region, region_name, service, service_name, arn, open) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "https://status.aws.amazon.com/#s3-global_1772369486",
                    "2026-07-15T08:00:00Z",
                    "2026-07-15T09:30:00Z",
                    2,
                    "S3 Latency",
                    "global",
                    "Global Services",
                    "s3",
                    "S3",
                    "arn:aws:s3:::bucket",
                    0,
                ),
            )

            conn.execute(
                "INSERT INTO updates "
                "(guid, incident_key, published, severity, title, description) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "https://status.aws.amazon.com/#ec2-us-east-1_1772369485_1",
                    "https://status.aws.amazon.com/#ec2-us-east-1_1772369485",
                    "2026-08-01T10:15:00Z",
                    "2",
                    "Issue Identified",
                    "We are investigating increased API latency",
                ),
            )
            conn.execute(
                "INSERT INTO updates "
                "(guid, incident_key, published, severity, title, description) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "https://status.aws.amazon.com/#ec2-us-east-1_1772369485_2",
                    "https://status.aws.amazon.com/#ec2-us-east-1_1772369485",
                    "2026-08-01T11:00:00Z",
                    "1",
                    "Update Provided",
                    "Mitigation in progress",
                ),
            )

            conn.execute(
                "INSERT INTO services "
                "(incident_key, service_slug, service_name, severity, max_severity) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "https://status.aws.amazon.com/#ec2-us-east-1_1772369485",
                    "ec2",
                    "EC2",
                    "1",
                    "2",
                ),
            )

            # Insert metadata with JSON values
            conn.execute(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                ("archive_earliest_date", json.dumps("2026-01-01")),
            )
            conn.execute(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                ("archive_latest_date", json.dumps("2026-08-01")),
            )
            conn.execute(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                ("rebuilt_at", json.dumps("2026-09-29T12:00:00Z")),
            )
            conn.execute(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                ("total_incidents", json.dumps(2)),
            )
            conn.execute(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                ("null_value", json.dumps(None)),
            )

            conn.commit()
        finally:
            conn.close()

    def setUp(self):
        """Set up test client with mocked DB path."""
        self.patcher = patch.object(
            api.main, "DB_PATH", self.db_path
        )
        self.patcher.start()
        self.client = TestClient(api.main.app)

    def tearDown(self):
        """Stop patching."""
        self.patcher.stop()

    def test_healthz_returns_typed_values(self):
        """Test /healthz returns properly typed metadata values."""
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["incidents"], 2)
        self.assertEqual(data["updates"], 2)
        self.assertEqual(data["services"], 1)
        # Metadata should be parsed: dates are strings, not integers
        self.assertEqual(data["archive_earliest_date"], "2026-01-01")
        self.assertEqual(data["archive_latest_date"], "2026-08-01")

    def test_metadata_returns_typed_values(self):
        """Test /metadata returns properly typed values (int as int, null as null, string as string)."""
        response = self.client.get("/metadata")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["archive_earliest_date"], "2026-01-01")
        self.assertEqual(data["total_incidents"], 2)  # Should be int, not string
        self.assertIsNone(data["null_value"])  # Should be null, not "null"

    def test_updates_limit_validation(self):
        """Test /updates limit parameter validation."""
        # Valid limit
        response = self.client.get("/updates?limit=10")
        self.assertEqual(response.status_code, 200)

        # Limit too small
        response = self.client.get("/updates?limit=0")
        self.assertEqual(response.status_code, 422)  # Validation error

        # Limit negative
        response = self.client.get("/updates?limit=-1")
        self.assertEqual(response.status_code, 422)

        # Limit too large
        response = self.client.get("/updates?limit=1001")
        self.assertEqual(response.status_code, 422)

        # Limit at boundary
        response = self.client.get("/updates?limit=1000")
        self.assertEqual(response.status_code, 200)

    def test_incidents_short_key_lookup(self):
        """Test /incidents/{key} accepts short keys like 'ec2-us-east-1_1772369485'."""
        # Short key should match
        response = self.client.get("/incidents/ec2-us-east-1_1772369485")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("ec2-us-east-1_1772369485", data["incident_key"])
        self.assertEqual(data["title"], "EC2 Connectivity Issues")

    def test_incidents_full_key_lookup(self):
        """Test /incidents/{key} with full URL-encoded key."""
        # Full key
        full_key = "https://status.aws.amazon.com/%23ec2-us-east-1_1772369485"
        response = self.client.get(f"/incidents/{full_key}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("ec2-us-east-1_1772369485", data["incident_key"])

    def test_incidents_open_filter(self):
        """Test /incidents?open=true filter."""
        # Get only open incidents
        response = self.client.get("/incidents?open=true")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "EC2 Connectivity Issues")
        self.assertTrue(data[0]["open"])

        # Get closed incidents
        response = self.client.get("/incidents?open=false")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "S3 Latency")
        self.assertFalse(data[0]["open"])

    def test_incidents_region_global_filter(self):
        """Test /incidents?region=global works."""
        response = self.client.get("/incidents?region=global")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "S3 Latency")
        self.assertEqual(data[0]["region"], "global")

    def test_incidents_arn_and_open_exposed(self):
        """Test that arn and open columns are exposed in incident payloads."""
        response = self.client.get("/incidents/ec2-us-east-1_1772369485")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("arn", data)
        self.assertIn("open", data)
        self.assertEqual(data["arn"], "arn:aws:ec2:us-east-1::instance/i-1234")
        self.assertTrue(data["open"])

    def test_incidents_404_not_found(self):
        """Test /incidents/{key} returns 404 for missing incident."""
        response = self.client.get("/incidents/nonexistent-key")
        self.assertEqual(response.status_code, 404)

    def test_connection_closing(self):
        """Test that connections are properly closed after requests."""
        # Make multiple requests to verify connections are closed
        for _ in range(5):
            response = self.client.get("/healthz")
            self.assertEqual(response.status_code, 200)
        # If connections weren't closed, we'd likely run out of resources

    def test_regions_endpoint(self):
        """Test /regions returns data without error."""
        response = self.client.get("/regions")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreater(len(data), 0)
        # Should have both us-east-1 and global
        regions = {r["region"] for r in data}
        self.assertIn("us-east-1", regions)
        self.assertIn("global", regions)

    def test_updates_endpoint(self):
        """Test /updates returns data in correct order."""
        response = self.client.get("/updates")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        # Should be in descending published order (most recent first)
        self.assertTrue(data[0]["published"] >= data[1]["published"])

    def test_metrics_endpoint(self):
        """Test /metrics returns typed values."""
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["incidents"], 2)
        self.assertEqual(data["updates"], 2)
        self.assertEqual(data["services"], 1)
        # Metadata should be typed
        self.assertEqual(data["archive_earliest_date"], "2026-01-01")
        self.assertEqual(data["archive_latest_date"], "2026-08-01")

    def test_incident_detail_includes_updates_and_services(self):
        """Test /incidents/{key} includes updates and services."""
        response = self.client.get("/incidents/ec2-us-east-1_1772369485")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("updates", data)
        self.assertIn("services", data)
        self.assertEqual(len(data["updates"]), 2)
        self.assertEqual(len(data["services"]), 1)


class TestAPIMissingDatabase(unittest.TestCase):
    """Test API behavior when database is missing."""

    def setUp(self):
        """Set up with non-existent database path."""
        self.patcher = patch.object(
            api.main, "DB_PATH", "/nonexistent/path/to/db.sqlite"
        )
        self.patcher.start()
        self.client = TestClient(api.main.app)

    def tearDown(self):
        """Stop patching."""
        self.patcher.stop()

    def test_missing_database_returns_503(self):
        """Test that missing database returns 503 Service Unavailable."""
        endpoints = [
            "/healthz",
            "/incidents",
            "/regions",
            "/updates",
            "/metrics",
            "/metadata",
        ]
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                response = self.client.get(endpoint)
                self.assertEqual(
                    response.status_code,
                    503,
                    f"Expected 503 for {endpoint}, got {response.status_code}",
                )
                data = response.json()
                self.assertIn("detail", data)


if __name__ == "__main__":
    unittest.main()
