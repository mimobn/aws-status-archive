#!/usr/bin/env python3
"""Tests for feed shape (schema drift) checks."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from check_feed_shape import check_shape  # noqa: E402


def feed(body=""):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel><title>t</title><link>l</link>'
        + body
        + "</channel></rss>"
    )


def item(title="Service impact: EC2", guid="g1", pub="Mon, 01 Mar 2026 10:00:00 PST",
         desc="d"):
    return (
        "<item><title>%s</title><guid>%s</guid><pubDate>%s</pubDate>"
        "<description>%s</description></item>" % (title, guid, pub, desc)
    )


class TestCheckShape(unittest.TestCase):
    def test_empty_feed_is_fine(self):
        self.assertEqual(check_shape(feed()), [])

    def test_valid_item_passes(self):
        self.assertEqual(check_shape(feed(item())), [])

    def test_stray_text_before_root_still_parses(self):
        # AWS sometimes leaves whitespace/BOM before the root tag
        self.assertEqual(check_shape("\ufeff" + feed(item())), [])

    def test_bad_root_fails(self):
        errors = check_shape("<html></html>")
        self.assertTrue(any("root tag" in e for e in errors))

    def test_bad_version_fails(self):
        errors = check_shape('<rss version="3.0"><channel></channel></rss>')
        self.assertTrue(any("version" in e for e in errors))

    def test_missing_field_fails(self):
        bad = feed("<item><title>Service impact: EC2</title></item>")
        errors = check_shape(bad)
        self.assertTrue(any("<guid>" in e for e in errors))

    def test_unknown_severity_prefix_fails(self):
        bad = feed(item(title="Health check: all good"))
        errors = check_shape(bad)
        self.assertTrue(any("severity prefix" in e for e in errors))

    def test_not_xml_fails(self):
        errors = check_shape("totally not xml")
        self.assertTrue(any("XML" in e for e in errors))


if __name__ == "__main__":
    unittest.main()