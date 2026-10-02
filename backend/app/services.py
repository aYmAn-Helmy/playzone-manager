from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .billing import amount_piasters, live_billable_seconds, normalize_utc, seconds_between, segment_billable_seconds, weighted_amount_piasters
from .models import (
    AuditLog,
    CashMovement,
    Invoice,
    InvoiceSequence,
    PlaySession,
    Product,
    SessionEvent,
    SessionItem,
    Shift,
    Station,
    SystemSetting,
    User,
)


CAIRO = ZoneInfo("Africa/Cairo")

CONTROLLER_MULTIPLIERS_X100 = {2: 100, 3: 150, 4: 200}


def controller_multiplier_x100(controller_count: int) -> int:
    try:
        return CONTROLLER_MULTIPLIERS_X100[int(controller_count)]
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(422, "Controller count must be 2, 3, or 4") from exc


def _live_weighted_billable_seconds_x100(session: PlaySession, at: datetime) -> int:
    billable = live_billable_seconds(session, at)
    checkpoint = int(getattr(session, "pricing_checkpoint_billable_seconds", 0) or 0)
    weighted = int(getattr(session, "weighted_billable_seconds_x100", 0) or 0)
    delta = max(0, billable - checkpoint)
    return weighted + delta * controller_multiplier_x100(getattr(session, "controller_count", 2) or 2)


def _live_multi_seconds(session: PlaySession, at: datetime) -> tuple[int, int]:
    """Return billable seconds spent at 3- and 4-controller tiers, including live time."""
    multi_3 = int(getattr(session, "multi_3_billable_seconds", 0) or 0)
    multi_4 = int(getattr(session, "multi_4_billable_seconds", 0) or 0)
    billable = live_billable_seconds(session, at)
    checkpoint = int(getattr(session, "pricing_checkpoint_billable_seconds", 0) or 0)
    delta = max(0, billable - checkpoint)
    count = int(getattr(session, "controller_count", 2) or 2)
    if count == 3:
        multi_3 += delta
    elif count == 4:
        multi_4 += delta
    return multi_3, multi_4


def _settle_controller_pricing(session: PlaySession, at: datetime) -> None:
    billable = live_billable_seconds(session, at)
    checkpoint = int(getattr(session, "pricing_checkpoint_billable_seconds", 0) or 0)
    delta = max(0, billable - checkpoint)
    if delta:
        count = int(getattr(session, "controller_count", 2) or 2)
        session.weighted_billable_seconds_x100 = int(getattr(session, "weighted_billable_seconds_x100", 0) or 0) + (
            delta * controller_multiplier_x100(count)
        )
        if count == 3:
            session.multi_3_billable_seconds = int(getattr(session, "multi_3_billable_seconds", 0) or 0) + delta
        elif count == 4:
            session.multi_4_billable_seconds = int(getattr(session, "multi_4_billable_seconds", 0) or 0) + delta
    session.pricing_checkpoint_billable_seconds = billable


def _gameplay_pricing_breakdown(session: PlaySession, at: datetime) -> dict[str, int]:
    """Split gameplay into base charge + exact Multi surcharges without rounding drift."""
    billable = live_billable_seconds(session, at)
    weighted_billable_x100 = _live_weighted_billable_seconds_x100(session, at)
    gameplay = weighted_amount_piasters(session.hourly_rate_piasters, weighted_billable_x100)
    base = amount_piasters(session.hourly_rate_piasters, billable)
    multi_3_seconds, multi_4_seconds = _live_multi_seconds(session, at)
    multi_total = max(0, gameplay - base)

    # Calculate each tier independently, then put any one-piaster rounding residual
    # into an active tier so base + M3 + M4 always equals gameplay exactly.
    multi_3_amount = weighted_amount_piasters(session.hourly_rate_piasters, multi_3_seconds * 50) if multi_3_seconds else 0
    multi_4_amount = weighted_amount_piasters(session.hourly_rate_piasters, multi_4_seconds * 100) if multi_4_seconds else 0
    residual = multi_total - multi_3_amount - multi_4_amount
    if residual:
        if multi_4_seconds:
            multi_4_amount += residual
        elif multi_3_seconds:
            multi_3_amount += residual
    return {
        "billable_seconds": billable,
        "gameplay_amount_piasters": gameplay,
        "base_gameplay_amount_piasters": base,
        "multi_amount_piasters": multi_total,
        "multi_3_seconds": multi_3_seconds,
        "multi_3_amount_piasters": multi_3_amount,
        "multi_4_seconds": multi_4_seconds,
        "multi_4_amount_piasters": multi_4_amount,
    }


