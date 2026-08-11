#!/usr/bin/env python3
"""Fetch the AWS status feed and save a snapshot to data/.

The point of this script is to be boring. It grabs the feed, writes it
over data/aws-status.rss, and tells you whether anything changed. Git
keeps the history once the workflow commits the file.
"""

import hashlib
import sys
import urllib.request

FEED_URL = "https://status.aws.amazon.com/rss/all.rss"
OUT_PATH = "data/aws-status.rss"


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

    with open(OUT_PATH, "wb") as handle:
        handle.write(body)

    digest = hashlib.sha256(body).hexdigest()[:16]
    print(f"fetched {len(body)} bytes (sha {digest})")
    if previous == body:
        print("no change")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
