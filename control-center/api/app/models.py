from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EnrollmentCode(Base):
    __tablename__ = "enrollment_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(160), default="")
    site_name: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    installation_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    customer_name: Mapped[str] = mapped_column(String(160), default="")
    site_name: Mapped[str] = mapped_column(String(160), default="")
    hostname: Mapped[str] = mapped_column(String(160), default="")
    app_version: Mapped[str] = mapped_column(String(40), default="")
    os_version: Mapped[str] = mapped_column(String(160), default="")

    tailscale_ipv4: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tailscale_dns_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    remote_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    tailscale_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    serve_active: Mapped[bool] = mapped_column(Boolean, default=False)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
