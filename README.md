# status-archive

A long-term, reproducible archive of AWS public service health events.

AWS's public Service Health Dashboard provides a Service History covering the previous 12 months. Once events fall outside that rolling window, they are no longer available through the public Service History in the same way. This project continuously archives the public data published by AWS so that historical service health information can be preserved and analyzed independently.

## Table of Contents

* [The Idea](#the-idea)
* [Live Page](#live-page)
* [Quick Start](#quick-start)
* [API](#api)
* [Tests](#tests)
* [Data](#data)

  * [Data Sources](#data-sources)
  * [Data Semantics](#data-semantics)
  * [Metrics](#metrics)
  * [Day Classification](#day-classification)
  * [Severity Levels](#severity-levels)
* [Technology](#technology)

## The Idea

AWS publishes public service health information through its Service Health Dashboard. The Service History currently provides a rolling view of AWS service interruptions from the previous 12 months. This project preserves that information by periodically archiving the underlying public data.

The archive is built from three public JSON files:

| File                 | Description                                           |
| -------------------- | ----------------------------------------------------- |
| `services.json`      | Service and Region catalog with display names         |
| `historyevents.json` | Historical and ongoing incidents with update logs     |
| `currentevents.json` | Currently open incidents and per-service availability |

A scheduled workflow fetches these files and stores each snapshot in Git. This makes the historical data reproducible and auditable.

The rebuild process then combines the archived snapshots into a normalized dataset containing:

* AWS service and Region incidents
* Incident timelines and status updates
* Severity levels
* Regional breakdowns
* Per-service availability
* Archive metadata

The resulting data is written to both SQLite and JSON for use by the API and the public website.

## Live Page

The public archive is available at:

**https://mimobn.github.io/aws-status-archive/**

The site is static and is rebuilt automatically when a new archive snapshot is added.

Everything displayed on the site is derived from the archived AWS data. No incidents or status observations are manually seeded or fabricated.

## Quick Start

Requirements:

* Python 3.13+
* [uv](https://docs.astral.sh/uv/)

Install the project dependencies:

```bash
uv sync
```

Fetch the latest public data from AWS:

```bash
uv run python scripts/fetch_archive.py
```

Rebuild the database and generated JSON:

```bash
uv run python scripts/rebuild.py
```

Run the integrity checks:

```bash
uv run python scripts/check_integrity.py
```

Start the local API:

```bash
uv run uvicorn api.main:app --port 8000
```

The interactive API documentation is available at:

**http://localhost:8000/docs**

## API

The FastAPI backend is read-only and primarily intended for local use and development.

The public website uses the generated static data rather than exposing this API directly.

| Endpoint               | Description                                             |
| ---------------------- | ------------------------------------------------------- |
| `GET /healthz`         | Health check, archive counts, and freshness information |
| `GET /incidents`       | List archived incidents                                 |
| `GET /incidents/{key}` | Incident details, timeline, and affected services       |
| `GET /regions`         | Regions with incident counts                            |
| `GET /updates`         | Recent status updates, optionally filtered by severity  |
| `GET /metrics`         | Aggregate statistics and archive metadata               |
| `GET /metadata`        | Archive date range, counts, and rebuild information     |

## Tests

Run the test suite with:

```bash
uv run python -m unittest discover -s tests
```

The tests cover:

* Data parsing
* Incident construction
* Archive differences
* Integrity checks
* Archive structure validation

Tests use real sample data stored in `fixtures/`.

## Data

### Data Sources

Each archived snapshot contains the public AWS data used to reconstruct the service health history.

#### `services.json`

Contains the AWS service and Region catalog, including display names and identifiers.

#### `historyevents.json`

Contains historical and ongoing public service incidents together with their update logs.

#### `currentevents.json`

Contains currently open incidents and per-service availability information.

Snapshots are stored in Git, allowing the archive to preserve the state published by AWS at each collection time.

### Data Semantics

#### Archived Snapshot

An archived snapshot represents a point-in-time dump of the public AWS Service Health Dashboard data.

Each snapshot contains:

* The AWS service catalog
* Historical incidents and their update logs
* Currently open incidents
* Per-service availability information

#### Incident

An incident represents a service and Region event during a specific time window.

For example:

```text
ec2-us-east-1
```

Incident records are keyed using the service identifier and event start timestamp.

#### Status Update

A status update is a timestamped entry in an incident's event log.

The timestamps represent publication times recorded by AWS. They should not necessarily be interpreted as the exact moment when the underlying service state changed.

#### Absence of an Incident

The archive does **not** provide continuous health observations.

AWS public event data is incident-based. Therefore:

> No incident does not mean confirmed healthy operation.

A day with no archived incident activity is classified as **No Data**, rather than as confirmed operational.

#### No Data vs Operational

The archive distinguishes between:

* **Operational**: an explicit operational status update associated with an incident, typically indicating resolution.
* **No Data**: no archived incident activity was recorded for the period.

This distinction prevents periods without incident data from being incorrectly interpreted as periods of confirmed healthy operation.

### Metrics

#### Activity Days

Days on which at least one incident update exists in the archive.

Activity days indicate incident-related activity and do not represent confirmed healthy operation.

#### Total Incidents

The number of distinct service and Region incidents represented in the archive.

#### Impact Days

Activity days on which at least one incident had a severity worse than operational.

This includes:

* Degraded
* Impacted
* Disrupted

#### Resolution Days

Activity days containing only operational status updates.

These days generally represent the resolution of existing incidents rather than independent observations that a service was continuously healthy.

### Day Classification

The heatmap and related metrics classify each day into one of three categories:

| Classification     | Meaning                                             |
| ------------------ | --------------------------------------------------- |
| **Impact Day**     | At least one non-operational status update occurred |
| **Resolution Day** | Only operational status updates occurred            |
| **No Data**        | No archived incident activity occurred              |

The classification is intentionally conservative.

An absence of incidents is not treated as evidence that AWS services were operating normally.

### Severity Levels

| Level         | Meaning                                               |
| ------------- | ----------------------------------------------------- |
| `operational` | Incident resolved with an explicit operational status |
| `degraded`    | Service degraded                                      |
| `impacted`    | Service impacted                                      |
| `disrupted`   | Service disrupted                                     |
| `no_data`     | No archived incident observation for the period       |
| `unknown`     | Status could not be determined                        |

## Technology

The project is built with:

* Python
* FastAPI
* SQLite
* GitHub Actions
* GitHub Pages

The archive itself is stored in Git, while the generated SQLite and JSON data provide the structured data used by the API and static website.
