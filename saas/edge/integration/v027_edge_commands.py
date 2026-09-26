from __future__ import annotations

import json
import threading
from typing import Any

import httpx
from sqlalchemy import select

from .db import SessionLocal
from .edge_runtime import (
    EDGE_APP_VERSION,
    _connect,
    _credentials,
    _meta_set,
    _utc_iso,
    record_power_event,
)
from .models import PlaySession, Station, User
from .services import (
    audit,
    change_controller_count,
    extend_timed_session,
    pause_session,
    resume_session,
    session_snapshot,
)
from .voltra import set_power as voltra_set_power

_COMMAND_STOP = threading.Event()
_COMMAND_THREAD: threading.Thread | None = None
COMMAND_POLL_SECONDS = 3.0


def _init_command_table() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS processed_cloud_commands (
                command_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                result_json TEXT NOT NULL,
                error TEXT,
                processed_at TEXT NOT NULL,
                acknowledged_at TEXT
            );
            """
        )


def _reserve_command(command_id: str) -> bool:
    """Persist execution intent before touching PlayZone business state.

    This makes remote commands at-most-once across process crashes. If the
    process dies after reservation but before a terminal result is stored, the
    command is never replayed automatically; Cloud receives an explicit
    uncertain/failed result instead of risking a duplicate financial action.
    """
    _init_command_table()
    with _connect() as conn:
        try:
            conn.execute(
                "INSERT INTO processed_cloud_commands(command_id,status,result_json,error,processed_at) "
                "VALUES(?,?,?,?,?)",
                (command_id, "PROCESSING", "{}", None, _utc_iso()),
            )
            conn.commit()
            return True
        except Exception:
            return False


def _load_processed(command_id: str) -> dict[str, Any] | None:
    _init_command_table()
    with _connect() as conn:
        row = conn.execute(
            "SELECT command_id,status,result_json,error,processed_at,acknowledged_at "
            "FROM processed_cloud_commands WHERE command_id=?",
            (command_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["command_id"],
        "status": row["status"],
        "result": json.loads(row["result_json"] or "{}"),
        "error": row["error"],
        "processed_at": row["processed_at"],
        "acknowledged_at": row["acknowledged_at"],
    }


def _store_processed(command_id: str, status: str, result: dict[str, Any], error: str | None) -> None:
    _init_command_table()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO processed_cloud_commands(command_id,status,result_json,error,processed_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(command_id) DO UPDATE SET
                status=excluded.status,
                result_json=excluded.result_json,
                error=excluded.error,
                processed_at=excluded.processed_at
            """,
            (command_id, status, json.dumps(result or {}, separators=(",", ":")), error, _utc_iso()),
        )
        conn.commit()


def _mark_acknowledged(command_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE processed_cloud_commands SET acknowledged_at=? WHERE command_id=?",
            (_utc_iso(), command_id),
        )
        conn.commit()


def _root_actor(db) -> User:
    actor = db.scalar(
        select(User).where(User.role == "ROOT", User.is_active.is_(True)).order_by(User.id)
    )
    if actor is None:
        raise RuntimeError("No active ROOT user available for cloud command audit")
    return actor


def _session_from_ref(db, session_ref: str) -> PlaySession:
    try:
        session_id = int(session_ref)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Invalid session_ref") from exc
    session = db.get(PlaySession, session_id)
    if session is None:
        raise RuntimeError("Session not found")
    return session


