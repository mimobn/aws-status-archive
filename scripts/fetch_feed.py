#!/usr/bin/env python3
"""Fetch the AWS status feed and save a snapshot to data/.

The point of this script is to be boring. It grabs the feed, writes it
over data/aws-status.rss, and reports whether anything changed. Git
keeps the history once the workflow commits the file.

AWS re-renders the feed every few minutes and bumps lastBuildDate each
time, so "changed" is decided by comparing the actual items, not the
bytes. Otherwise we'd commit noise every single day.

Exits 0 as long as the fetch itself worked; whether the feed changed
is informational. The workflow looks at git status to decide if there
is anything worth committing.
"""

import sys
import urllib.request

from parse_snapshot import parse_snapshot_text

FEED_URL = "https://status.aws.amazon.com/rss/all.rss"
OUT_PATH = "data/aws-status.rss"


def item_signatures(content):
    """A comparable signature per item, ignoring feed-level noise."""
    return {
        (
            item["guid"],
            item["published"],
            item["severity"],
            item["title"],
            item["description"],
        )
        for item in parse_snapshot_text(content)
    }


def main():
    request = urllib.request.Request(
        FEED_URL,
        headers={"User-Agent": "status-archive/0.1"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()

    previous = None
    try:
        with open(OUT_PATH, "rb") as handle:
            previous = handle.read()
    except FileNotFoundError:
        pass

    changed = True
    if previous is not None:
        changed = item_signatures(previous.decode("utf-8")) != item_signatures(
            body.decode("utf-8")
        )

    if changed:
        with open(OUT_PATH, "wb") as handle:
            handle.write(body)
        print(f"changed: wrote {len(body)} bytes to {OUT_PATH}")
    else:
        print("no change")
    return 0


if __name__ == "__main__":
    sys.exit(main())
