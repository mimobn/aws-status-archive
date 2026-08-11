#!/usr/bin/env python3
"""Parse one AWS status snapshot into structured records.

Each <item> in the feed is a single status update, not a whole
incident. This script turns a snapshot file into a list of records,
one per update, with a severity label derived from the title prefix.
"""

import sys
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

# Severity comes from the title prefix. A single event moves between
# these over its lifetime, so the label is per-update, not per-event.
SEVERITIES = {
    "Service disruption": "disruption",
    "Service impact": "impact",
    "Service degradation": "degradation",
    "Informational message": "informational",
    "Service is operating normally": "operational",
}


def parse_snapshot(path):
    tree = ET.parse(path)
    channel = tree.getroot().find("channel")
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
            published = parsedate_to_datetime(published_raw).isoformat()

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


def main():
    path = sys.argv[1]
    items = parse_snapshot(path)
    print(f"{len(items)} items")
    for item in items:
        print(f"{item['published']}  {item['severity']:<13} {item['title'][:60]}")


if __name__ == "__main__":
    main()
