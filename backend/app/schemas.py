from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .billing import normalize_utc


class LoginRequest(BaseModel):
    username: str
    password: str = ""


class LoginResponse(BaseModel):
    token: str
    role: str
    username: str
    must_change_password: bool = False


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=200)


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=8, max_length=200)
    role: str = "STAFF"
    display_name: str | None = Field(default=None, max_length=100)


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    password: str | None = Field(default=None, min_length=8, max_length=200)
    is_active: bool | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str | None
    role: str
    is_active: bool
    must_change_password: bool = False


class StationUpdate(BaseModel):
    hourly_rate_piasters: int | None = Field(default=None, gt=0)
    is_enabled: bool | None = None


class StationCountUpdate(BaseModel):
    count: int = Field(ge=1, le=100)



class TailscaleProvisionRequest(BaseModel):
    auth_key: str = Field(min_length=20, max_length=500)


class SettingUpdate(BaseModel):
    value: str = Field(pattern=r"^\d+$")


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    price_piasters: int = Field(ge=0)


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    price_piasters: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    price_piasters: int
    is_active: bool


class AddItem(BaseModel):
    product_id: int
    quantity: int = Field(ge=1, le=100)


class SessionStartRequest(BaseModel):
    session_type: str = Field(default="OPEN", pattern=r"^(OPEN|TIMED)$")
    duration_seconds: int | None = Field(default=None, ge=60, le=12 * 60 * 60)
    controller_count: int = 2

    @field_validator("controller_count")
    @classmethod
    def valid_controller_count(cls, value: int) -> int:
        value = int(value)
        if value not in (2, 3, 4):
            raise ValueError("Controller count must be 2, 3, or 4")
        return value


class ControllerCountUpdate(BaseModel):
    controller_count: int

    @field_validator("controller_count")
    @classmethod
    def valid_controller_count(cls, value: int) -> int:
        value = int(value)
        if value not in (2, 3, 4):
            raise ValueError("Controller count must be 2, 3, or 4")
        return value


class TimedSessionExtendRequest(BaseModel):
    seconds: int = Field(ge=60, le=12 * 60 * 60)


class PaymentRequest(BaseModel):
    payment_method: str = Field(pattern=r"^(CASH|INSTAPAY|VISA)$")
    discount_piasters: int = Field(default=0, ge=0)


class PaymentMethodsUpdate(BaseModel):
    enabled: list[str]

    @field_validator("enabled")
    @classmethod
    def valid_payment_methods(cls, value: list[str]) -> list[str]:
        allowed = {"CASH", "INSTAPAY", "VISA"}
        normalized = []
        for method in value:
            method = str(method).upper()
            if method not in allowed:
                raise ValueError("Unknown payment method")
            if method not in normalized:
                normalized.append(method)
        if not normalized:
            raise ValueError("At least one payment method must remain enabled")
        return normalized


class TimedSessionSettingsUpdate(BaseModel):
    presets_seconds: list[int]
    expiry_mode: str = Field(pattern=r"^(STOP_AND_WAIT_PAYMENT|NOTIFY_ONLY)$")

    @field_validator("presets_seconds")
    @classmethod
    def valid_presets(cls, value: list[int]) -> list[int]:
        cleaned = sorted({int(v) for v in value if 60 <= int(v) <= 12 * 60 * 60})
        if not cleaned:
            raise ValueError("At least one timed-session preset is required")
        if len(cleaned) > 12:
            raise ValueError("A maximum of 12 presets is allowed")
        return cleaned


class ShiftOpenRequest(BaseModel):
    opening_cash_piasters: int = Field(ge=0, le=100_000_000)


class AdminApprovalCredentials(BaseModel):
    admin_username: str = Field(min_length=1, max_length=80)
    admin_password: str = Field(min_length=1, max_length=300)


class ShiftCloseRequest(AdminApprovalCredentials):
    actual_cash_piasters: int = Field(ge=0, le=100_000_000)


class CashMovementCreate(BaseModel):
    movement_type: str = Field(pattern=r"^(CASH_IN|CASH_OUT)$")
    amount_piasters: int = Field(gt=0, le=100_000_000)
    reason: str = Field(min_length=2, max_length=300)


class CashMovementDecisionRequest(AdminApprovalCredentials):
    decision: str = Field(pattern=r"^(APPROVE|REJECT)$")


class SessionOut(BaseModel):
    id: int
    status: str
    snapshot_at: datetime | None = None
    started_at: datetime
    hourly_rate_piasters: int
    grace_seconds: int
    billable_seconds: int
    current_amount_piasters: int
    elapsed_seconds: int
    paused_seconds: int
    grace_used_seconds: int
    grace_remaining_seconds: int
    gameplay_amount_piasters: int
    base_gameplay_amount_piasters: int = 0
    multi_amount_piasters: int = 0
    multi_3_seconds: int = 0
    multi_3_amount_piasters: int = 0
    multi_4_seconds: int = 0
    multi_4_amount_piasters: int = 0
    products_amount_piasters: int
    discount_piasters: int
    total_piasters: int
    items: list[dict]
    power_start_status: str | None = None
    power_start_message: str | None = None
    power_start_checked_at: datetime | None = None
    session_type: str = "OPEN"
    timed_total_seconds: int | None = None
    timed_remaining_seconds: int | None = None
    timed_expired: bool = False
    timed_expired_at: datetime | None = None
    controller_count: int = 2
    controller_multiplier_x100: int = 100
    effective_hourly_rate_piasters: int = 0


class StationOut(BaseModel):
    id: int
    code: str
    name: str
    hourly_rate_piasters: int
    is_enabled: bool
    active_session: SessionOut | None = None
    power: dict | None = None
    power_alerts: list[dict] = Field(default_factory=list)


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    invoice_number: str
    session_id: int
    shift_id: int | None = None
    play_seconds: int
    amount_piasters: int
    gameplay_amount_piasters: int
    base_gameplay_amount_piasters: int
    multi_amount_piasters: int
    multi_3_seconds: int
    multi_3_amount_piasters: int
    multi_4_seconds: int
    multi_4_amount_piasters: int
    products_amount_piasters: int
    discount_piasters: int
    payment_method: str
    created_at: datetime
    power: dict | None = None

    @field_validator("created_at")
    @classmethod
    def utc_created_at(cls, value: datetime) -> datetime:
        return normalize_utc(value)


class ShiftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employee_id: int
    opened_at: datetime
    closed_at: datetime | None
    opening_cash_piasters: int
    expected_cash_piasters: int | None
    actual_cash_piasters: int | None
    cash_difference_piasters: int | None
    status: str

    @field_validator("opened_at", "closed_at")
    @classmethod
    def utc_datetime(cls, value: datetime | None):
        return normalize_utc(value) if value else value
