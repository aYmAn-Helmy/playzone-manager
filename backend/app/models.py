from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default="STAFF")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship()


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(500))


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    hourly_rate_piasters: Mapped[int] = mapped_column(Integer, default=6000)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    sessions: Mapped[list["PlaySession"]] = relationship(back_populates="station")


class PlaySession(Base):
    __tablename__ = "play_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)
    opened_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    closed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="RUNNING", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    current_segment_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    hourly_rate_piasters: Mapped[int] = mapped_column(Integer)
    grace_seconds: Mapped[int] = mapped_column(Integer, default=300)
    first_segment: Mapped[bool] = mapped_column(Boolean, default=True)
    billable_seconds_accrued: Mapped[int] = mapped_column(Integer, default=0)

    # Controller-based pricing. Two controllers are the base rate, three are
    # 1.5x, and four are 2x. Weighted billable seconds preserve an exact split
    # when the controller count changes in the middle of the same session.
    controller_count: Mapped[int] = mapped_column(Integer, default=2)
    weighted_billable_seconds_x100: Mapped[int] = mapped_column(Integer, default=0)
    pricing_checkpoint_billable_seconds: Mapped[int] = mapped_column(Integer, default=0)
    # Billable seconds spent at each Multi tier. Two-controller time is the
    # remainder of total billable seconds. Persisting these buckets makes the
    # invoice and reports exact even when Multi starts/stops mid-session.
    multi_3_billable_seconds: Mapped[int] = mapped_column(Integer, default=0)
    multi_4_billable_seconds: Mapped[int] = mapped_column(Integer, default=0)

    # OPEN sessions run until a cashier ends them. TIMED sessions keep a
    # persisted active-time budget so pause/resume and application restarts do
    # not reset the countdown. When automatic expiry is enabled, an expired
    # session moves to EXPIRED and waits for the cashier to choose payment; the
    # invoice is never finalized with a guessed payment method.
    session_type: Mapped[str] = mapped_column(String(20), default="OPEN")
    timed_total_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timed_remaining_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timed_expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Best-effort Voltra telemetry from the START action. These fields are
    # operational only; billing/session validity never depends on them.
    power_start_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    power_start_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    power_start_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    station: Mapped[Station] = relationship(back_populates="sessions")
    events: Mapped[list["SessionEvent"]] = relationship(back_populates="session", order_by="SessionEvent.id")
    invoice: Mapped["Invoice | None"] = relationship(back_populates="session", uselist=False)
    items: Mapped[list["SessionItem"]] = relationship(back_populates="session")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    price_piasters: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SessionItem(Base):
    __tablename__ = "session_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("play_sessions.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    product_name: Mapped[str] = mapped_column(String(100))
    unit_price_piasters: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[PlaySession] = relationship(back_populates="items")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship()


class SessionEvent(Base):
    __tablename__ = "session_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("play_sessions.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[str] = mapped_column(String(20))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[PlaySession] = relationship(back_populates="events")


class Shift(Base):
    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    opening_cash_piasters: Mapped[int] = mapped_column(Integer)
    expected_cash_piasters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_cash_piasters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cash_difference_piasters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)

    employee: Mapped[User] = relationship(foreign_keys=[employee_id])
    closed_by: Mapped[User | None] = relationship(foreign_keys=[closed_by_user_id])
    movements: Mapped[list["CashMovement"]] = relationship(back_populates="shift")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="shift")


class CashMovement(Base):
    __tablename__ = "cash_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("shifts.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    movement_type: Mapped[str] = mapped_column(String(20))
    amount_piasters: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(300))
    approval_status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correction_of_id: Mapped[int | None] = mapped_column(ForeignKey("cash_movements.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    shift: Mapped[Shift] = relationship(back_populates="movements")
    user: Mapped[User] = relationship(foreign_keys=[user_id])
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_user_id])


class InvoiceSequence(Base):
    __tablename__ = "invoice_sequences"

    business_date: Mapped[str] = mapped_column(String(8), primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, default=0)


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("session_id", name="uq_invoice_session"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("play_sessions.id"), unique=True)
    issued_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"), nullable=True, index=True)
    play_seconds: Mapped[int] = mapped_column(Integer)
    amount_piasters: Mapped[int] = mapped_column(Integer)
    gameplay_amount_piasters: Mapped[int] = mapped_column(Integer, default=0)
    # Gameplay is split on the finalized invoice into the base 2-controller
    # charge plus the incremental Multi surcharge. The two parts always add
    # back to gameplay_amount_piasters.
    base_gameplay_amount_piasters: Mapped[int] = mapped_column(Integer, default=0)
    multi_amount_piasters: Mapped[int] = mapped_column(Integer, default=0)
    multi_3_seconds: Mapped[int] = mapped_column(Integer, default=0)
    multi_3_amount_piasters: Mapped[int] = mapped_column(Integer, default=0)
    multi_4_seconds: Mapped[int] = mapped_column(Integer, default=0)
    multi_4_amount_piasters: Mapped[int] = mapped_column(Integer, default=0)
    products_amount_piasters: Mapped[int] = mapped_column(Integer, default=0)
    discount_piasters: Mapped[int] = mapped_column(Integer, default=0)
    payment_method: Mapped[str] = mapped_column(String(20), default="CASH")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[PlaySession] = relationship(back_populates="invoice")
    shift: Mapped[Shift | None] = relationship(back_populates="invoices")
    issued_by: Mapped[User] = relationship(foreign_keys=[issued_by_user_id])
