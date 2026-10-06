#!/usr/bin/env python3
"""Tests for scripts/serve.py."""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Add scripts directory to path so we can import serve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from serve import resolve_path, needs_rebuild


class TestResolvePath(unittest.TestCase):
    """Tests for resolve_path function."""

    def setUp(self):
        """Create temporary directories for testing."""
        self.site_dir = tempfile.mkdtemp()
        self.out_dir = tempfile.mkdtemp()

        # Create test files
        Path(self.site_dir, "index.html").write_text("<html>index</html>")
        Path(self.site_dir, "app.js").write_text("// app")
        Path(self.site_dir, "styles.css").write_text("/* styles */")
        Path(self.out_dir, "incidents.json").write_text("{}")
        Path(self.out_dir, "metadata.json").write_text("{}")

    def tearDown(self):
        """Clean up temporary directories."""
        import shutil
        shutil.rmtree(self.site_dir, ignore_errors=True)
        shutil.rmtree(self.out_dir, ignore_errors=True)

    def test_root_path_serves_index(self):
        """Root path / should serve site/index.html."""
        result = resolve_path("/", self.site_dir, self.out_dir)
        expected = os.path.join(self.site_dir, "index.html")
        self.assertEqual(result, expected)

    def test_empty_path_serves_index(self):
        """Empty path should serve site/index.html."""
        result = resolve_path("", self.site_dir, self.out_dir)
        expected = os.path.join(self.site_dir, "index.html")
        self.assertEqual(result, expected)

    def test_site_file_served(self):
        """Site files like /app.js should be served from site/."""
        result = resolve_path("/app.js", self.site_dir, self.out_dir)
        expected = os.path.join(self.site_dir, "app.js")
        self.assertEqual(result, expected)

    def test_site_css_file_served(self):
        """CSS files should be served from site/."""
        result = resolve_path("/styles.css", self.site_dir, self.out_dir)
        expected = os.path.join(self.site_dir, "styles.css")
        self.assertEqual(result, expected)

    def test_parsed_incidents_served(self):
        """Parsed incidents should be served from out/."""
        result = resolve_path("/parsed/incidents.json", self.site_dir, self.out_dir)
        expected = os.path.join(self.out_dir, "incidents.json")
        self.assertEqual(result, expected)

    def test_parsed_metadata_served(self):
        """Parsed metadata should be served from out/."""
        result = resolve_path("/parsed/metadata.json", self.site_dir, self.out_dir)
        expected = os.path.join(self.out_dir, "metadata.json")
        self.assertEqual(result, expected)

    def test_parsed_forbidden_file_rejected(self):
        """/parsed/status.db should be rejected (forbidden file)."""
        result = resolve_path("/parsed/status.db", self.site_dir, self.out_dir)
        self.assertIsNone(result)

    def test_path_traversal_from_site_rejected(self):
        """Path traversal like /../README.md should be rejected."""
        result = resolve_path("/../README.md", self.site_dir, self.out_dir)
        self.assertIsNone(result)

    def test_path_traversal_from_parsed_rejected(self):
        """Path traversal like /parsed/../../README.md should be rejected."""
        result = resolve_path("/parsed/../../README.md", self.site_dir, self.out_dir)
        self.assertIsNone(result)

    def test_nonexistent_site_file_returns_none(self):
        """Nonexistent site files should return None."""
        result = resolve_path("/nonexistent.js", self.site_dir, self.out_dir)
        self.assertIsNone(result)

    def test_nonexistent_parsed_file_returns_none(self):
        """Nonexistent files in /parsed/ should return None."""
        result = resolve_path("/parsed/nonexistent.json", self.site_dir, self.out_dir)
        self.assertIsNone(result)

    def test_directory_with_index_html(self):
        """Directories containing index.html should return the index.html path."""
        subdir = os.path.join(self.site_dir, "subdir")
        os.makedirs(subdir)
        Path(subdir, "index.html").write_text("<html>subdir</html>")

        result = resolve_path("/subdir", self.site_dir, self.out_dir)
        expected = os.path.join(subdir, "index.html")
        self.assertEqual(result, expected)

    def test_directory_without_index_html_returns_none(self):
        """Directories without index.html should return None."""
        subdir = os.path.join(self.site_dir, "empty_subdir")
        os.makedirs(subdir)

        result = resolve_path("/empty_subdir", self.site_dir, self.out_dir)
        self.assertIsNone(result)