def change_controller_count(
    db: Session, session: PlaySession, user: User, controller_count: int, at: datetime | None = None
) -> PlaySession:
    if session.status not in ("RUNNING", "PAUSED", "EXPIRED"):
        raise HTTPException(409, "Session has ended")
    controller_count = int(controller_count)
    controller_multiplier_x100(controller_count)
    at = at or now_utc()
    old_count = int(getattr(session, "controller_count", 2) or 2)
    if old_count == controller_count:
        return session
    _settle_controller_pricing(session, at)
    session.controller_count = controller_count
    db.add(SessionEvent(session_id=session.id, user_id=user.id, event_type="CONTROLLERS", occurred_at=at))
    audit(
        db, user, "SESSION_CONTROLLERS_CHANGED", "session", session.id,
        f"from={old_count};to={controller_count};multiplier_x100={controller_multiplier_x100(controller_count)}",
    )
    db.commit()
    db.refresh(session)
    return session


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get_setting_int(db: Session, key: str, default: int) -> int:
    row = db.get(SystemSetting, key)
    return int(row.value) if row else default


def audit(db: Session, user: User, action: str, entity: str, entity_id: int | None, details: str = "") -> None:
    db.add(AuditLog(user_id=user.id, action=action, entity=entity, entity_id=entity_id, details=details))


def active_shift_for_user(db: Session, user_id: int) -> Shift | None:
    return db.scalar(
        select(Shift)
        .where(Shift.employee_id == user_id, Shift.status == "OPEN")
        .order_by(Shift.id.desc())
    )


def require_cashier_shift(db: Session, user: User) -> Shift | None:
    """Require an open shift for staff when production shift enforcement is enabled.

    Existing Milestone 1/2 databases and isolated legacy tests that do not contain the
    `shift_required` setting retain backward compatibility. Normal application startup
    seeds the setting as enabled.
    """
    if user.role in ("ROOT", "ADMIN"):
        return active_shift_for_user(db, user.id)
    if get_setting_int(db, "shift_required", 0) != 1:
        return active_shift_for_user(db, user.id)
    shift = active_shift_for_user(db, user.id)
    if not shift:
        raise HTTPException(409, "An open cashier shift is required")
    return shift


def open_shift(db: Session, user: User, opening_cash_piasters: int, at: datetime | None = None) -> Shift:
    if active_shift_for_user(db, user.id):
        raise HTTPException(409, "User already has an open shift")
    other_open = db.scalar(select(Shift.id).where(Shift.status == "OPEN").limit(1))
    if other_open:
        raise HTTPException(409, "Another cashier shift is already open for this drawer")
    if user.role == "STAFF" and int(opening_cash_piasters) != 0:
        raise HTTPException(403, "Staff shifts must start at zero; drawer opening cash is admin-controlled")
    at = at or now_utc()
    shift = Shift(employee_id=user.id, opened_at=at, opening_cash_piasters=opening_cash_piasters, status="OPEN")
    db.add(shift)
    db.flush()
    audit(db, user, "SHIFT_OPENED", "shift", shift.id, f"opening_cash={opening_cash_piasters}")
    db.commit()
    db.refresh(shift)
    return shift


