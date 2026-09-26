from __future__ import annotations

import base64
import ctypes
import json
import os
import sqlite3
import threading
import uuid
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import joinedload

# This module is copied into backend/app/edge_runtime.py when packaging the
# transitional PlayZone v0.27 -> SaaS Edge build. These imports deliberately
# target the existing PlayZone runtime package.
from .activation import machine_hash, machine_label
from .db import DB_PATH, SessionLocal
from .models import AuditLog, Invoice, PlaySession, Station

EDGE_DB_PATH = Path(os.getenv("PLAYZONE_EDGE_DB_PATH", DB_PATH.parent / "edge.db")).expanduser().resolve()
EDGE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
EDGE_SYNC_INTERVAL_SECONDS = max(2.0, float(os.getenv("PLAYZONE_EDGE_SYNC_INTERVAL", "5")))
EDGE_BATCH_SIZE = max(1, min(500, int(os.getenv("PLAYZONE_EDGE_BATCH_SIZE", "200"))))
EDGE_APP_VERSION = os.getenv("PLAYZONE_EDGE_APP_VERSION", "0.28-saas-prototype")

_SYNC_STOP = threading.Event()
_SYNC_THREAD: threading.Thread | None = None
_LOCK = threading.RLock()

AUDIT_EVENT_MAP = {
    "SESSION_STARTED": "SESSION_STARTED",
    "SESSION_CONTROLLERS_CHANGED": "CONTROLLERS_CHANGED",
    "SESSION_PAUSED": "SESSION_PAUSED",
    "SESSION_RESUMED": "SESSION_RESUMED",
    "TIMED_SESSION_EXTENDED": "SESSION_EXTENDED",
    "TIMED_SESSION_EXPIRED": "SESSION_EXPIRED",
    "PRODUCT_ADDED": "PRODUCT_ADDED",
    "SESSION_ENDED": "SESSION_ENDED",
    "INVOICE_FINALIZED": "SESSION_INVOICED",
    "VOLTRA_POWER_ON": "POWER_ON",
    "VOLTRA_POWER_OFF": "POWER_OFF",
}