class TestNeedsRebuild(unittest.TestCase):
    """Tests for needs_rebuild function."""

    def setUp(self):
        """Create temporary directories for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.out_dir = os.path.join(self.temp_dir, "out")
        self.data_dir = os.path.join(self.temp_dir, "data")
        self.archive_dir = os.path.join(self.data_dir, "archive")

        os.makedirs(self.out_dir)
        os.makedirs(self.archive_dir)

    def tearDown(self):
        """Clean up temporary directories."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_rebuild_needed_when_missing(self):
        """needs_rebuild should return True when incidents.json is missing."""
        # Create a data file so the check doesn't fail on missing data
        Path(self.data_dir, "services.json").write_text("{}")

        result = needs_rebuild(self.out_dir, self.data_dir)
        self.assertTrue(result)

    def test_no_rebuild_when_output_newer(self):
        """needs_rebuild should return False when incidents.json is newer than data files."""
        # Create data file first with an old timestamp
        data_file = Path(self.data_dir, "services.json")
        data_file.write_text("{}")
        old_time = time.time() - 100
        os.utime(str(data_file), (old_time, old_time))

        # Create incidents.json with current time (newer)
        output_file = Path(self.out_dir, "incidents.json")
        output_file.write_text("{}")

        result = needs_rebuild(self.out_dir, self.data_dir)
        self.assertFalse(result)

    def test_rebuild_needed_when_data_newer(self):
        """needs_rebuild should return True when data files are newer than incidents.json."""
        # Create incidents.json
        Path(self.out_dir, "incidents.json").write_text("{}")

        # Wait to ensure mtime difference
        time.sleep(0.01)

        # Create a newer data file
        Path(self.data_dir, "services.json").write_text("{}")

        result = needs_rebuild(self.out_dir, self.data_dir)
        self.assertTrue(result)

    def test_rebuild_needed_when_archive_data_newer(self):
        """needs_rebuild should return True when archived data is newer."""
        # Create incidents.json
        Path(self.out_dir, "incidents.json").write_text("{}")

        # Wait to ensure mtime difference
        time.sleep(0.01)

        # Create a newer archived data file
        Path(self.archive_dir, "historyevents.json").write_text("{}")

        result = needs_rebuild(self.out_dir, self.data_dir)
        self.assertTrue(result)

    def test_no_rebuild_with_multiple_data_files(self):
        """needs_rebuild should check all data files."""
        # Create multiple data files with old timestamps
        old_time = time.time() - 100
        for filename in ["services.json", "historyevents.json", "currentevents.json"]:
            filepath = Path(self.data_dir, filename)
            filepath.write_text("{}")
            os.utime(str(filepath), (old_time, old_time))

        # Create incidents.json with current time (newer)
        Path(self.out_dir, "incidents.json").write_text("{}")

        result = needs_rebuild(self.out_dir, self.data_dir)
        self.assertFalse(result)

    def test_rebuild_needed_with_one_newer_data_file(self):
        """needs_rebuild should return True if even one data file is newer."""
        # Create incidents.json
        Path(self.out_dir, "incidents.json").write_text("{}")

        # Wait to ensure mtime difference
        time.sleep(0.01)

        # Create multiple data files
        Path(self.data_dir, "services.json").write_text("{}")
        Path(self.data_dir, "historyevents.json").write_text("{}")

        # Wait again and create a newer file
        time.sleep(0.01)
        Path(self.data_dir, "currentevents.json").write_text("{}")

        result = needs_rebuild(self.out_dir, self.data_dir)
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