def _shift_financials(db: Session, shift_id: int) -> dict[str, int]:
    invoice_row = db.execute(
        select(
            func.count(Invoice.id),
            func.coalesce(func.sum(case((Invoice.payment_method == "CASH", Invoice.amount_piasters), else_=0)), 0),
            func.coalesce(func.sum(case((Invoice.payment_method == "VISA", Invoice.amount_piasters), else_=0)), 0),
            func.coalesce(func.sum(case((Invoice.payment_method == "INSTAPAY", Invoice.amount_piasters), else_=0)), 0),
        ).where(Invoice.shift_id == shift_id)
    ).one()
    movement_row = db.execute(
        select(
            func.coalesce(func.sum(case((
                (CashMovement.movement_type == "CASH_IN") & (CashMovement.approval_status == "APPROVED"),
                CashMovement.amount_piasters
            ), else_=0)), 0),
            func.coalesce(func.sum(case((
                (CashMovement.movement_type == "CASH_OUT") & (CashMovement.approval_status == "APPROVED"),
                CashMovement.amount_piasters
            ), else_=0)), 0),
            func.coalesce(func.sum(case((
                (CashMovement.movement_type == "CASH_IN") & (CashMovement.approval_status == "PENDING"),
                CashMovement.amount_piasters
            ), else_=0)), 0),
            func.coalesce(func.sum(case((
                (CashMovement.movement_type == "CASH_OUT") & (CashMovement.approval_status == "PENDING"),
                CashMovement.amount_piasters
            ), else_=0)), 0),
            func.coalesce(func.sum(case((CashMovement.approval_status == "PENDING", 1), else_=0)), 0),
        ).where(CashMovement.shift_id == shift_id)
    ).one()
    return {
        "invoice_count": int(invoice_row[0] or 0),
        "cash_sales": int(invoice_row[1] or 0),
        "visa_sales": int(invoice_row[2] or 0),
        "instapay_sales": int(invoice_row[3] or 0),
        "cash_in": int(movement_row[0] or 0),
        "cash_out": int(movement_row[1] or 0),
        "pending_cash_in": int(movement_row[2] or 0),
        "pending_cash_out": int(movement_row[3] or 0),
        "pending_movement_count": int(movement_row[4] or 0),
    }


def shift_expected_cash(db: Session, shift: Shift) -> int:
    totals = _shift_financials(db, shift.id)
    return shift.opening_cash_piasters + totals["cash_sales"] + totals["cash_in"] - totals["cash_out"]


def shift_snapshot(db: Session, shift: Shift) -> dict:
    totals = _shift_financials(db, shift.id)
    expected = shift.opening_cash_piasters + totals["cash_sales"] + totals["cash_in"] - totals["cash_out"]
    employee = db.get(User, shift.employee_id)
    employee_name = (employee.display_name or employee.username) if employee else f"User #{shift.employee_id}"
    username = employee.username if employee else str(shift.employee_id)
    return {
        "id": shift.id,
        "employee_id": shift.employee_id,
        "employee": employee_name,
        "username": username,
        "opened_at": normalize_utc(shift.opened_at),
        "closed_at": normalize_utc(shift.closed_at) if shift.closed_at else None,
        "opening_cash_piasters": shift.opening_cash_piasters,
        "cash_sales_piasters": totals["cash_sales"],
        "visa_sales_piasters": totals["visa_sales"],
        "instapay_sales_piasters": totals["instapay_sales"],
        "cash_in_piasters": totals["cash_in"],
        "cash_out_piasters": totals["cash_out"],
        "pending_cash_in_piasters": totals["pending_cash_in"],
        "pending_cash_out_piasters": totals["pending_cash_out"],
        "pending_movement_count": totals["pending_movement_count"],
        "expected_cash_piasters": expected if shift.status == "OPEN" else shift.expected_cash_piasters,
        "actual_cash_piasters": shift.actual_cash_piasters,
        "cash_difference_piasters": shift.cash_difference_piasters,
        "closed_by_user_id": shift.closed_by_user_id,
        "closed_by": ((shift.closed_by.display_name or shift.closed_by.username) if shift.closed_by else None),
        "status": shift.status,
        "invoice_count": totals["invoice_count"],
    }


