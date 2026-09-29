#!/usr/bin/env python3
"""One-command local server for the status-archive site.

Serves the site from site/ and generated data from out/, with automatic
rebuild if data files are newer than the output.

Usage:
    python scripts/serve.py [--port 8000] [--host 127.0.0.1] [--no-rebuild]
"""

import argparse
import glob
import http.server
import os
import urllib.parse
import sys
from datetime import datetime
from pathlib import Path

# Add scripts directory to path so we can import rebuild
sys.path.insert(0, os.path.dirname(__file__))

try:
    import rebuild
except ImportError:
    rebuild = None


def resolve_path(url_path, site_dir, out_dir):
    """Resolve a URL path to a filesystem path, handling /parsed/* specially.

    Maps /parsed/* to out_dir (only incidents.json and metadata.json allowed).
    Maps everything else to site_dir (with directory index for /).
    Prevents path traversal attacks.

    Args:
        url_path: URL path (e.g. "/app.js" or "/parsed/incidents.json")
        site_dir: Filesystem path to site directory
        out_dir: Filesystem path to out directory

    Returns:
        Absolute filesystem path if allowed, or None if forbidden/not found.
    """
    # Normalize the path to remove double slashes and resolve . and ..
    # Start by removing leading slash
    if url_path.startswith("/"):
        url_path = url_path[1:]

    # Special case: root path serves index.html from site_dir
    if not url_path or url_path == "":
        return os.path.join(site_dir, "index.html")

    if url_path.startswith("parsed/"):
        # /parsed/* requests map to out/
        file_name = url_path[7:]  # Remove "parsed/" prefix

        # Only allow incidents.json and metadata.json
        if file_name not in ("incidents.json", "metadata.json"):
            return None

        # Reconstruct the path and check it doesn't escape
        full_path = os.path.normpath(os.path.join(out_dir, file_name))
        out_dir_normalized = os.path.normpath(out_dir)

        # Ensure the resolved path is within out_dir
        if not full_path.startswith(out_dir_normalized + os.sep) and full_path != out_dir_normalized:
            return None

        return full_path if os.path.exists(full_path) else None
    else:
        # Everything else maps to site_dir
        # Reconstruct the path and check it doesn't escape
        full_path = os.path.normpath(os.path.join(site_dir, url_path))
        site_dir_normalized = os.path.normpath(site_dir)

        # Ensure the resolved path is within site_dir
        if not full_path.startswith(site_dir_normalized + os.sep) and full_path != site_dir_normalized:
            return None

        # If it's a directory and index.html exists, return that
        if os.path.isdir(full_path):
            index_path = os.path.join(full_path, "index.html")
            return index_path if os.path.exists(index_path) else None

        return full_path if os.path.exists(full_path) else None


def needs_rebuild(out_dir, data_dir):
    """Check if rebuild is needed based on mtime of source files.

    Returns True if out/incidents.json is missing or older than any file in
    data/ or data/archive/.

    Args:
        out_dir: Path to out directory
        data_dir: Path to data directory

    Returns:
        True if rebuild is needed, False otherwise.
    """
    incidents_json = os.path.join(out_dir, "incidents.json")

    # If output doesn't exist, rebuild is needed
    if not os.path.exists(incidents_json):
        return True

    out_mtime = os.path.getmtime(incidents_json)

    # Check all JSON files in data/ and data/archive/
    data_files = glob.glob(os.path.join(data_dir, "*.json"))
    data_files.extend(glob.glob(os.path.join(data_dir, "archive", "*.json")))

    for data_file in data_files:
        if os.path.getmtime(data_file) > out_mtime:
            return True

    return False


class SiteHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP request handler that serves site/ and /parsed/* from out/."""

    def __init__(self, *args, site_dir=None, out_dir=None, **kwargs):
        self.site_dir = site_dir or os.path.join(os.path.dirname(__file__), "..", "site")
        self.out_dir = out_dir or os.path.join(os.path.dirname(__file__), "..", "out")
        super().__init__(*args, directory=self.site_dir, **kwargs)

    def translate_path(self, path):
        """Translate a /-initial abstract path to a file path."""
        # Drop the query/fragment and percent-decode, like the base class does.
        path = urllib.parse.unquote(path.split("?", 1)[0].split("#", 1)[0])
        fs_path = resolve_path(path, self.site_dir, self.out_dir)
        return fs_path if fs_path else ""

    def end_headers(self):
        """Add Cache-Control header to prevent stale pages."""
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format, *args):
        """Log HTTP requests."""
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), format % args))


def main():
    """Parse arguments and start the server."""
    parser = argparse.ArgumentParser(
        description="Serve the status-archive site locally with automatic rebuild."
    )
    parser.add_argument("--port", type=int, default=8000, help="Port to serve on (default: 8000)")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
    parser.add_argument("--no-rebuild", action="store_true", help="Skip automatic rebuild")

    args = parser.parse_args()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    site_dir = os.path.join(repo_root, "site")
    out_dir = os.path.join(repo_root, "out")
    data_dir = os.path.join(repo_root, "data")

    # Rebuild if needed
    if not args.no_rebuild and rebuild:
        if needs_rebuild(out_dir, data_dir):
            print("Rebuilding output files...")
            try:
                rebuild.main()
            except Exception as e:
                print(f"Rebuild failed: {e}", file=sys.stderr)
                sys.exit(1)
            print("Rebuild complete.")
        else:
            print("Output files are up to date.")
    elif not args.no_rebuild and not rebuild:
        print("Warning: rebuild module not available, skipping automatic rebuild", file=sys.stderr)

    # Create server
    handler_class = lambda *args, **kwargs: SiteHTTPRequestHandler(
        *args, site_dir=site_dir, out_dir=out_dir, **kwargs
    )

    try:
        server = http.server.ThreadingHTTPServer((args.host, args.port), handler_class)
    except OSError as e:
        print(f"Error: Could not bind to {args.host}:{args.port}: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Serving status-archive at http://{args.host}:{args.port}/")

    # Ctrl+C raises KeyboardInterrupt out of serve_forever(); calling
    # server.shutdown() from this same thread would deadlock.
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", file=sys.stderr)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
