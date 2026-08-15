#!/usr/bin/env python3
"""Read-only API over the rebuilt incident database.

Run with:  uv run uvicorn api.main:app
"""

import os
import sqlite3
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException
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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

INCIDENT_COLUMNS = (
    "incident_key, started_at, last_update, update_count, title, "
    "region, region_name, service, service_name"
)


def connect():
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=503, detail="database not built yet")
    return sqlite3.connect(DB_PATH)


def row_to_incident(row):
    return {
        "incident_key": row[0],
        "started_at": row[1],
        "last_update": row[2],
        "update_count": row[3],
        "title": row[4],
        "region": row[5],
        "region_name": row[6],
        "service": row[7],
        "service_name": row[8],
    }


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
        ],
    }


@app.get("/healthz")
def healthz():
    try:
        conn = connect()
        incidents = conn.execute("SELECT count(*) FROM incidents").fetchone()[0]
        updates = conn.execute("SELECT count(*) FROM updates").fetchone()[0]
        services = conn.execute("SELECT count(*) FROM services").fetchone()[0]
        conn.close()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"ok": True, "incidents": incidents, "updates": updates, "services": services}


@app.get("/incidents")
def incidents(region: str | None = None, service: str | None = None):
    conn = connect()
    query = f"SELECT {INCIDENT_COLUMNS} FROM incidents"
    params = []
    conditions = []
    if region:
        conditions.append("(region = ? OR region_name = ?)")
        params.extend([region, region])
    if service:
        conditions.append("service = ?")
        params.append(service)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY started_at DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [row_to_incident(row) for row in rows]


@app.get("/incidents/{incident_key:path}")
def incident(incident_key: str):
    decoded_key = unquote(incident_key)
    conn = connect()
    row = conn.execute(
        f"SELECT {INCIDENT_COLUMNS} FROM incidents WHERE incident_key = ? OR incident_key = ?",
        (incident_key, decoded_key),
    ).fetchone()
    if row is None:
        conn.close()
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
    conn.close()
    incident_data = row_to_incident(row)
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
    conn = connect()
    rows = conn.execute(
        "SELECT region, region_name, count(*) as count "
        "FROM incidents WHERE region IS NOT NULL "
        "GROUP BY region ORDER BY region_name, region"
    ).fetchall()
    conn.close()
    return [
        {"region": r[0], "region_name": r[1] or r[0], "incidents_count": r[2]}
        for r in rows
    ]


@app.get("/updates")
def updates(severity: str | None = None, limit: int = 100):
    conn = connect()
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
    conn.close()
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
    conn = connect()
    incidents = conn.execute("SELECT count(*) FROM incidents").fetchone()[0]
    updates = conn.execute("SELECT count(*) FROM updates").fetchone()[0]
    services = conn.execute("SELECT count(*) FROM services").fetchone()[0]
    by_severity = conn.execute(
        "SELECT severity, count(*) FROM updates GROUP BY severity"
    ).fetchall()
    conn.close()
    return {
        "incidents": incidents,
        "updates": updates,
        "services": services,
        "updates_by_severity": dict(by_severity),
    }