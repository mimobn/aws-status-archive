#!/usr/bin/env python3
"""Read-only API over the rebuilt incident database.

Run with:  uv run uvicorn api.main:app
"""

import contextlib
import json
import os
import sqlite3
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "out", "status.db")

app = FastAPI(
    title="status-archive",
    description="AWS incident history reconstructed from the official Service Health JSON archives.",
    version="0.2.0",
)

# Enable CORS for local development and web frontends
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

INCIDENT_COLUMNS = (
    "incident_key, started_at, last_update, update_count, title, "
    "region, region_name, service, service_name"
)


def connect():
    """Open a read-only SQLite connection."""
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=503, detail="database not built yet")
    try:
        return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def get_incident_columns():
    """Detect which columns exist in the incidents table.

    Returns the base columns plus 'arn' and 'open' if they exist.
    """
    base_cols = [
        "incident_key", "started_at", "last_update", "update_count", "title",
        "region", "region_name", "service", "service_name"
    ]
    try:
        with contextlib.closing(connect()) as conn:
            cursor = conn.execute("PRAGMA table_info(incidents)")
            col_names = {row[1] for row in cursor.fetchall()}
    except HTTPException:
        # DB doesn't exist yet, return base columns
        return base_cols

    if "arn" in col_names:
        base_cols.append("arn")
    if "open" in col_names:
        base_cols.append("open")
    return base_cols


def parse_metadata_value(value: str):
    """Parse metadata value: try JSON first, fall back to raw string."""
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def row_to_incident(row, columns):
    """Convert a database row to an incident dict, handling dynamic columns."""
    result = {}
    for i, col in enumerate(columns):
        if i >= len(row):
            break
        value = row[i]
        if col == "open" and value is not None:
            # Convert integer to boolean
            result[col] = bool(value)
        else:
            result[col] = value
    return result


@app.get("/")
def index():
    return {
        "name": "status-archive",
        "endpoints": [
            "/healthz",
            "/incidents",
            "/incidents/{incident_key}",
            "/regions",
            "/updates",
            "/metrics",
            "/metadata",
        ],
    }


@app.get("/healthz")
def healthz():
    """Check API health and return key metrics."""
    try:
        with contextlib.closing(connect()) as conn:
            incidents = conn.execute("SELECT count(*) FROM incidents").fetchone()[0]
            updates = conn.execute("SELECT count(*) FROM updates").fetchone()[0]
            services = conn.execute("SELECT count(*) FROM services").fetchone()[0]
            meta_rows = conn.execute("SELECT key, value FROM metadata").fetchall()
            meta = {k: parse_metadata_value(v) for k, v in meta_rows}
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {
        "ok": True,
        "incidents": incidents,
        "updates": updates,
        "services": services,
        "archive_earliest_date": meta.get("archive_earliest_date"),
        "archive_latest_date": meta.get("archive_latest_date"),
        "rebuilt_at": meta.get("rebuilt_at"),
    }


@app.get("/incidents")
def incidents(
    region: str | None = None,
    service: str | None = None,
    open: bool | None = None,
):
    """List incidents with optional filtering."""
    columns = get_incident_columns()
    col_str = ", ".join(columns)

    try:
        with contextlib.closing(connect()) as conn:
            query = f"SELECT {col_str} FROM incidents"
            params = []
            conditions = []

            if region:
                conditions.append("(region = ? OR region_name = ?)")
                params.extend([region, region])
            if service:
                conditions.append("service = ?")
                params.append(service)
            # Check if 'open' column exists before filtering
            if open is not None and "open" in columns:
                conditions.append("open = ?")
                params.append(1 if open else 0)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY started_at DESC"

            rows = conn.execute(query, params).fetchall()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return [row_to_incident(row, columns) for row in rows]