def execute_command(command: dict[str, Any]) -> dict[str, Any]:
    command_id = str(command.get("id") or "")
    command_type = str(command.get("command_type") or "")
    payload = dict(command.get("payload") or {})
    if not command_id or not command_type:
        raise RuntimeError("Malformed cloud command")

    previous = _load_processed(command_id)
    if previous is not None:
        if previous["status"] == "PROCESSING":
            # A previous process reserved the command but did not persist a
            # terminal result. Never replay an operation such as EXTEND_SESSION.
            error = "COMMAND_EXECUTION_UNCERTAIN_AFTER_RESTART"
            _store_processed(command_id, "FAILED", {}, error)
            return {"id": command_id, "status": "FAILED", "result": {}, "error": error}
        return previous

    if not _reserve_command(command_id):
        previous = _load_processed(command_id)
        if previous is not None:
            return previous
        raise RuntimeError("Could not reserve cloud command")

    try:
        with SessionLocal() as db:
            actor = _root_actor(db)

            if command_type in {"POWER_ON", "POWER_OFF"}:
                station_id = int(payload["station_id"])
                station = db.get(Station, station_id)
                if station is None:
                    raise RuntimeError("Station not found")
                on = command_type == "POWER_ON"
                power = voltra_set_power(station.id, on)
                active = db.scalar(
                    select(PlaySession)
                    .where(
                        PlaySession.station_id == station.id,
                        PlaySession.status.in_(["RUNNING", "PAUSED", "EXPIRED"]),
                    )
                    .order_by(PlaySession.id.desc())
                )
                record_power_event(station.id, on, power, active.id if active else None)
                audit(
                    db,
                    actor,
                    "CLOUD_COMMAND_EXECUTED",
                    "station",
                    station.id,
                    f"command={command_id};type={command_type}",
                )
                db.commit()
                result = {"station_id": station.id, "power": power}

            else:
                session = _session_from_ref(db, str(payload.get("session_ref") or ""))
                if command_type == "EXTEND_SESSION":
                    was_expired = session.status == "EXPIRED"
                    session = extend_timed_session(db, session, actor, int(payload["seconds"]))
                    if was_expired:
                        station = db.get(Station, session.station_id)
                        if station is not None:
                            power = voltra_set_power(station.id, True)
                            record_power_event(station.id, True, power, session.id)
                    result = {"session": session_snapshot(session)}
                elif command_type == "CHANGE_CONTROLLERS":
                    session = change_controller_count(db, session, actor, int(payload["controller_count"]))
                    result = {"session": session_snapshot(session)}
                elif command_type == "PAUSE_SESSION":
                    session = pause_session(db, session, actor)
                    result = {"session": session_snapshot(session)}
                elif command_type == "RESUME_SESSION":
                    session = resume_session(db, session, actor)
                    result = {"session": session_snapshot(session)}
                else:
                    raise RuntimeError(f"Unsupported command: {command_type}")

                # Service methods commit their own business transaction. This audit is
                # deliberately a second committed record and is harmless on retry,
                # because processed_cloud_commands prevents re-execution.
                audit(
                    db,
                    actor,
                    "CLOUD_COMMAND_EXECUTED",
                    "session",
                    session.id,
                    f"command={command_id};type={command_type}",
                )
                db.commit()

        stored = {"id": command_id, "status": "SUCCESS", "result": result, "error": None}
        _store_processed(command_id, "SUCCESS", result, None)
        return stored
    except Exception as exc:
        error = str(exc)[:1000]
        _store_processed(command_id, "FAILED", {}, error)
        return {"id": command_id, "status": "FAILED", "result": {}, "error": error}


def _ack(cloud_url: str, device_id: str, token: str, processed: dict[str, Any]) -> bool:
    response = httpx.post(
        f"{cloud_url}/api/edge/commands/{processed['id']}/ack",
        headers={"Authorization": f"Bearer {token}", "X-Device-ID": device_id},
        json={
            "status": processed["status"],
            "result": processed.get("result") or {},
            "error": processed.get("error"),
        },
        timeout=10.0,
    )
    if not response.is_success:
        return False
    _mark_acknowledged(str(processed["id"]))
    return True


def poll_commands_once() -> dict[str, Any]:
    creds = _credentials()
    if creds is None:
        return {"online": False, "activated": False, "commands": 0, "error": "EDGE_NOT_ACTIVATED"}

    cloud_url, device_id, token = creds
    headers = {"Authorization": f"Bearer {token}", "X-Device-ID": device_id}
    try:
        response = httpx.get(f"{cloud_url}/api/edge/commands", headers=headers, timeout=10.0)
        if not response.is_success:
            raise RuntimeError(f"Cloud command HTTP {response.status_code}: {response.text[:500]}")
        commands = list((response.json() or {}).get("commands") or [])
        acked = 0
        for command in commands:
            processed = execute_command(command)
            if _ack(cloud_url, device_id, token, processed):
                acked += 1
        with _connect() as conn:
            _meta_set(conn, "last_command_poll_at", _utc_iso())
            _meta_set(conn, "last_command_error", "")
            _meta_set(conn, "edge_app_version", EDGE_APP_VERSION)
            conn.commit()
        return {"online": True, "activated": True, "commands": len(commands), "acked": acked}
    except Exception as exc:
        with _connect() as conn:
            _meta_set(conn, "last_command_error", str(exc)[:1000])
            conn.commit()
        return {"online": False, "activated": True, "commands": 0, "error": str(exc)}


def _loop() -> None:
    while not _COMMAND_STOP.wait(COMMAND_POLL_SECONDS):
        poll_commands_once()


def start_cloud_command_runtime() -> None:
    global _COMMAND_THREAD
    _init_command_table()
    if _COMMAND_THREAD and _COMMAND_THREAD.is_alive():
        return
    _COMMAND_STOP.clear()
    _COMMAND_THREAD = threading.Thread(
        target=_loop,
        name="playzone-edge-cloud-commands",
        daemon=True,
    )
    _COMMAND_THREAD.start()
    print("[EDGE] cloud command runtime started")


def stop_cloud_command_runtime() -> None:
    global _COMMAND_THREAD
    _COMMAND_STOP.set()
    thread = _COMMAND_THREAD
    _COMMAND_THREAD = None
    if thread and thread.is_alive():
        thread.join(timeout=2.0)
