# ============================================================
# MarketFloor — SQLite Database
# ============================================================
# Stores completed auctions & tasks for the analytics view.
# Zero-config; swap connection string for PostgreSQL later.

from __future__ import annotations
import sqlite3
import json
import os
import time

DB_PATH = os.environ.get("MF_DB_PATH", "marketfloor.db")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    """Create tables if they don't exist."""
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS auctions (
            id          TEXT PRIMARY KEY,
            task_id     TEXT NOT NULL,
            winner_id   TEXT,
            mode        TEXT NOT NULL,
            bids_json   TEXT NOT NULL,
            is_re_auction INTEGER DEFAULT 0,
            created_at  REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS completed_tasks (
            id          TEXT PRIMARY KEY,
            source      TEXT NOT NULL,
            destination TEXT NOT NULL,
            priority    TEXT NOT NULL,
            material    TEXT NOT NULL,
            assigned_agv TEXT,
            distance    INTEGER NOT NULL,
            completion_time_s REAL,
            created_at  REAL NOT NULL,
            completed_at REAL
        );
        """)


def save_auction(auction_id: str, task_id: str, winner_id: str | None,
                 mode: str, bids: list[dict], is_re: bool):
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO auctions VALUES (?,?,?,?,?,?,?)",
            (auction_id, task_id, winner_id, mode, json.dumps(bids),
             1 if is_re else 0, time.time()),
        )


def save_completed_task(task_dict: dict):
    ct = task_dict.get("completedAt") or time.time()
    ca = task_dict.get("createdAt", ct)
    dur = ct - ca if ct and ca else 0
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO completed_tasks VALUES (?,?,?,?,?,?,?,?,?,?)",
            (task_dict["id"], task_dict["source"], task_dict["destination"],
             task_dict["priority"], task_dict["material"],
             task_dict.get("assignedAGV"), task_dict["distance"],
             round(dur, 2), ca, ct),
        )


def get_analytics() -> dict:
    """Return aggregate stats for the analytics page."""
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM completed_tasks").fetchone()[0]
        avg_time = c.execute("SELECT AVG(completion_time_s) FROM completed_tasks").fetchone()[0] or 0
        avg_dist = c.execute("SELECT AVG(distance) FROM completed_tasks").fetchone()[0] or 0

        # per-mode breakdown (from auctions table)
        modes = {}
        for row in c.execute(
            "SELECT mode, COUNT(*) as cnt, AVG(json_extract(bids_json, '$[0].finalBid')) as avg_bid "
            "FROM auctions GROUP BY mode"
        ).fetchall():
            modes[row["mode"]] = {"count": row["cnt"], "avgBid": round(row["avg_bid"] or 0, 1)}

        # recent tasks
        recent = [dict(r) for r in c.execute(
            "SELECT * FROM completed_tasks ORDER BY completed_at DESC LIMIT 20"
        ).fetchall()]

    return {
        "totalCompleted": total,
        "avgCompletionTime": round(avg_time, 2),
        "avgDistance": round(avg_dist, 1),
        "byMode": modes,
        "recentTasks": recent,
    }
