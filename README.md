# status-archive

Ever wonder "was AWS down last week?" — well, AWS won't tell you. Their
[status page](https://status.aws.amazon.com) only shows what's happening
*right now*. Once an incident is resolved, it vanishes. No history, no archive.

This project fixes that by using git itself as the archive.

## The idea

Every day, a GitHub Actions workflow grabs a snapshot of the AWS status feed
and commits it to the repo. Over time, git's history *becomes* the missing
record. A rebuild script then replays every snapshot, stitches them together
into incidents, and writes them to a SQLite database and a JSON file.

The result: a browsable history of AWS incidents, complete with timelines,
severity levels, and region breakdowns — all reconstructed from daily
snapshots.

## Live page

The public site is here:

> **https://mimobn.github.io/aws-status-archive/**

It's a static page that rebuilds automatically every time a new snapshot
lands. What you see is exactly what the archive contains — nothing is
seeded or faked.

## Quick start

You'll need Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync

# Rebuild the database from archived snapshots
uv run python scripts/rebuild.py

# Sanity-check the result
uv run python scripts/check_integrity.py

# Run the API locally
uv run uvicorn api.main:app --port 8000
```

Then open <http://localhost:8000/docs> for the interactive API docs.

### Docker

```bash
docker build -t status-archive .
docker run -p 8000:8000 status-archive
```

The image replays the history at build time, so a clone of the repo with
its git history is all you need for a working container.

## API

The FastAPI backend is read-only and meant for local use. The public site
is the static GitHub Pages version, not this service.

| Endpoint | What it does |
|---|---|
| `GET /healthz` | Health check + counts |
| `GET /incidents` | List all incidents |
| `GET /incidents/{key}` | Incident detail with timeline |
| `GET /updates` | Recent updates (filterable by severity) |
| `GET /metrics` | Aggregate stats |

## Tests

```bash
uv run python -m unittest discover -s tests
```

Covers parsing, incident grouping, snapshot diffs, integrity checks, and
feed-shape validation — all with real feed samples in `fixtures/`.

## A note on the data

The archive is young, so the history is short. That's by design: every
daily snapshot adds another day to the record. The longer it runs, the
more valuable it gets.

Built with Python, FastAPI, and SQLite.