@app.get("/incidents/{incident_key:path}")
def incident(incident_key: str):
    """Get a single incident by full or short key.

    Supports both full URL-encoded keys and short keys like 'ec2-us-east-1_1234567890'
    which will match incident_key ending with '#' + short_key.
    """
    decoded_key = unquote(incident_key)
    columns = get_incident_columns()
    col_str = ", ".join(columns)

    try:
        with contextlib.closing(connect()) as conn:
            # First try exact match (full or URL-decoded key)
            row = conn.execute(
                f"SELECT {col_str} FROM incidents WHERE incident_key = ? OR incident_key = ?",
                (incident_key, decoded_key),
            ).fetchone()

            # If no match, try matching by short key (ends with '#' + key)
            if row is None:
                rows = conn.execute(
                    f"SELECT {col_str} FROM incidents WHERE incident_key LIKE ?",
                    (f"%#{incident_key}",),
                ).fetchall()
                if rows:
                    row = rows[0]

            if row is None:
                raise HTTPException(status_code=404, detail="incident not found")

            actual_key = row[0]
            updates = conn.execute(
                "SELECT guid, published, severity, title, description "
                "FROM updates WHERE incident_key = ? ORDER BY published",
                (actual_key,),
            ).fetchall()
            services = conn.execute(
                "SELECT service_slug, service_name, severity, max_severity "
                "FROM services WHERE incident_key = ? ORDER BY service_name",
                (actual_key,),
            ).fetchall()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    incident_data = row_to_incident(row, columns)
    incident_data["updates"] = [
        {
            "guid": u[0],
            "published": u[1],
            "severity": u[2],
            "title": u[3],
            "description": u[4],
        }
        for u in updates
    ]
    incident_data["services"] = [
        {
            "service_slug": s[0],
            "service_name": s[1],
            "severity": s[2],
            "max_severity": s[3],
        }
        for s in services
    ]
    return incident_data


@app.get("/regions")
def regions():
    """List all regions with incident counts."""
    try:
        with contextlib.closing(connect()) as conn:
            rows = conn.execute(
                "SELECT region, region_name, count(*) as count "
                "FROM incidents WHERE region IS NOT NULL "
                "GROUP BY region ORDER BY region_name, region"
            ).fetchall()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return [
        {"region": r[0], "region_name": r[1] or r[0], "incidents_count": r[2]}
        for r in rows
    ]


@app.get("/updates")
def updates(
    severity: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
):
    """List recent updates with optional severity filter."""
    try:
        with contextlib.closing(connect()) as conn:
            if severity:
                rows = conn.execute(
                    "SELECT guid, incident_key, published, severity, title "
                    "FROM updates WHERE severity = ? ORDER BY published DESC LIMIT ?",
                    (severity, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT guid, incident_key, published, severity, title "
                    "FROM updates ORDER BY published DESC LIMIT ?",
                    (limit,),
                ).fetchall()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return [
        {
            "guid": r[0],
            "incident_key": r[1],
            "published": r[2],
            "severity": r[3],
            "title": r[4],
        }
        for r in rows
    ]


@app.get("/metrics")
def metrics():
    """Return aggregated metrics and metadata."""
    try:
        with contextlib.closing(connect()) as conn:
            incidents = conn.execute("SELECT count(*) FROM incidents").fetchone()[0]
            updates = conn.execute("SELECT count(*) FROM updates").fetchone()[0]
            services = conn.execute("SELECT count(*) FROM services").fetchone()[0]
            by_severity = conn.execute(
                "SELECT severity, count(*) FROM updates GROUP BY severity"
            ).fetchall()
            meta_rows = conn.execute("SELECT key, value FROM metadata").fetchall()
            meta = {k: parse_metadata_value(v) for k, v in meta_rows}
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {
        "incidents": incidents,
        "updates": updates,
        "services": services,
        "updates_by_severity": dict(by_severity),
        "archive_earliest_date": meta.get("archive_earliest_date"),
        "archive_latest_date": meta.get("archive_latest_date"),
        "rebuilt_at": meta.get("rebuilt_at"),
    }


@app.get("/metadata")
def metadata():
    """Return all metadata with parsed JSON values."""
    try:
        with contextlib.closing(connect()) as conn:
            meta_rows = conn.execute("SELECT key, value FROM metadata").fetchall()
            meta = {k: parse_metadata_value(v) for k, v in meta_rows}
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    if not meta:
        raise HTTPException(status_code=404, detail="no metadata available")
    return meta