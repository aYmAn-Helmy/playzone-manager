from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class PendingEvent:
    event_id: str
    sequence: int
    event_type: str
    session_ref: str | None
    occurred_at: str
    payload: dict[str, Any]

    def to_wire(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "session_ref": self.session_ref,
            "occurred_at": self.occurred_at,
            "payload": self.payload,
        }


class EdgeStore:
    """Durable local runtime queue used while Cloud is unavailable.

    This database is deliberately not the PlayZone business-history database.
    It stores local sync/runtime metadata and pending events only.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS edge_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pending_events (
                    event_id TEXT PRIMARY KEY,
                    sequence INTEGER NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    session_ref TEXT,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_pending_events_sequence
                    ON pending_events(sequence);
                """
            )

    def _next_sequence(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT value FROM edge_meta WHERE key='next_sequence'").fetchone()
        sequence = int(row["value"]) if row else 1
        conn.execute(
            "INSERT INTO edge_meta(key,value) VALUES('next_sequence',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(sequence + 1),),
        )
        return sequence

    def enqueue(
        self,
        event_type: str,
        session_ref: str | None = None,
        payload: dict[str, Any] | None = None,
        occurred_at: str | None = None,
        event_id: str | None = None,
    ) -> PendingEvent:
        if not event_type or len(event_type) > 80:
            raise ValueError("invalid event_type")
        payload = payload or {}
        when = occurred_at or utc_iso()
        event_id = event_id or f"evt-{uuid.uuid4()}"
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            sequence = self._next_sequence(conn)
            conn.execute(
                """
                INSERT INTO pending_events(
                    event_id, sequence, event_type, session_ref,
                    occurred_at, payload_json, created_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (event_id, sequence, event_type, session_ref, when, json.dumps(payload, separators=(",", ":")), utc_iso()),
            )
            conn.commit()
        return PendingEvent(event_id, sequence, event_type, session_ref, when, payload)

    def pending(self, limit: int = 500) -> list[PendingEvent]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT event_id,sequence,event_type,session_ref,occurred_at,payload_json "
                "FROM pending_events ORDER BY sequence LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [
            PendingEvent(
                event_id=row["event_id"],
                sequence=row["sequence"],
                event_type=row["event_type"],
                session_ref=row["session_ref"],
                occurred_at=row["occurred_at"],
                payload=json.loads(row["payload_json"]),
            )
            for row in rows
        ]

    def acknowledge(self, event_ids: list[str]) -> int:
        if not event_ids:
            return 0
        placeholders = ",".join("?" for _ in event_ids)
        with self.connect() as conn:
            cur = conn.execute(f"DELETE FROM pending_events WHERE event_id IN ({placeholders})", event_ids)
            conn.commit()
            return cur.rowcount

    def pending_count(self) -> int:
        with self.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM pending_events").fetchone()[0])
