# status-archive

AWS doesn't keep old status updates around. Their status feed
([status.aws.amazon.com](https://status.aws.amazon.com)) only shows what's
happening right now, and once an incident is resolved it quietly drops off.
So if you wanted to know "was there a problem last month?" the answer was
basically no.

This project fixes that.

The idea is simple: I grab a copy of the feed every day and commit it to
git. Git keeps every version, so over time I end up with a full history
even though AWS never stored one. Then a script replays that history,
stitches the snapshots together, and turns them into something you can
actually query.

## How it works

```
GitHub Actions (daily)
    │
    ├─ fetch_feed.py        grabs https://status.aws.amazon.com/rss/all.rss
    │                       and writes data/aws-status.rss (committed)
    │
    ├─ check_feed_shape.py  fails loudly if AWS changes the feed format
    │
    ├─ diff_snapshots.py    prints "what changed since yesterday"
    │
    └─ git commit           git history IS the archive
                              │
                              ▼
    rebuild.py              replays every snapshot in history, merges the
    │                       updates, groups them into incidents
    │
    └─ out/status.db        SQLite with incidents + their updates
                              │
                              ▼
    api/main.py             FastAPI, read-only
```

A quirk of the feed: AWS re-renders `lastBuildDate` every few minutes, so
"did anything change" is decided by comparing the actual items, not the
bytes. Its format is also officially "subject to change", which is why the
pipeline guards against feed drift before it parses anything.

## Running it

Needs Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync

# rebuild the database from the archived snapshots
uv run python scripts/rebuild.py

# sanity-check the database against a fresh rebuild
uv run python scripts/check_integrity.py

# run the API
uv run uvicorn api.main:app --port 8000
```

The API endpoints are `/healthz`, `/incidents`, `/incidents/{key}`,
`/updates`, and `/metrics`. Open <http://localhost:8000/docs> for the
interactive OpenAPI page.

Or skip all of that and run the whole thing in Docker:

```bash
docker build -t status-archive .
docker run -p 8000:8000 status-archive
```

The image replays the history at build time, so a clone of the repo with
its git history and nothing else is enough to produce a working container.

## Tests

```bash
uv run python -m unittest discover -s tests
```

They cover parsing, incident grouping, snapshot diffs, the integrity
checks, and the feed-shape guard, with real feed samples in `fixtures/`.

## The deal with the data

Right now the archive is young, so the reconstructed history is short.
The whole point is that it compounds: every daily snapshot adds another
day to the record. Check back in a year.

Built with Python, FastAPI, and SQLite. Python because it's nice for this
kind of messy text scraping, SQLite because the data fits in a file, and
FastAPI because it gives you a usable API for almost free.

This is mostly a learning project, but if AWS ever breaks hard, it might
come in handy too.