def close_shift(db: Session, shift: Shift, user: User, actual_cash_piasters: int, at: datetime | None = None) -> Shift:
    if shift.status != "OPEN":
        raise HTTPException(409, "Shift is already closed")
    if user.role not in ("ROOT", "ADMIN"):
        raise HTTPException(403, "Admin approval is required to close a shift")
    if db.scalar(select(PlaySession.id).where(
        PlaySession.opened_by_user_id == shift.employee_id,
        PlaySession.status.in_(["RUNNING", "PAUSED", "EXPIRED"]),
    )):
        raise HTTPException(409, "Cannot close shift while this employee has active sessions")
    if db.scalar(select(CashMovement.id).where(
        CashMovement.shift_id == shift.id,
        CashMovement.approval_status == "PENDING",
    )):
        raise HTTPException(409, "Resolve all pending cash movements before closing the drawer")
    expected = shift_expected_cash(db, shift)
    at = at or now_utc()
    shift.expected_cash_piasters = expected
    shift.actual_cash_piasters = actual_cash_piasters
    shift.cash_difference_piasters = actual_cash_piasters - expected
    shift.closed_at = at
    shift.closed_by_user_id = user.id
    shift.status = "CLOSED"
    audit(
        db,
        user,
        "SHIFT_CLOSED",
        "shift",
        shift.id,
        f"system_cash={expected};actual={actual_cash_piasters};difference={shift.cash_difference_piasters}",
    )
    db.commit()
    db.refresh(shift)
    return shift


def add_cash_movement(db: Session, shift: Shift, user: User, movement_type: str, amount_piasters: int, reason: str) -> CashMovement:
    """Create an immutable pending cash request. It never changes drawer cash until an admin approves it."""
    if shift.status != "OPEN":
        raise HTTPException(409, "Shift is closed")
    if shift.employee_id != user.id and user.role not in ("ROOT", "ADMIN"):
        raise HTTPException(403, "Cannot modify another employee's shift")
    if user.role == "STAFF" and movement_type != "CASH_OUT":
        raise HTTPException(403, "Staff can only request cash-out expenses; cash-in is admin-controlled")
    pending_count = db.scalar(select(func.count(CashMovement.id)).where(
        CashMovement.shift_id == shift.id,
        CashMovement.approval_status == "PENDING",
    )) or 0
    if int(pending_count) >= 20:
        raise HTTPException(409, "Too many pending cash requests; admin review is required")
    movement = CashMovement(
        shift_id=shift.id,
        user_id=user.id,
        movement_type=movement_type,
        amount_piasters=amount_piasters,
        reason=reason,
        approval_status="PENDING",
    )
    db.add(movement)
    db.flush()
    audit(
        db,
        user,
        "CASH_MOVEMENT_REQUESTED",
        "cash_movement",
        movement.id,
        f"shift={shift.id};type={movement_type};amount={amount_piasters};reason={reason}",
    )
    db.commit()
    db.refresh(movement)
    return movement


def decide_cash_movement(
    db: Session,
    shift: Shift,
    movement: CashMovement,
    admin: User,
    decision: str,
    at: datetime | None = None,
) -> CashMovement:
    if admin.role not in ("ROOT", "ADMIN"):
        raise HTTPException(403, "Admin approval is required")
    if shift.status != "OPEN":
        raise HTTPException(409, "Shift is closed")
    if movement.shift_id != shift.id:
        raise HTTPException(409, "Movement does not belong to this shift")
    if movement.approval_status != "PENDING":
        raise HTTPException(409, "Cash movement was already decided")
    decision = str(decision).upper()
    if decision not in ("APPROVE", "REJECT"):
        raise HTTPException(422, "Unknown cash movement decision")
    if decision == "APPROVE" and movement.movement_type == "CASH_OUT":
        available = shift_expected_cash(db, shift)
        if movement.amount_piasters > available:
            raise HTTPException(409, "Cash out exceeds the drawer balance recorded by the system")
    movement.approval_status = "APPROVED" if decision == "APPROVE" else "REJECTED"
    movement.decided_by_user_id = admin.id
    movement.decided_at = at or now_utc()
    audit(
        db,
        admin,
        f"CASH_MOVEMENT_{movement.approval_status}",
        "cash_movement",
        movement.id,
        f"shift={shift.id};type={movement.movement_type};amount={movement.amount_piasters};requested_by={movement.user_id}",
    )
    db.commit()
    db.refresh(movement)
    return movement


def active_session_for_station(db: Session, station_id: int) -> PlaySession | None:
    return db.scalar(
        select(PlaySession)
        .where(PlaySession.station_id == station_id, PlaySession.status.in_(["RUNNING", "PAUSED", "EXPIRED"]))
        .order_by(PlaySession.id.desc())
    )


