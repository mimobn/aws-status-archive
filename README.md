# status-archive

Ever wonder "was AWS down last week?" — well, AWS won't tell you. Their
[status page](https://status.aws.amazon.com) only shows what's happening
*right now*, and their "Service history" table disappears after 12 months.
This project fixes that by archiving the data AWS itself doesn't keep.

## The idea

AWS renders its Service history table from three public JSON files (the
same data behind `https://status.aws.amazon.com`):

* `services.json` — the service/region catalog with display names
* `historyevents.json` — resolved/open incidents with full update logs
* `currentevents.json` — open incidents plus per-service availability

A daily workflow archives these files into git, so the history is
reproducible and auditable. A rebuild script merges them into incidents
(with per-service availability inside each region), then writes a SQLite
database and a JSON file for the site.

The result: a browsable history of AWS incidents, complete with timelines,
severity levels, region breakdowns, and per-service availability.

## Live page

The public site is here:

> **https://mimobn.github.io/aws-status-archive/**

It's a static page that rebuilds automatically every time a new snapshot
lands. What you see is exactly what the archives contain — nothing is
seeded or faked.

## Quick start

You'll need Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync

# Fetch the latest archives from AWS (network access required)
uv run python scripts/fetch_archive.py

# Rebuild the database from the archived JSON
uv run python scripts/rebuild.py

# Sanity-check the result
uv run python scripts/check_integrity.py

# Run the API locally
uv run uvicorn api.main:app --port 8000
```

Then open <http://localhost:8000/docs> for the interactive API docs.

## API

The FastAPI backend is read-only and meant for local use. The public site
is the static GitHub Pages version, not this service.

| Endpoint | What it does |
|---|---|
| `GET /healthz` | Health check + counts + archive freshness |
| `GET /incidents` | List all incidents |
| `GET /incidents/{key}` | Incident detail with timeline + services |
| `GET /regions` | Regions with incident counts |
| `GET /updates` | Recent updates (filterable by severity) |
| `GET /metrics` | Aggregate stats + archive metadata |
| `GET /metadata` | Archive metadata (date range, counts, rebuild time) |

## Tests

```bash
uv run python -m unittest discover -s tests
```

Covers parsing, incident building, archive diffs, integrity checks, and
archive-shape validation — all with real samples in `fixtures/`.

## A note on the data

The archives are snapshots of what AWS publishes, fetched on a schedule and
stored in git. The history reaches back about 12 months (as far as AWS
keeps it); the daily archive keeps that window rolling forward.

### Data semantics

**What an archived snapshot represents:** A point-in-time dump of the AWS
Service Health Dashboard's internal state. It contains three JSON files:
the service catalog, historical incidents with full update logs, and
currently open incidents with per-service status.

**What an incident represents:** A single service+region event (e.g.,
`ec2-us-east-1` during a specific time window). Incidents are keyed by
service slug and event start timestamp.

**What a status update represents:** A timestamped status change entry
within an incident's event log. Timestamps are publication times (unix
seconds), not necessarily the exact moment a state transition occurred.

**What absence of an incident means:** The archive does NOT confirm
normal operation. AWS only populates the feed with incidents. No incident
on a given day = no data, not confirmed healthy.

**"No data" vs "operational":** The dashboard distinguishes between
these states. Days without archived incident data are shown as
"no data" (gray), not "operational" (green). The incident-free rate is
calculated only across days where observations exist.

### Metrics

- **Incident-Free Rate:** `clean_days / observed_days` — the fraction of
  observed days with no active incidents. Only counts days that have at
  least one status update in the archive.
- **Archive Coverage:** The number of days with observations, plus the
  count of unknown days in the calendar range.
- **Impacted Days:** Days where at least one incident had a severity
  worse than operational.

### Severity levels

| Level | Meaning |
|---|---|
| `operational` | Service confirmed working (explicit status=0 in archive) |
| `degraded` | Service degraded (status=2) |
| `impacted` | Service impacted (status=1) |
| `disrupted` | Service disrupted (status=3) |
| `no_data` | No archived observation for this period |
| `unknown` | Status could not be determined |

Built with Python, FastAPI, and SQLite.
