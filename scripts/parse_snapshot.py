#!/usr/bin/env python3
"""Parse one AWS status snapshot into structured records.

Each <item> in the feed is a single status update, not a whole
incident. This script turns a snapshot file into a list of records,
one per update, with a severity label derived from the title prefix.
"""

import sys
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

# Severity comes from the title prefix. A single event moves between
# these over its lifetime, so the label is per-update, not per-event.
# The category names mirror what the AWS status page calls them.
SEVERITIES = {
    "Service disruption": "disrupted",
    "Service impact": "impacted",
    "Service degradation": "degraded",
    "Informational message": "informational",
    "Service is operating normally": "operational",
}


def parse_snapshot_text(content):
    """Parse RSS text into a list of update records.

    `published` is kept as a timezone-aware datetime so callers can
    sort across different UTC offsets; serialize with isoformat().
    """
    tree = ET.fromstring(content)
    channel = tree.find("channel")
    items = []
    for node in channel.findall("item"):
        title = node.findtext("title") or ""
        guid = node.findtext("guid") or ""
        published_raw = node.findtext("pubDate") or ""
        description = node.findtext("description") or ""

        severity = "unknown"
        for prefix, label in SEVERITIES.items():
            if title.startswith(prefix):
                severity = label
                break

        published = None
        if published_raw:
            published = parsedate_to_datetime(published_raw)

        items.append(
            {
                "guid": guid,
                "title": title,
                "severity": severity,
                "published": published,
                "description": description,
            }
        )
    return items


def parse_snapshot(path):
    with open(path, "r", encoding="utf-8") as handle:
        return parse_snapshot_text(handle.read())


def main():
    path = sys.argv[1]
    items = parse_snapshot(path)
    print(f"{len(items)} items")
    for item in items:
        published = item["published"].isoformat() if item["published"] else None
        print(f"{published}  {item['severity']:<13} {item['title'][:60]}")


if __name__ == "__main__":
    main()