def start_session(
    db: Session,
    station: Station,
    user: User,
    at: datetime | None = None,
    *,
    session_type: str = "OPEN",
    duration_seconds: int | None = None,
    controller_count: int = 2,
) -> PlaySession:
    if not station.is_enabled:
        raise HTTPException(409, "Station is disabled")
    if active_session_for_station(db, station.id):
        raise HTTPException(409, "Station already has an active session")

    session_type = str(session_type or "OPEN").upper()
    if session_type not in ("OPEN", "TIMED"):
        raise HTTPException(422, "Unknown session type")
    if session_type == "TIMED":
        if duration_seconds is None or not 60 <= int(duration_seconds) <= 12 * 60 * 60:
            raise HTTPException(422, "Timed session duration must be between 1 minute and 12 hours")
        duration_seconds = int(duration_seconds)
    else:
        duration_seconds = None

    controller_count = int(controller_count)
    controller_multiplier_x100(controller_count)
    at = at or now_utc()
    grace = get_setting_int(db, "initial_grace_seconds", 300)
    session = PlaySession(
        station_id=station.id,
        opened_by_user_id=user.id,
        status="RUNNING",
        started_at=at,
        current_segment_started_at=at,
        hourly_rate_piasters=station.hourly_rate_piasters,
        grace_seconds=grace,
        first_segment=True,
        billable_seconds_accrued=0,
        controller_count=controller_count,
        weighted_billable_seconds_x100=0,
        pricing_checkpoint_billable_seconds=0,
        multi_3_billable_seconds=0,
        multi_4_billable_seconds=0,
        session_type=session_type,
        timed_total_seconds=duration_seconds,
        timed_remaining_seconds=duration_seconds,
    )
    db.add(session)
    db.flush()
    db.add(SessionEvent(session_id=session.id, user_id=user.id, event_type="START", occurred_at=at))
    audit(
        db,
        user,
        "SESSION_STARTED",
        "session",
        session.id,
        f"station={station.code};rate={session.hourly_rate_piasters};grace={grace};type={session_type};duration={duration_seconds or 0};controllers={controller_count}",
    )
    db.commit()
    db.refresh(session)
    return session


def pause_session(db: Session, session: PlaySession, user: User, at: datetime | None = None) -> PlaySession:
    if session.status != "RUNNING" or not session.current_segment_started_at:
        raise HTTPException(409, "Only a running session can be paused")
    at = at or now_utc()
    duration = seconds_between(session.current_segment_started_at, at)
    if session.session_type == "TIMED" and session.timed_remaining_seconds is not None:
        session.timed_remaining_seconds = max(0, session.timed_remaining_seconds - duration)
    session.billable_seconds_accrued += segment_billable_seconds(
        duration_seconds=duration,
        first_segment=session.first_segment,
        grace_seconds=session.grace_seconds,
    )
    session.status = "PAUSED"
    session.paused_at = at
    session.current_segment_started_at = None
    session.first_segment = False
    _settle_controller_pricing(session, at)
    db.add(SessionEvent(session_id=session.id, user_id=user.id, event_type="PAUSE", occurred_at=at))
    audit(db, user, "SESSION_PAUSED", "session", session.id)
    db.commit()
    db.refresh(session)
    return session


def resume_session(db: Session, session: PlaySession, user: User, at: datetime | None = None) -> PlaySession:
    if session.status != "PAUSED":
        raise HTTPException(409, "Only a paused session can be resumed")
    at = at or now_utc()
    session.status = "RUNNING"
    session.paused_at = None
    session.current_segment_started_at = at
    session.first_segment = False
    db.add(SessionEvent(session_id=session.id, user_id=user.id, event_type="RESUME", occurred_at=at))
    audit(db, user, "SESSION_RESUMED", "session", session.id)
    db.commit()
    db.refresh(session)
    return session


def timed_remaining_seconds(session: PlaySession, at: datetime | None = None) -> int | None:
    if session.session_type != "TIMED" or session.timed_remaining_seconds is None:
        return None
    remaining = int(session.timed_remaining_seconds)
    if session.status == "RUNNING" and session.current_segment_started_at is not None:
        remaining -= seconds_between(session.current_segment_started_at, at or now_utc())
    return max(0, remaining)