def _utc_iso(value: datetime | None = None) -> str:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(EDGE_DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_edge_db() -> None:
    with _connect() as conn:
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


def _meta_get(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM edge_meta WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row else default


def _meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO edge_meta(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def _next_sequence(conn: sqlite3.Connection) -> int:
    sequence = int(_meta_get(conn, "next_sequence", "1") or "1")
    _meta_set(conn, "next_sequence", str(sequence + 1))
    return sequence


def _protect_secret(raw: str) -> str:
    data = raw.encode("utf-8")
    if os.name != "nt":
        return "plain:" + base64.urlsafe_b64encode(data).decode("ascii")

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    buf = ctypes.create_string_buffer(data)
    in_blob = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    out_blob = DATA_BLOB()
    CRYPTPROTECT_LOCAL_MACHINE = 0x4
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, CRYPTPROTECT_LOCAL_MACHINE, ctypes.byref(out_blob)
    ):
        raise OSError("Windows DPAPI CryptProtectData failed")
    try:
        protected = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return "dpapi:" + base64.urlsafe_b64encode(protected).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _unprotect_secret(stored: str) -> str:
    if stored.startswith("plain:"):
        return base64.urlsafe_b64decode(stored[6:].encode("ascii")).decode("utf-8")
    if not stored.startswith("dpapi:") or os.name != "nt":
        raise ValueError("unsupported protected secret")

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    protected = base64.urlsafe_b64decode(stored[6:].encode("ascii"))
    buf = ctypes.create_string_buffer(protected)
    in_blob = DATA_BLOB(len(protected), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    out_blob = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise OSError("Windows DPAPI CryptUnprotectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def enqueue_event(
    event_type: str,
    *,
    event_id: str | None = None,
    session_ref: str | None = None,
    occurred_at: datetime | str | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    init_edge_db()
    event_id = event_id or f"evt-{uuid.uuid4()}"
    when = occurred_at if isinstance(occurred_at, str) else _utc_iso(occurred_at)
    payload = payload or {}
    with _LOCK, _connect() as conn:
        if conn.execute("SELECT 1 FROM pending_events WHERE event_id=?", (event_id,)).fetchone():
            return event_id
        conn.execute("BEGIN IMMEDIATE")
        sequence = _next_sequence(conn)
        conn.execute(
            "INSERT INTO pending_events(event_id,sequence,event_type,session_ref,occurred_at,payload_json,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (event_id, sequence, event_type, session_ref, when, json.dumps(payload, separators=(",", ":")), _utc_iso()),
        )
        conn.commit()
    return event_id


def _parse_details(details: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in str(details or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key:
            result[key] = value
    return result


def _session_payload(db, session_id: int) -> dict[str, Any]:
    session = db.scalar(
        select(PlaySession).where(PlaySession.id == session_id).options(joinedload(PlaySession.station))
    )
    if session is None:
        return {"session_id": session_id}
    return {
        "session_id": session.id,
        "station_id": session.station_id,
        "station_code": session.station.code if session.station else None,
        "status": session.status,
        "session_type": session.session_type,
        "controller_count": int(getattr(session, "controller_count", 2) or 2),
        "hourly_rate_piasters": session.hourly_rate_piasters,
        "grace_seconds": session.grace_seconds,
        "started_at": _utc_iso(session.started_at),
        "ended_at": _utc_iso(session.ended_at) if session.ended_at else None,
        "timed_total_seconds": session.timed_total_seconds,
        "timed_remaining_seconds": session.timed_remaining_seconds,
        "multi_3_billable_seconds": int(getattr(session, "multi_3_billable_seconds", 0) or 0),
        "multi_4_billable_seconds": int(getattr(session, "multi_4_billable_seconds", 0) or 0),
    }


def _invoice_payload(db, invoice_id: int) -> tuple[str | None, dict[str, Any]]:
    invoice = db.scalar(
        select(Invoice)
        .where(Invoice.id == invoice_id)
        .options(joinedload(Invoice.session).joinedload(PlaySession.station))
    )
    if invoice is None:
        return None, {"invoice_id": invoice_id}
    session = invoice.session
    return str(session.id), {
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "session_id": invoice.session_id,
        "station_id": session.station_id,
        "station_code": session.station.code if session.station else None,
        "amount_piasters": invoice.amount_piasters,
        "gameplay_amount_piasters": invoice.gameplay_amount_piasters,
        "base_gameplay_amount_piasters": invoice.base_gameplay_amount_piasters,
        "multi_amount_piasters": invoice.multi_amount_piasters,
        "multi_3_seconds": invoice.multi_3_seconds,
        "multi_3_amount_piasters": invoice.multi_3_amount_piasters,
        "multi_4_seconds": invoice.multi_4_seconds,
        "multi_4_amount_piasters": invoice.multi_4_amount_piasters,
        "products_amount_piasters": invoice.products_amount_piasters,
        "discount_piasters": invoice.discount_piasters,
        "payment_method": invoice.payment_method,
        "created_at": _utc_iso(invoice.created_at),
    }


def scan_committed_audit_events(limit: int = 300) -> int:
    init_edge_db()
    with _connect() as conn:
        cursor = int(_meta_get(conn, "audit_cursor", "0") or "0")

    copied = 0
    with SessionLocal() as db:
        rows = list(db.scalars(select(AuditLog).where(AuditLog.id > cursor).order_by(AuditLog.id).limit(limit)))
        for row in rows:
            mapped = AUDIT_EVENT_MAP.get(row.action)
            if mapped:
                details = _parse_details(row.details)
                session_ref: str | None = None
                payload: dict[str, Any] = {
                    "local_audit_id": row.id,
                    "actor_user_id": row.user_id,
                    "action": row.action,
                    "entity": row.entity,
                    "entity_id": row.entity_id,
                    "details": details,
                }
                if row.entity == "session" and row.entity_id:
                    session_ref = str(row.entity_id)
                    payload.update(_session_payload(db, row.entity_id))
                elif row.entity == "invoice" and row.entity_id:
                    session_ref, invoice_payload = _invoice_payload(db, row.entity_id)
                    payload.update(invoice_payload)
                elif row.entity == "station" and row.entity_id:
                    station = db.get(Station, row.entity_id)
                    payload.update({
                        "station_id": row.entity_id,
                        "station_code": station.code if station else None,
                    })
                enqueue_event(
                    mapped,
                    event_id=f"audit-{row.id}",
                    session_ref=session_ref,
                    occurred_at=row.created_at,
                    payload=payload,
                )
                copied += 1
            with _connect() as edge_conn:
                _meta_set(edge_conn, "audit_cursor", str(row.id))
                edge_conn.commit()
    return copied


def _credentials() -> tuple[str, str, str] | None:
    init_edge_db()
    with _connect() as conn:
        cloud_url = _meta_get(conn, "cloud_url")
        device_id = _meta_get(conn, "device_id")
        token_protected = _meta_get(conn, "device_token")
    if not cloud_url or not device_id or not token_protected:
        return None
    return cloud_url.rstrip("/"), device_id, _unprotect_secret(token_protected)


def activate(cloud_url: str, installation_code: str, timeout: float = 15.0) -> dict[str, Any]:
    cloud_url = cloud_url.strip().rstrip("/")
    if not cloud_url.startswith(("https://", "http://")):
        raise ValueError("Cloud URL must start with https:// or http://")
    response = httpx.post(
        cloud_url + "/api/edge/activate",
        json={
            "installation_code": installation_code.strip(),
            "device_name": machine_label(),
            "machine_fingerprint": machine_hash(),
            "app_version": EDGE_APP_VERSION,
        },
        timeout=timeout,
    )
    if not response.is_success:
        try:
            detail = response.json().get("detail") or response.text
        except Exception:
            detail = response.text
        raise RuntimeError(f"Cloud activation failed ({response.status_code}): {detail}")
    body = response.json()
    with _LOCK, _connect() as conn:
        _meta_set(conn, "cloud_url", cloud_url)
        _meta_set(conn, "device_id", str(body["device_id"]))
        _meta_set(conn, "device_token", _protect_secret(str(body["device_token"])))
        _meta_set(conn, "customer_code", str((body.get("customer") or {}).get("code") or ""))
        _meta_set(conn, "customer_name", str((body.get("customer") or {}).get("name") or ""))
        _meta_set(conn, "branch_name", str((body.get("branch") or {}).get("name") or ""))
        _meta_set(conn, "activated_at", _utc_iso())
        _meta_set(conn, "last_error", "")
        conn.commit()
    return status()


def _pending_rows(limit: int = EDGE_BATCH_SIZE) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT event_id,sequence,event_type,session_ref,occurred_at,payload_json "
            "FROM pending_events ORDER BY sequence LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "event_id": row["event_id"],
            "sequence": row["sequence"],
            "event_type": row["event_type"],
            "session_ref": row["session_ref"],
            "occurred_at": row["occurred_at"],
            "payload": json.loads(row["payload_json"]),
        }
        for row in rows
    ]


def sync_once() -> dict[str, Any]:
    scan_committed_audit_events()
    creds = _credentials()
    if creds is None:
        return {"online": False, "activated": False, "pending": pending_count(), "error": "EDGE_NOT_ACTIVATED"}
    cloud_url, device_id, token = creds
    headers = {"Authorization": f"Bearer {token}", "X-Device-ID": device_id}
    events = _pending_rows()
    try:
        if events:
            response = httpx.post(cloud_url + "/api/edge/events", headers=headers, json={"events": events}, timeout=10.0)
        else:
            response = httpx.post(
                cloud_url + "/api/edge/heartbeat",
                headers=headers,
                json={"app_version": EDGE_APP_VERSION},
                timeout=10.0,
            )
        if not response.is_success:
            try:
                detail = response.json().get("detail") or response.text
            except Exception:
                detail = response.text
            raise RuntimeError(f"Cloud HTTP {response.status_code}: {detail}")
        acknowledged: list[str] = []
        if events:
            body = response.json()
            acknowledged = list(dict.fromkeys((body.get("accepted") or []) + (body.get("duplicates") or [])))
            if acknowledged:
                marks = ",".join("?" for _ in acknowledged)
                with _connect() as conn:
                    conn.execute(f"DELETE FROM pending_events WHERE event_id IN ({marks})", acknowledged)
                    conn.commit()
        with _connect() as conn:
            _meta_set(conn, "last_sync_at", _utc_iso())
            _meta_set(conn, "last_error", "")
            conn.commit()
        return {
            "online": True,
            "activated": True,
            "sent": len(events),
            "acknowledged": len(acknowledged),
            "pending": pending_count(),
        }
    except Exception as exc:
        with _connect() as conn:
            _meta_set(conn, "last_error", str(exc)[:1000])
            conn.commit()
        return {"online": False, "activated": True, "pending": pending_count(), "error": str(exc)}


def pending_count() -> int:
    init_edge_db()
    with _connect() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM pending_events").fetchone()[0])


def status() -> dict[str, Any]:
    init_edge_db()
    with _connect() as conn:
        get = lambda key, default=None: _meta_get(conn, key, default)
        return {
            "activated": bool(get("device_id")),
            "cloud_url": get("cloud_url"),
            "device_id": get("device_id"),
            "customer_code": get("customer_code"),
            "customer_name": get("customer_name"),
            "branch_name": get("branch_name"),
            "activated_at": get("activated_at"),
            "last_sync_at": get("last_sync_at"),
            "last_error": get("last_error") or None,
            "pending_events": int(conn.execute("SELECT COUNT(*) FROM pending_events").fetchone()[0]),
            "audit_cursor": int(get("audit_cursor", "0") or "0"),
            "app_version": EDGE_APP_VERSION,
        }


def record_power_event(station_id: int, on: bool, result: dict[str, Any] | None = None, session_id: int | None = None) -> None:
    try:
        enqueue_event(
            "POWER_ON" if on else "POWER_OFF",
            session_ref=str(session_id) if session_id else None,
            payload={
                "station_id": station_id,
                "session_id": session_id,
                "automatic": True,
                "result": result or {},
            },
        )
    except Exception as exc:
        print(f"[EDGE] could not queue power event: {exc}")


def _loop() -> None:
    while not _SYNC_STOP.wait(EDGE_SYNC_INTERVAL_SECONDS):
        try:
            sync_once()
        except Exception as exc:
            print(f"[EDGE] sync loop error: {exc}")


def start_edge_runtime() -> None:
    global _SYNC_THREAD
    init_edge_db()
    try:
        scan_committed_audit_events()
    except Exception as exc:
        print(f"[EDGE] initial audit scan failed: {exc}")
    if _SYNC_THREAD and _SYNC_THREAD.is_alive():
        return
    _SYNC_STOP.clear()
    _SYNC_THREAD = threading.Thread(target=_loop, name="playzone-edge-sync", daemon=True)
    _SYNC_THREAD.start()
    print(f"[EDGE] runtime started; db={EDGE_DB_PATH}")


def stop_edge_runtime() -> None:
    global _SYNC_THREAD
    _SYNC_STOP.set()
    thread = _SYNC_THREAD
    _SYNC_THREAD = None
    if thread and thread.is_alive():
        thread.join(timeout=2.0)
