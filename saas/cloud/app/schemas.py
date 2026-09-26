from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)
    customer_code: str | None = Field(default=None, max_length=32)


class TenantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    owner_username: str = Field(min_length=2, max_length=100)
    owner_password: str = Field(min_length=8, max_length=200)
    owner_display_name: str | None = Field(default=None, max_length=160)


class InstallationCodeCreate(BaseModel):
    expires_hours: int = Field(default=24, ge=1, le=168)


class EdgeActivateRequest(BaseModel):
    installation_code: str = Field(min_length=8, max_length=100)
    device_name: str = Field(min_length=1, max_length=160)
    machine_fingerprint: str = Field(min_length=8, max_length=200)
    app_version: str | None = Field(default=None, max_length=40)


class EdgeHeartbeatRequest(BaseModel):
    app_version: str | None = Field(default=None, max_length=40)


class EdgeEventIn(BaseModel):
    event_id: str = Field(min_length=8, max_length=80)
    sequence: int = Field(ge=1)
    event_type: str = Field(min_length=2, max_length=80)
    session_ref: str | None = Field(default=None, max_length=100)
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class EdgeEventsRequest(BaseModel):
    events: list[EdgeEventIn] = Field(min_length=1, max_length=500)


class CustomerUserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=8, max_length=200)
    display_name: str | None = Field(default=None, max_length=160)
    role: str = Field(default="CASHIER", pattern="^(OWNER|MANAGER|CASHIER)$")


class UserPasswordUpdate(BaseModel):
    password: str = Field(min_length=8, max_length=200)


class UserStatusUpdate(BaseModel):
    is_active: bool


class TenantStatusUpdate(BaseModel):
    status: str = Field(pattern="^(ACTIVE|SUSPENDED)$")