def expire_timed_session(db: Session, session: PlaySession, at: datetime | None = None) -> bool:
    """Freeze an elapsed TIMED session exactly at its deadline.

    This does not create an invoice. Payment is a cashier decision, so the session
    becomes EXPIRED and continues to occupy the station until finalized.
    """
    if session.session_type != "TIMED" or session.status != "RUNNING" or session.current_segment_started_at is None:
        return False
    if session.timed_remaining_seconds is None:
        return False

    now = at or now_utc()
    current_elapsed = seconds_between(session.current_segment_started_at, now)
    remaining = max(0, int(session.timed_remaining_seconds))
    if current_elapsed < remaining:
        return False

    from datetime import timedelta
    expires_at = normalize_utc(session.current_segment_started_at) + timedelta(seconds=remaining)
    session.billable_seconds_accrued += segment_billable_seconds(
        duration_seconds=remaining,
        first_segment=session.first_segment,
        grace_seconds=session.grace_seconds,
    )
    session.timed_remaining_seconds = 0
    session.timed_expired_at = expires_at
    session.ended_at = expires_at
    session.current_segment_started_at = None
    session.paused_at = None
    session.first_segment = False
    session.status = "EXPIRED"
    _settle_controller_pricing(session, expires_at)
    db.add(SessionEvent(
        session_id=session.id,
        user_id=session.opened_by_user_id,
        event_type="EXPIRE",
        occurred_at=expires_at,
    ))
    opener = db.get(User, session.opened_by_user_id)
    if opener is not None:
        audit(db, opener, "TIMED_SESSION_EXPIRED", "session", session.id, f"duration={session.timed_total_seconds or 0}")
    db.commit()
    db.refresh(session)
    return True


def extend_timed_session(
    db: Session, session: PlaySession, user: User, seconds: int, at: datetime | None = None
) -> PlaySession:
    if session.session_type != "TIMED":
        raise HTTPException(409, "Only timed sessions can be extended")
    if session.status not in ("RUNNING", "PAUSED", "EXPIRED"):
        raise HTTPException(409, "Session has ended")
    if not 60 <= int(seconds) <= 12 * 60 * 60:
        raise HTTPException(422, "Extension must be between 1 minute and 12 hours")

    at = at or now_utc()
    seconds = int(seconds)
    if session.status == "RUNNING":
        # The stored budget is relative to current_segment_started_at. If the
        # session is still before its deadline, extending that budget preserves
        # billing continuity. In NOTIFY_ONLY mode the timer may already be at
        # zero while the session keeps running; in that case first settle the
        # elapsed segment for billing, then grant the full extension from now.
        elapsed = seconds_between(session.current_segment_started_at, at) if session.current_segment_started_at else 0
        stored = max(0, int(session.timed_remaining_seconds or 0))
        if elapsed >= stored:
            _settle_controller_pricing(session, at)
            session.billable_seconds_accrued += segment_billable_seconds(
                duration_seconds=elapsed,
                first_segment=session.first_segment,
                grace_seconds=session.grace_seconds,
            )
            session.current_segment_started_at = at
            session.first_segment = False
            session.timed_remaining_seconds = seconds
        else:
            session.timed_remaining_seconds = stored + seconds
    elif session.status == "PAUSED":
        session.timed_remaining_seconds = max(0, int(session.timed_remaining_seconds or 0)) + seconds
    else:  # EXPIRED: reopen from now without changing the already-accrued bill.
        session.status = "RUNNING"
        session.ended_at = None
        session.timed_expired_at = None
        session.timed_remaining_seconds = seconds
        session.current_segment_started_at = at
        session.paused_at = None
        session.first_segment = False

    session.timed_total_seconds = int(session.timed_total_seconds or 0) + seconds
    db.add(SessionEvent(session_id=session.id, user_id=user.id, event_type="EXTEND", occurred_at=at))
    audit(db, user, "TIMED_SESSION_EXTENDED", "session", session.id, f"seconds={seconds}")
    db.commit()
    db.refresh(session)
    return session


