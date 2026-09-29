#!/usr/bin/env python3
"""Fetch the AWS status archive JSON files and save them to data/.

The AWS Service Health Dashboard exposes the data behind its Service
history table as three public JSON files:

  * services.json      - the service + region catalog (display names)
  * historyevents.json - resolved/open incidents with full update logs
  * currentevents.json - currently open events, including the list of
                         affected services and per-service status changes

Unlike the old RSS feed, these files already carry ~12 months of history,
so the archive no longer needs to reconstruct incidents from daily
snapshots. Git still keeps the files under version control so we can see
how the official data evolved.

The script is deliberately boring: fetch, decode, normalize, write.
Whether a file changed is decided by comparing the normalized JSON so we
don't commit noise. Exits 0 as long as the fetch itself worked; the
workflow looks at git status to decide if there is anything to commit.
"""

import gzip
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

SOURCES = {
    "services.json": "https://servicedata-eu-west-1-prod.s3.amazonaws.com/services.json",
    "historyevents.json": "https://history-events-eu-west-1-prod.s3.amazonaws.com/historyevents.json",
    "currentevents.json": "https://health.aws.amazon.com/health/public/currentevents",
}

GZIP_MAGIC = b"\x1f\x8b"
UTF16_LE_BOM = b"\xff\xfe"
UTF16_BE_BOM = b"\xfe\xff"
UTF8_BOM = b"\xef\xbb\xbf"


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "status-archive/0.2"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def decode_json_bytes(raw):
    """Decode raw bytes into parsed JSON.

    AWS serves the same data with different encodings per endpoint
    (plain UTF-8, gzip, UTF-16 with BOM), so normalize them all to text
    before parsing.
    """
    if raw.startswith(GZIP_MAGIC):
        raw = gzip.decompress(raw)
    if raw.startswith(UTF16_LE_BOM) or raw.startswith(UTF16_BE_BOM):
        raw = raw.decode("utf-16").encode("utf-8")
    if raw.startswith(UTF8_BOM):
        raw = raw[len(UTF8_BOM):]
    return json.loads(raw.decode("utf-8"))


def canonical_json(value):
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main():
    any_failed = False
    for name, url in SOURCES.items():
        out_path = DATA_DIR / name
        try:
            raw = fetch(url)
        except Exception as exc:  # noqa: BLE001 - report and keep going
            print(f"[FAIL] {name}: fetch failed: {exc}", file=sys.stderr)
            any_failed = True
            continue

        try:
            parsed = decode_json_bytes(raw)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {name}: could not decode JSON: {exc}", file=sys.stderr)
            any_failed = True
            continue

        # Refuse empty payloads: services should be a non-empty list, history should be a non-empty dict
        if isinstance(parsed, (dict, list)) and not parsed:
            expected_type = "list" if name == "services.json" else "dict"
            print(f"[FAIL] {name}: empty {expected_type} payload", file=sys.stderr)
            any_failed = True
            continue

        text = canonical_json(parsed)
        previous = out_path.read_text(encoding="utf-8") if out_path.exists() else None

        if text == previous:
            print(f"no change: {name}")
        else:
            # Write atomically: write to temp file in same dir, then replace
            fd, temp_path = tempfile.mkstemp(suffix=".json", dir=str(out_path.parent), text=False)
            try:
                with open(fd, "w", encoding="utf-8") as f:
                    f.write(text)
                os.replace(temp_path, str(out_path))
                print(f"changed: wrote {len(text.encode('utf-8'))} bytes to {out_path.relative_to(BASE_DIR)}")
            except Exception:
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
                raise

    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
