#!/usr/bin/env python3
"""Check that a snapshot still matches the shape we know how to parse.

AWS warns the status feed "format is subject to change". If they ever
rework it, this is what notices first: instead of parsing garbage into
silently wrong incidents, we fail loudly and let a human look.

It checks the root element, the version, and that every item carries
the fields and title prefixes the pipeline depends on. An empty feed
is fine - that just means nothing is broken right now.

Usage: python scripts/check_feed_shape.py [--path data/aws-status.rss]
"""

import argparse
import sys
import xml.etree.ElementTree as ET

from parse_snapshot import SEVERITIES

EXPECTED_ITEM_FIELDS = ["title", "pubDate", "guid", "description"]


def check_shape(content):
    """Return a list of shape problems; empty list means it looks fine."""
    errors = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        return [f"not valid XML: {exc}"]

    if root.tag != "rss":
        errors.append(f"root tag is {root.tag!r}, expected 'rss'")
    version = root.get("version")
    if version not in (None, "2.0"):
        errors.append(f"rss version is {version!r}, expected 2.0")

    channel = root.find("channel")
    if channel is None:
        errors.append("no <channel> element")
        return errors

    items = channel.findall("item")
    for idx, item in enumerate(items):
        for field in EXPECTED_ITEM_FIELDS:
            if item.find(field) is None:
                errors.append(f"item {idx} is missing <{field}>")
        title = item.findtext("title") or ""
        if not any(title.startswith(prefix) for prefix in SEVERITIES):
            errors.append(f"item {idx} title has no known severity prefix: {title[:40]!r}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default="data/aws-status.rss")
    args = parser.parse_args()

    with open(args.path, "r", encoding="utf-8") as handle:
        content = handle.read()

    errors = check_shape(content)
    if errors:
        for error in errors:
            print(f"[FAIL] {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())