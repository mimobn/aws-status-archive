#!/usr/bin/env python3
"""Read-only API over the rebuilt incident database.

Run with:  uv run uvicorn api.main:app
"""

import os
import sqlite3

from fastapi import FastAPI, HTTPException

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "out", "status.db")

app = FastAPI(
    title="status-archive",
    description="AWS incident history reconstructed from daily feed snapshots.",
    version="0.1.0",
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
    }


@app.get("/")
def index():
    return {
        "name": "status-archive",
        "endpoints": [
            "/healthz",
            "/incidents",
            "/incidents/{incident_key}",
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
        conn.close()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"ok": True, "incidents": incidents, "updates": updates}


@app.get("/incidents")
def incidents():
    conn = connect()
    rows = conn.execute(
        "SELECT incident_key, started_at, last_update, update_count, title "
        "FROM incidents ORDER BY started_at"
    ).fetchall()
    conn.close()
    return [row_to_incident(row) for row in rows]


@app.get("/incidents/{incident_key}")
def incident(incident_key: str):
    conn = connect()
    row = conn.execute(
        "SELECT incident_key, started_at, last_update, update_count, title "
        "FROM incidents WHERE incident_key = ?",
        (incident_key,),
    ).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="incident not found")
    updates = conn.execute(
        "SELECT guid, published, severity, title, description "
        "FROM updates WHERE incident_key = ? ORDER BY published",
        (incident_key,),
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
    return incident_data


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
    by_severity = conn.execute(
        "SELECT severity, count(*) FROM updates GROUP BY severity"
    ).fetchall()
    conn.close()
    return {
        "incidents": incidents,
        "updates": updates,
        "updates_by_severity": dict(by_severity),
    }