def add_product(db: Session, session: PlaySession, product: Product, quantity: int, user: User) -> SessionItem:
    if session.status not in ("RUNNING", "PAUSED"):
        raise HTTPException(409, "Session has ended")
    if not product.is_active:
        raise HTTPException(409, "Product is disabled")
    item = SessionItem(session_id=session.id, product_id=product.id, product_name=product.name,
                       unit_price_piasters=product.price_piasters, quantity=quantity)
    db.add(item)
    audit(db, user, "PRODUCT_ADDED", "session", session.id, f"product={product.id};quantity={quantity};price={product.price_piasters}")
    db.commit()
    db.refresh(item)
    return item


def session_totals(session: PlaySession, now: datetime | None = None, discount_piasters: int = 0) -> dict:
    now = now or now_utc()
    pricing = _gameplay_pricing_breakdown(session, now)
    billable = pricing["billable_seconds"]
    gameplay = pricing["gameplay_amount_piasters"]
    products = sum(item.unit_price_piasters * item.quantity for item in session.items)
    if discount_piasters > gameplay + products:
        raise HTTPException(422, "Discount exceeds subtotal")
    elapsed = seconds_between(session.started_at, session.ended_at or now)
    events = session.events
    paused = 0
    pause_at = None
    first_segment_seconds = None
    for event in events:
        if event.event_type == "PAUSE":
            if first_segment_seconds is None:
                first_segment_seconds = seconds_between(session.started_at, event.occurred_at)
            pause_at = event.occurred_at
        elif event.event_type == "RESUME" and pause_at:
            paused += seconds_between(pause_at, event.occurred_at)
            pause_at = None
    if pause_at:
        paused += seconds_between(pause_at, now)
    if first_segment_seconds is None:
        first_segment_seconds = seconds_between(session.started_at, session.ended_at or now)
    grace_used = min(session.grace_seconds, first_segment_seconds)
    grace_remaining = max(0, session.grace_seconds - first_segment_seconds) if session.first_segment and session.status == "RUNNING" else 0
    timed_remaining = timed_remaining_seconds(session, now)
    return {
        "elapsed_seconds": elapsed,
        "paused_seconds": paused,
        "grace_used_seconds": grace_used,
        "grace_remaining_seconds": grace_remaining,
        "billable_seconds": billable,
        "gameplay_amount_piasters": gameplay,
        "base_gameplay_amount_piasters": pricing["base_gameplay_amount_piasters"],
        "multi_amount_piasters": pricing["multi_amount_piasters"],
        "multi_3_seconds": pricing["multi_3_seconds"],
        "multi_3_amount_piasters": pricing["multi_3_amount_piasters"],
        "multi_4_seconds": pricing["multi_4_seconds"],
        "multi_4_amount_piasters": pricing["multi_4_amount_piasters"],
        "products_amount_piasters": products,
        "discount_piasters": discount_piasters,
        "total_piasters": gameplay + products - discount_piasters,
        "session_type": session.session_type or "OPEN",
        "timed_total_seconds": session.timed_total_seconds,
        "timed_remaining_seconds": timed_remaining,
        "timed_expired": session.status == "EXPIRED" or (session.session_type == "TIMED" and timed_remaining == 0),
        "timed_expired_at": normalize_utc(session.timed_expired_at) if session.timed_expired_at else None,
        "controller_count": int(getattr(session, "controller_count", 2) or 2),
        "controller_multiplier_x100": controller_multiplier_x100(getattr(session, "controller_count", 2) or 2),
        "effective_hourly_rate_piasters": int(round(session.hourly_rate_piasters * controller_multiplier_x100(getattr(session, "controller_count", 2) or 2) / 100)),
        "items": [
            {
                "id": item.id,
                "product_name": item.product_name,
                "unit_price_piasters": item.unit_price_piasters,
                "quantity": item.quantity,
                "line_total_piasters": item.unit_price_piasters * item.quantity,
            }
            for item in session.items
        ],
    }


