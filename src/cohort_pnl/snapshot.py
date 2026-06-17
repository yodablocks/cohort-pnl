"""snapshot.py -- SQLite daily snapshot writer/reader.

Schema stores one row per (date, asset, tier). The 7-day Bias Trend is a
read query over this table grouped by tier -- no separate computation needed.

Follows the pi-liqnode init_db pattern: idempotent setup, explicit schema,
no ORM.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator

DEFAULT_DB = Path(__file__).parent.parent.parent / "data" / "snapshots.db"


def init_db(path: Path = DEFAULT_DB) -> sqlite3.Connection:
    """Create tables if they do not exist. Returns an open connection."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cohort_snapshots (
            snapshot_date TEXT NOT NULL,
            asset         TEXT NOT NULL,
            tier          TEXT NOT NULL,
            bias_pct      REAL NOT NULL,
            position_count INTEGER NOT NULL,
            total_value   REAL NOT NULL,
            avg_liq_distance_pct REAL,
            created_at    TEXT NOT NULL,
            PRIMARY KEY (snapshot_date, asset, tier)
        )
    """)
    conn.commit()
    return conn


def write_snapshot(
    conn: sqlite3.Connection,
    snapshot_date: date,
    asset: str,
    tier: str,
    bias_pct: float,
    position_count: int,
    total_value: float,
    avg_liq_distance_pct: float | None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO cohort_snapshots
          (snapshot_date, asset, tier, bias_pct, position_count,
           total_value, avg_liq_distance_pct, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        snapshot_date.isoformat(),
        asset.upper(),
        tier,
        bias_pct,
        position_count,
        total_value,
        avg_liq_distance_pct,
        now,
    ))
    conn.commit()


def read_bias_trend(
    conn: sqlite3.Connection,
    asset: str,
    tier: str,
    days: int = 7,
) -> list[tuple[str, float]]:
    """Return (date, bias_pct) rows for the last `days` days, oldest first."""
    rows = conn.execute("""
        SELECT snapshot_date, bias_pct
        FROM cohort_snapshots
        WHERE asset = ? AND tier = ?
        ORDER BY snapshot_date DESC
        LIMIT ?
    """, (asset.upper(), tier, days)).fetchall()
    return list(reversed(rows))
