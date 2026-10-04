from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CloudInvoice, CloudSession, CloudStation, EdgeDevice
from .security import utcnow


def _int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _upsert_station(db: Session, edge: EdgeDevice, payload: dict[str, Any], occurred_at: datetime) -> CloudStation | None:
    source_station_id = _int(payload.get("station_id"))
    if source_station_id is None:
        return None
    row = db.scalar(
        select(CloudStation).where(
            CloudStation.tenant_id == edge.tenant_id,
            CloudStation.branch_id == edge.branch_id,
            CloudStation.source_station_id == source_station_id,
        )
    )
    if row is None:
        row = CloudStation(
            tenant_id=edge.tenant_id,
            branch_id=edge.branch_id,
            source_station_id=source_station_id,
        )
        db.add(row)
    row.code = _text(payload.get("station_code")) or row.code
    row.last_event_at = occurred_at
    row.updated_at = utcnow()
    return row


def _upsert_session(
    db: Session,
    edge: EdgeDevice,
    session_ref: str,
    payload: dict[str, Any],
    occurred_at: datetime,
) -> CloudSession:
    row = db.scalar(
        select(CloudSession).where(
            CloudSession.edge_device_id == edge.id,
            CloudSession.local_session_ref == session_ref,
        )
    )
    if row is None:
        row = CloudSession(
            tenant_id=edge.tenant_id,
            branch_id=edge.branch_id,
            edge_device_id=edge.id,
            local_session_ref=session_ref,
        )
        db.add(row)
    row.source_station_id = _int(payload.get("station_id"), row.source_station_id)
    row.station_code = _text(payload.get("station_code")) or row.station_code
    row.session_type = _text(payload.get("session_type")) or row.session_type
    row.controller_count = _int(payload.get("controller_count"), row.controller_count) or 2
    row.hourly_rate_piasters = _int(payload.get("hourly_rate_piasters"), row.hourly_rate_piasters)
    row.started_at = _dt(payload.get("started_at")) or row.started_at
    row.ended_at = _dt(payload.get("ended_at")) or row.ended_at
    row.timed_total_seconds = _int(payload.get("timed_total_seconds"), row.timed_total_seconds)
    row.timed_remaining_seconds = _int(payload.get("timed_remaining_seconds"), row.timed_remaining_seconds)
    row.multi_3_billable_seconds = _int(payload.get("multi_3_billable_seconds"), row.multi_3_billable_seconds) or 0
    row.multi_4_billable_seconds = _int(payload.get("multi_4_billable_seconds"), row.multi_4_billable_seconds) or 0
    row.last_event_at = occurred_at
    row.updated_at = utcnow()
    return row


def apply_edge_event(
    db: Session,
    edge: EdgeDevice,
    *,
    event_type: str,
    session_ref: str | None,
    occurred_at: datetime,
    payload: dict[str, Any],
) -> None:
    """Apply one accepted Edge event to tenant-scoped cloud projections.

    The raw immutable EdgeEvent remains the audit/source record. These projection
    tables are only read models for mobile/web dashboards and can be rebuilt later.
    """
    payload = payload or {}
    station = _upsert_station(db, edge, payload, occurred_at)

    resolved_ref = session_ref or (_text(payload.get("session_id")) if payload.get("session_id") is not None else None)
    session = _upsert_session(db, edge, resolved_ref, payload, occurred_at) if resolved_ref else None

    if session is not None:
        details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
        if event_type == "SESSION_STARTED":
            session.status = "RUNNING"
            start_controllers = _int(details.get("controllers"))
            if start_controllers in (2, 3, 4):
                session.controller_count = start_controllers
        elif event_type == "CONTROLLERS_CHANGED":
            new_count = _int(details.get("to"), _int(payload.get("controller_count"), session.controller_count))
            if new_count in (2, 3, 4):
                session.controller_count = new_count
        elif event_type == "SESSION_PAUSED":
            session.status = "PAUSED"
        elif event_type == "SESSION_RESUMED":
            session.status = "RUNNING"
        elif event_type == "SESSION_EXPIRED":
            session.status = "EXPIRED"
            session.ended_at = occurred_at
            session.timed_remaining_seconds = 0
        elif event_type == "SESSION_EXTENDED":
            session.status = "RUNNING" if session.status == "EXPIRED" else session.status
            session.ended_at = None if session.status == "RUNNING" else session.ended_at
        elif event_type in {"SESSION_ENDED", "SESSION_INVOICED"}:
            session.status = "ENDED"
            session.ended_at = _dt(payload.get("ended_at")) or session.ended_at or occurred_at

    if station is not None and event_type in {"POWER_ON", "POWER_OFF"}:
        station.power_state = "ON" if event_type == "POWER_ON" else "OFF"

    if event_type == "SESSION_INVOICED":
        local_invoice_id = _int(payload.get("invoice_id"))
        invoice_number = _text(payload.get("invoice_number"))
        if local_invoice_id is None or invoice_number is None:
            return
        invoice = db.scalar(
            select(CloudInvoice).where(
                CloudInvoice.edge_device_id == edge.id,
                CloudInvoice.local_invoice_id == local_invoice_id,
            )
        )
        if invoice is None:
            invoice = CloudInvoice(
                tenant_id=edge.tenant_id,
                branch_id=edge.branch_id,
                edge_device_id=edge.id,
                local_invoice_id=local_invoice_id,
                invoice_number=invoice_number,
                created_at=_dt(payload.get("created_at")) or occurred_at,
            )
            db.add(invoice)
        invoice.invoice_number = invoice_number
        invoice.local_session_ref = resolved_ref
        invoice.station_code = _text(payload.get("station_code"))
        invoice.amount_piasters = _int(payload.get("amount_piasters"), 0) or 0
        invoice.gameplay_amount_piasters = _int(payload.get("gameplay_amount_piasters"), 0) or 0
        invoice.base_gameplay_amount_piasters = _int(payload.get("base_gameplay_amount_piasters"), 0) or 0
        invoice.multi_amount_piasters = _int(payload.get("multi_amount_piasters"), 0) or 0
        invoice.multi_3_seconds = _int(payload.get("multi_3_seconds"), 0) or 0
        invoice.multi_3_amount_piasters = _int(payload.get("multi_3_amount_piasters"), 0) or 0
        invoice.multi_4_seconds = _int(payload.get("multi_4_seconds"), 0) or 0
        invoice.multi_4_amount_piasters = _int(payload.get("multi_4_amount_piasters"), 0) or 0
        invoice.products_amount_piasters = _int(payload.get("products_amount_piasters"), 0) or 0
        invoice.discount_piasters = _int(payload.get("discount_piasters"), 0) or 0
        invoice.payment_method = _text(payload.get("payment_method"))
        invoice.created_at = _dt(payload.get("created_at")) or invoice.created_at
        invoice.updated_at = utcnow()