def next_invoice_number(db: Session, at: datetime) -> str:
    business_date = normalize_utc(at).astimezone(CAIRO).strftime("%Y%m%d")
    counter = db.get(InvoiceSequence, business_date)
    if counter is None:
        counter = InvoiceSequence(business_date=business_date, last_value=1)
        db.add(counter)
        value = 1
    else:
        counter.last_value += 1
        value = counter.last_value
    candidate = f"INV-{business_date}-{value:06d}"
    while db.scalar(select(Invoice.id).where(Invoice.invoice_number == candidate)) is not None:
        counter.last_value += 1
        value = counter.last_value
        candidate = f"INV-{business_date}-{value:06d}"
    db.flush()
    return candidate


def end_session(
    db: Session,
    session: PlaySession,
    user: User,
    at: datetime | None = None,
    payment_method: str = "CASH",
    discount_piasters: int = 0,
    shift: Shift | None = None,
) -> Invoice:
    if session.status not in ("RUNNING", "PAUSED", "EXPIRED"):
        raise HTTPException(409, "Session is already ended")
    if session.invoice:
        raise HTTPException(409, "Invoice already finalized")

    at = at or now_utc()
    session_totals(session, at, discount_piasters)
    _settle_controller_pricing(session, at)
    was_expired = session.status == "EXPIRED"
    if session.status == "RUNNING" and session.current_segment_started_at:
        duration = seconds_between(session.current_segment_started_at, at)
        if session.session_type == "TIMED" and session.timed_remaining_seconds is not None:
            session.timed_remaining_seconds = max(0, session.timed_remaining_seconds - duration)
        session.billable_seconds_accrued += segment_billable_seconds(
            duration_seconds=duration,
            first_segment=session.first_segment,
            grace_seconds=session.grace_seconds,
        )

    session.status = "ENDED"
    if not was_expired:
        session.ended_at = at
    session.current_segment_started_at = None
    session.paused_at = None
    session.closed_by_user_id = user.id
    session.first_segment = False

    totals = session_totals(session, at, discount_piasters)
    invoice = Invoice(
        invoice_number=next_invoice_number(db, at),
        session_id=session.id,
        issued_by_user_id=user.id,
        shift_id=shift.id if shift else None,
        play_seconds=session.billable_seconds_accrued,
        amount_piasters=totals["total_piasters"],
        gameplay_amount_piasters=totals["gameplay_amount_piasters"],
        base_gameplay_amount_piasters=totals["base_gameplay_amount_piasters"],
        multi_amount_piasters=totals["multi_amount_piasters"],
        multi_3_seconds=totals["multi_3_seconds"],
        multi_3_amount_piasters=totals["multi_3_amount_piasters"],
        multi_4_seconds=totals["multi_4_seconds"],
        multi_4_amount_piasters=totals["multi_4_amount_piasters"],
        products_amount_piasters=totals["products_amount_piasters"],
        discount_piasters=discount_piasters,
        payment_method=payment_method,
        created_at=at,
    )
    db.add(SessionEvent(session_id=session.id, user_id=user.id, event_type="END", occurred_at=at))
    db.add(invoice)
    db.flush()
    audit(db, user, "SESSION_ENDED", "session", session.id)
    audit(db, user, "INVOICE_FINALIZED", "invoice", invoice.id, f"session={session.id};total={invoice.amount_piasters};method={payment_method};shift={invoice.shift_id}")
    db.commit()
    db.refresh(invoice)
    return invoice


def session_snapshot(session: PlaySession, now: datetime | None = None, discount_piasters: int = 0) -> dict:
    now = now or now_utc()
    totals = session_totals(session, now, discount_piasters)
    return {
        "id": session.id,
        "status": session.status,
        "snapshot_at": normalize_utc(now),
        "started_at": normalize_utc(session.started_at),
        "hourly_rate_piasters": session.hourly_rate_piasters,
        "grace_seconds": session.grace_seconds,
        "billable_seconds": totals["billable_seconds"],
        "current_amount_piasters": totals["gameplay_amount_piasters"],
        "power_start_status": getattr(session, "power_start_status", None),
        "power_start_message": getattr(session, "power_start_message", None),
        "power_start_checked_at": normalize_utc(session.power_start_checked_at) if getattr(session, "power_start_checked_at", None) else None,
        **totals,
    }
