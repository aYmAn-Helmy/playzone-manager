from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .security import utcnow


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    branches: Mapped[list["Branch"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")


class Branch(Base):
    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_branch_tenant_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(32), default="MAIN")
    name: Mapped[str] = mapped_column(String(160), default="Main Branch")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    tenant: Mapped[Tenant] = relationship(back_populates="branches")


class CloudUser(Base):
    __tablename__ = "cloud_users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "username", name="uq_user_tenant_username"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    username: Mapped[str] = mapped_column(String(100), index=True)
    display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(30), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserToken(Base):
    __tablename__ = "user_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("cloud_users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InstallationCode(Base):
    __tablename__ = "installation_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("cloud_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EdgeDevice(Base):
    __tablename__ = "edge_devices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "machine_fingerprint", name="uq_edge_tenant_machine"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), index=True)
    device_name: Mapped[str] = mapped_column(String(160))
    machine_fingerprint: Mapped[str] = mapped_column(String(200))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)
    app_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EdgeEvent(Base):
    __tablename__ = "edge_events"
    __table_args__ = (
        UniqueConstraint("edge_device_id", "event_id", name="uq_edge_event_id"),
        UniqueConstraint("edge_device_id", "sequence", name="uq_edge_event_sequence"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), index=True)
    edge_device_id: Mapped[str] = mapped_column(ForeignKey("edge_devices.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(String(80))
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    session_ref: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)



class CloudStation(Base):
    __tablename__ = "cloud_stations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "branch_id", "source_station_id", name="uq_cloud_station_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), index=True)
    source_station_id: Mapped[int] = mapped_column(Integer)
    code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    power_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CloudSession(Base):
    __tablename__ = "cloud_sessions"
    __table_args__ = (
        UniqueConstraint("edge_device_id", "local_session_ref", name="uq_cloud_session_edge_local"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), index=True)
    edge_device_id: Mapped[str] = mapped_column(ForeignKey("edge_devices.id", ondelete="CASCADE"), index=True)
    local_session_ref: Mapped[str] = mapped_column(String(100))
    source_station_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    station_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING", index=True)
    session_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    controller_count: Mapped[int] = mapped_column(Integer, default=2)
    hourly_rate_piasters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timed_total_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timed_remaining_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    multi_3_billable_seconds: Mapped[int] = mapped_column(Integer, default=0)
    multi_4_billable_seconds: Mapped[int] = mapped_column(Integer, default=0)
    last_event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CloudInvoice(Base):
    __tablename__ = "cloud_invoices"
    __table_args__ = (
        UniqueConstraint("edge_device_id", "local_invoice_id", name="uq_cloud_invoice_edge_local"),
        UniqueConstraint("tenant_id", "invoice_number", name="uq_cloud_invoice_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), index=True)
    edge_device_id: Mapped[str] = mapped_column(ForeignKey("edge_devices.id", ondelete="CASCADE"), index=True)
    local_invoice_id: Mapped[int] = mapped_column(Integer)
    invoice_number: Mapped[str] = mapped_column(String(80), index=True)
    local_session_ref: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    station_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    amount_piasters: Mapped[int] = mapped_column(Integer, default=0)
    gameplay_amount_piasters: Mapped[int] = mapped_column(Integer, default=0)
    base_gameplay_amount_piasters: Mapped[int] = mapped_column(Integer, default=0)
    multi_amount_piasters: Mapped[int] = mapped_column(Integer, default=0)
    multi_3_seconds: Mapped[int] = mapped_column(Integer, default=0)
    multi_3_amount_piasters: Mapped[int] = mapped_column(Integer, default=0)
    multi_4_seconds: Mapped[int] = mapped_column(Integer, default=0)
    multi_4_amount_piasters: Mapped[int] = mapped_column(Integer, default=0)
    products_amount_piasters: Mapped[int] = mapped_column(Integer, default=0)
    discount_piasters: Mapped[int] = mapped_column(Integer, default=0)
    payment_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
