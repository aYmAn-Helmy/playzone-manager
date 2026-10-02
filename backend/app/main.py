from __future__ import annotations

import sqlite3
import os

import httpx
import secrets
import threading
import time as time_module
from datetime import date as date_type, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from .activation import (
    ACTIVATION_AT_KEY,
    ACTIVATION_BY_KEY,
    ACTIVATION_HASH_KEY,
    ACTIVATION_LABEL_KEY,
    PASSWORDLESS_PRIVILEGED_KEY,
    activation_status,
    is_activated,
    machine_hash,
    machine_label,
    passwordless_privileged_enabled,
    set_setting as set_activation_setting,
)
from .billing import normalize_utc
from .db import BACKUP_DIR, Base, SessionLocal, engine, get_db, migrate_existing_database
from .embedded_voltra import start_embedded_voltra, stop_embedded_voltra
from voltra_local.dashboard import DASHBOARD as VOLTRA_DASHBOARD_HTML
from .models import AuditLog, AuthToken, CashMovement, DrawerSettlement, Invoice, PlaySession, Product, Shift, ShiftHandoff, Station, SystemSetting, User
from .schemas import (
    AddItem,
    CashMovementCreate,
    CashMovementDecisionRequest,
    ControllerCountUpdate,
    InvoiceOut,
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    PaymentRequest,
    PaymentMethodsUpdate,
    SessionStartRequest,
    TimedSessionExtendRequest,
    TimedSessionSettingsUpdate,
    TailscaleProvisionRequest,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    SettingUpdate,
    ShiftCloseRequest,
    ShiftHandoffRequest,
    ShiftOpenRequest,
    StationOut,
    StationUpdate,
    StationCountUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)
from .security import hash_password, needs_password_rehash, new_token, token_expiry, token_hash, verify_password
from .services import (
    active_session_for_station,
    active_drawer_shift,
    active_shift_for_user,
    add_cash_movement,
    decide_cash_movement,
    add_product,
    audit,
    close_shift,
    change_controller_count,
    end_session,
    expire_timed_session,
    extend_timed_session,
    handoff_shift,
    open_shift,
    pause_session,
    require_cashier_shift,
    resume_session,
    session_snapshot,
    session_totals,
    shift_snapshot,
    start_session,
)
from .voltra import (
    VoltraError,
    power_status as voltra_power_status,
    power_statuses as voltra_power_statuses,
    set_power as voltra_set_power,
    sync_stations as voltra_sync_stations,
)
from .tailscale_support import (
    TailscaleSupportError,
    disable_remote_access as tailscale_disable_remote_access,
    enable_remote_access as tailscale_enable_remote_access,
    get_status as tailscale_status,
    provision as tailscale_provision,
    reconnect as tailscale_reconnect,
)

CAIRO = ZoneInfo("Africa/Cairo")

_AUTH_GUARD_LOCK = threading.Lock()
_CASH_DRAWER_LOCK = threading.RLock()
_AUTH_FAILURES: dict[str, list[float]] = {}
_AUTH_BLOCKED_UNTIL: dict[str, float] = {}
_AUTH_WINDOW_SECONDS = 120.0
_AUTH_MAX_FAILURES = 8
_AUTH_BLOCK_SECONDS = 300.0


def _check_auth_rate_limit(key: str) -> None:
    now = time_module.monotonic()
    with _AUTH_GUARD_LOCK:
        blocked_until = _AUTH_BLOCKED_UNTIL.get(key, 0.0)
        if blocked_until > now:
            retry = max(1, int(blocked_until - now))
            raise HTTPException(429, f"Too many failed authentication attempts; retry in {retry} seconds")
        recent = [t for t in _AUTH_FAILURES.get(key, []) if now - t <= _AUTH_WINDOW_SECONDS]
        if recent:
            _AUTH_FAILURES[key] = recent
        else:
            _AUTH_FAILURES.pop(key, None)


def _record_auth_failure(key: str) -> None:
    now = time_module.monotonic()
    with _AUTH_GUARD_LOCK:
        recent = [t for t in _AUTH_FAILURES.get(key, []) if now - t <= _AUTH_WINDOW_SECONDS]
        recent.append(now)
        _AUTH_FAILURES[key] = recent
        if len(recent) >= _AUTH_MAX_FAILURES:
            _AUTH_BLOCKED_UNTIL[key] = now + _AUTH_BLOCK_SECONDS
            _AUTH_FAILURES.pop(key, None)


def _clear_auth_failures(key: str) -> None:
    with _AUTH_GUARD_LOCK:
        _AUTH_FAILURES.pop(key, None)
        _AUTH_BLOCKED_UNTIL.pop(key, None)


# ROOT-controlled customer UI profile. These switches only change what is
# presented in the client UI; backend permissions and financial rules stay
# unchanged so hiding a control can never weaken security or corrupt billing.
UI_CONFIG_DEFAULTS: dict[str, bool] = {
    # Station cards
    "show_pause_button": True,
    "show_add_order_button": True,
    "show_power_watts": True,
    "show_power_state": True,
    "show_power_alerts": True,
    "show_station_details": True,
    "show_station_total": True,
    "show_grace_banner": True,
    # Home dashboard
    "show_dashboard_stats": True,
    "show_payment_stats": True,
    "show_power_alert_summary": True,
    "show_recent_invoices": True,
    "show_system_status": True,
    # Sidebar modules. Home, Stations, Settings and this customization page are
    # intentionally not hideable, so ROOT can always recover the UI profile.
    "show_nav_sessions": True,
    "show_nav_invoices": True,
    "show_nav_products": True,
    "show_nav_reports": True,
    "show_nav_users": True,
    "show_nav_voltra": True,
}

app = FastAPI(title="PlayZone Manager API", version="0.34.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def seed_data() -> None:
    Base.metadata.create_all(engine)
    migrate_existing_database()
    with SessionLocal() as db:
        defaults = {
            "initial_grace_seconds": "300",
            "default_hourly_rate_piasters": "6000",
            "shift_required": "1",
            # Start-session power automation is best-effort: billing/session creation
            # never depends on Voltra being online or mapped.
            "voltra_auto_power_on_start": "1",
            # The mapped Voltra outlet powers the TV/display only (never the PS4).
            # Ending/finalizing a session therefore turns that display outlet OFF
            # on a best-effort basis without affecting billing finalization.
            "voltra_auto_power_off_end": "1",
            # Operational screen monitoring. Watts below this value are treated as
            # standby/off when the relay is still ON. Values are deliberately kept
            # as system settings so production can tune them per TV fleet later.
            "voltra_screen_on_watts_threshold": "5",
            "voltra_active_screen_alert_seconds": "8",
            "voltra_idle_screen_alert_seconds": "10",
            # Timed-session presets are active-play time. Pause freezes the
            # countdown. STOP_AND_WAIT_PAYMENT freezes billing at zero and keeps
            # the station occupied until the cashier explicitly chooses payment.
            "timed_session_presets_seconds": "600,1200,1800,3600,7200,10800",
            "timed_session_expiry_mode": "STOP_AND_WAIT_PAYMENT",
            # ROOT can tailor payment methods per customer. The cashier UI and
            # backend validation both use these switches; this is not UI-only.
            "payment_cash_enabled": "1",
            "payment_instapay_enabled": "1",
            "payment_visa_enabled": "1",
            **{f"ui_{key}": "1" if value else "0" for key, value in UI_CONFIG_DEFAULTS.items()},
            # Production-safe default. Remote Support must never expose a
            # passwordless privileged account. The installer provisions ROOT.
            "development_passwordless_privileged": "0",
            "root_password_initialized": "0",
        }
        for key, value in defaults.items():
            if not db.get(SystemSetting, key):
                db.add(SystemSetting(key=key, value=value))
        db.flush()
        if db.scalar(select(Station).limit(1)) is None:
            for i in range(1, 7):
                db.add(Station(code=f"PS4-{i:02d}", name=f"PS4-{i:02d}", hourly_rate_piasters=6000))

        # ROOT exists specifically for local machine activation and remote support.
        # v0.31 never permits ROOT passwordless login; the installer sets its password.
        for username, display_name, role in (("root", "System Root", "ROOT"), ("admin", "Administrator", "ADMIN")):
            user = db.scalar(select(User).where(User.username == username))
            if user is None:
                user = User(
                    username=username,
                    display_name=display_name,
                    password_hash=hash_password(secrets.token_urlsafe(32)),
                    role=role,
                    must_change_password=True,
                )
                db.add(user)
            elif role == "ADMIN" and passwordless_privileged_enabled(db):
                user.must_change_password = False
        db.commit()


@app.on_event("startup")
def on_startup():
    seed_data()
    start_embedded_voltra()
    start_timed_session_monitor()


@app.on_event("shutdown")
def on_shutdown():
    stop_timed_session_monitor()
    stop_embedded_voltra()


@app.get("/api/health")
def health():
    return {"ok": True, "time": datetime.now(timezone.utc)}


def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    raw = authorization.split(" ", 1)[1]
    row = db.scalar(
        select(AuthToken)
        .where(AuthToken.token_hash == token_hash(raw))
        .options(joinedload(AuthToken.user))
    )
    now = datetime.now(timezone.utc)
    if not row:
        raise HTTPException(401, "Invalid token")
    expires = normalize_utc(row.expires_at)
    if expires <= now or not row.user.is_active:
        raise HTTPException(401, "Expired or disabled token")
    return row.user


def ready_user(user: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
    # Authentication is on every polling/action request. Read the two readiness
    # settings in one indexed query instead of two separate PK lookups.
    rows = db.scalars(
        select(SystemSetting).where(
            SystemSetting.key.in_([PASSWORDLESS_PRIVILEGED_KEY, ACTIVATION_HASH_KEY])
        )
    ).all()
    settings = {row.key: row.value for row in rows}
    privileged_passwordless = (
        user.role == "ADMIN" and settings.get(PASSWORDLESS_PRIVILEGED_KEY) == "1"
    )
    if user.must_change_password and not privileged_passwordless:
        raise HTTPException(403, "PASSWORD_CHANGE_REQUIRED")
    if settings.get(ACTIVATION_HASH_KEY) != machine_hash():
        raise HTTPException(403, "PROGRAM_NOT_ACTIVATED")
    return user


def admin_user(user: User = Depends(ready_user)) -> User:
    if user.role not in ("ROOT", "ADMIN"):
        raise HTTPException(403, "Admin role required")
    return user


def root_user(user: User = Depends(current_user)) -> User:
    if user.role != "ROOT":
        raise HTTPException(403, "Root role required")
    return user


def root_ready_user(user: User = Depends(ready_user)) -> User:
    if user.role != "ROOT":
        raise HTTPException(403, "Root role required")
    return user


def _admin_password_approval(
    db: Session,
    *,
    admin_username: str,
    admin_password: str,
    requested_by: User,
    purpose: str,
) -> User:
    """Re-authenticate an active ADMIN/ROOT for a sensitive cash-drawer action."""
    username = str(admin_username or "").strip()
    auth_keys = [
        f"approval:{requested_by.id}:{username.lower()}",
        f"approval-admin:{username.lower()}",
    ]
    for auth_key in auth_keys:
        _check_auth_rate_limit(auth_key)
    admin = db.scalar(select(User).where(User.username == username))
    valid = bool(
        admin
        and admin.is_active
        and admin.role in ("ROOT", "ADMIN")
        and not admin.must_change_password
        and verify_password(admin_password, admin.password_hash)
    )
    if not valid:
        for auth_key in auth_keys:
            _record_auth_failure(auth_key)
        audit(
            db,
            requested_by,
            "ADMIN_APPROVAL_FAILED",
            "cash_drawer",
            None,
            f"purpose={purpose};requested_admin={username[:80]}",
        )
        db.commit()
        raise HTTPException(403, "Invalid admin approval credentials")
    for auth_key in auth_keys:
        _clear_auth_failures(auth_key)
    audit(
        db,
        admin,
        "ADMIN_APPROVAL_GRANTED",
        "cash_drawer",
        None,
        f"purpose={purpose};requested_by={requested_by.username}",
    )
    db.flush()
    return admin


@app.get("/api/root/tailscale/status")
def api_tailscale_status(_: User = Depends(root_ready_user)):
    return tailscale_status()


@app.post("/api/root/tailscale/provision")
def api_tailscale_provision(payload: TailscaleProvisionRequest, actor: User = Depends(root_ready_user), db: Session = Depends(get_db)):
    try:
        status = tailscale_provision(payload.auth_key)
    except TailscaleSupportError as exc:
        audit(db, actor, "TAILSCALE_PROVISION_FAILED", "system", None, "Auth Key was not stored; provisioning failed")
        db.commit()
        raise HTTPException(409, str(exc)) from exc
    audit(db, actor, "TAILSCALE_PROVISIONED", "system", None, f"ip={status.get('ipv4') or '-'} state={status.get('state') or '-'};auth_key=NOT_STORED")
    db.commit()
    return status


@app.post("/api/root/tailscale/reconnect")
def api_tailscale_reconnect(actor: User = Depends(root_ready_user), db: Session = Depends(get_db)):
    try:
        status = tailscale_reconnect()
    except TailscaleSupportError as exc:
        raise HTTPException(409, str(exc)) from exc
    audit(db, actor, "TAILSCALE_RECONNECT", "system", None, f"ip={status.get('ipv4') or '-'} state={status.get('state') or '-'}")
    db.commit()
    return status


@app.post("/api/root/tailscale/enable")
def api_tailscale_enable(actor: User = Depends(root_ready_user), db: Session = Depends(get_db)):
    try:
        status = tailscale_enable_remote_access()
    except TailscaleSupportError as exc:
        audit(db, actor, "TAILSCALE_SERVE_ENABLE_FAILED", "system", None, str(exc)[:500])
        db.commit()
        raise HTTPException(409, str(exc)) from exc
    audit(db, actor, "TAILSCALE_SERVE_ENABLED", "system", None, f"url={status.get('remote_url') or '-'}")
    db.commit()
    return status


@app.post("/api/root/tailscale/disable")
def api_tailscale_disable(actor: User = Depends(root_ready_user), db: Session = Depends(get_db)):
    try:
        status = tailscale_disable_remote_access()
    except TailscaleSupportError as exc:
        audit(db, actor, "TAILSCALE_SERVE_DISABLE_FAILED", "system", None, str(exc)[:500])
        db.commit()
        raise HTTPException(409, str(exc)) from exc
    audit(db, actor, "TAILSCALE_SERVE_DISABLED", "system", None)
    db.commit()
    return status


@app.get("/api/activation/status")
def api_activation_status(db: Session = Depends(get_db)):
    return activation_status(db)


@app.post("/api/activation/activate")
def api_activate(actor: User = Depends(root_user), db: Session = Depends(get_db)):
    from datetime import datetime, timezone
    set_activation_setting(db, ACTIVATION_HASH_KEY, machine_hash())
    set_activation_setting(db, ACTIVATION_LABEL_KEY, machine_label())
    set_activation_setting(db, ACTIVATION_AT_KEY, datetime.now(timezone.utc).isoformat())
    set_activation_setting(db, ACTIVATION_BY_KEY, actor.username)
    audit(db, actor, "PROGRAM_ACTIVATED", "system", None, f"machine={activation_status(db)['machine_id']}")
    db.commit()
    return activation_status(db)


@app.post("/api/activation/deactivate")
def api_deactivate(actor: User = Depends(root_user), db: Session = Depends(get_db)):
    for key in (ACTIVATION_HASH_KEY, ACTIVATION_LABEL_KEY, ACTIVATION_AT_KEY, ACTIVATION_BY_KEY):
        row = db.get(SystemSetting, key)
        if row:
            db.delete(row)
    audit(db, actor, "PROGRAM_DEACTIVATED", "system", None)
    db.commit()
    return activation_status(db)


@app.post("/api/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    auth_key = f"login:{str(payload.username).strip().lower()}"
    _check_auth_rate_limit(auth_key)
    user = db.scalar(select(User).where(User.username == payload.username))
    if not user or not user.is_active:
        _record_auth_failure(auth_key)
        raise HTTPException(401, "Invalid credentials")
    if not is_activated(db) and user.role != "ROOT":
        raise HTTPException(403, "PROGRAM_NOT_ACTIVATED")

    privileged_passwordless = user.role == "ADMIN" and passwordless_privileged_enabled(db)
    if not privileged_passwordless and not verify_password(payload.password, user.password_hash):
        _record_auth_failure(auth_key)
        raise HTTPException(401, "Invalid credentials")
    _clear_auth_failures(auth_key)
    if not privileged_passwordless and needs_password_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    raw = new_token()
    db.add(AuthToken(token_hash=token_hash(raw), user_id=user.id, expires_at=token_expiry()))
    audit(db, user, "LOGIN", "user", user.id)
    db.commit()
    return LoginResponse(
        token=raw,
        role=user.role,
        username=user.username,
        must_change_password=False if privileged_passwordless else user.must_change_password,
    )


@app.get("/api/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    payload = UserOut.model_validate(user).model_dump()
    if user.role == "ADMIN" and passwordless_privileged_enabled(db):
        payload["must_change_password"] = False
    return payload


@app.post("/api/auth/change-password", response_model=LoginResponse)
def change_password(payload: PasswordChangeRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    privileged_passwordless = user.role == "ADMIN" and passwordless_privileged_enabled(db)
    if not privileged_passwordless and not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(401, "Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(422, "New password must be different")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    for token in list(db.scalars(select(AuthToken).where(AuthToken.user_id == user.id))):
        db.delete(token)
    raw = new_token()
    db.add(AuthToken(token_hash=token_hash(raw), user_id=user.id, expires_at=token_expiry()))
    audit(db, user, "PASSWORD_CHANGED", "user", user.id)
    db.commit()
    return LoginResponse(token=raw, role=user.role, username=user.username, must_change_password=False)


@app.post("/api/auth/logout")
def logout(authorization: str = Header(), user: User = Depends(current_user), db: Session = Depends(get_db)):
    raw = authorization.split(" ", 1)[1]
    token = db.scalar(select(AuthToken).where(AuthToken.token_hash == token_hash(raw)))
    if token:
        db.delete(token)
    audit(db, user, "LOGOUT", "user", user.id)
    db.commit()
    return {"ok": True}


@app.get("/api/users", response_model=list[UserOut])
def list_users(actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    query = select(User).order_by(User.username)
    if actor.role != "ROOT":
        query = query.where(User.role != "ROOT")
    return list(db.scalars(query).all())


@app.post("/api/users", response_model=UserOut)
def create_user(payload: UserCreate, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    role = payload.role.upper()
    if role != "STAFF":
        raise HTTPException(422, "Only staff accounts can be created here")
    if db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(409, "Username already exists")
    user = User(username=payload.username, display_name=payload.display_name or payload.username,
                password_hash=hash_password(payload.password), role=role)
    db.add(user)
    db.flush()
    audit(db, actor, "EMPLOYEE_CREATED", "user", user.id, f"username={user.username};role={role}")
    db.commit()
    db.refresh(user)
    return user


@app.patch("/api/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if user.role == "ROOT" and actor.role != "ROOT":
        raise HTTPException(403, "Root account can only be modified by Root")
    changes = []
    if payload.display_name is not None:
        changes.append(f"display_name:{user.display_name}->{payload.display_name}")
        user.display_name = payload.display_name
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
        privileged_passwordless = user.role == "ADMIN" and passwordless_privileged_enabled(db)
        user.must_change_password = False if privileged_passwordless else True
        changes.append("password reset;must_change_password=false" if privileged_passwordless else "password reset;must_change_password=true")
        for token in list(db.scalars(select(AuthToken).where(AuthToken.user_id == user.id))):
            db.delete(token)
    if payload.is_active is not None:
        if user.id == actor.id and not payload.is_active:
            raise HTTPException(409, "Cannot disable own account")
        changes.append(f"is_active:{user.is_active}->{payload.is_active}")
        user.is_active = payload.is_active
        if not user.is_active:
            for token in list(db.scalars(select(AuthToken).where(AuthToken.user_id == user.id))):
                db.delete(token)
    audit(db, actor, "EMPLOYEE_UPDATED", "user", user.id, ";".join(changes))
    db.commit()
    db.refresh(user)
    return user


_POWER_ALERT_SINCE: dict[tuple[int, str], float] = {}


def _setting_int(db: Session, key: str, default: int) -> int:
    row = db.get(SystemSetting, key)
    if row is None:
        return default
    try:
        return int(str(row.value).strip())
    except (TypeError, ValueError):
        return default


def _power_monitor_config(db: Session) -> dict[str, int]:
    defaults = {
        "voltra_screen_on_watts_threshold": 5,
        "voltra_active_screen_alert_seconds": 8,
        "voltra_idle_screen_alert_seconds": 10,
    }
    rows = db.scalars(select(SystemSetting).where(SystemSetting.key.in_(list(defaults)))).all()
    values = dict(defaults)
    for row in rows:
        try:
            values[row.key] = max(0, int(str(row.value).strip()))
        except (TypeError, ValueError):
            pass
    return values


def _held_power_condition(station_id: int, key: str, condition: bool, hold_seconds: int) -> bool:
    marker = (station_id, key)
    if not condition:
        _POWER_ALERT_SINCE.pop(marker, None)
        return False
    now = time_module.monotonic()
    first = _POWER_ALERT_SINCE.setdefault(marker, now)
    return now - first >= max(0, hold_seconds)


def _station_power_monitor(
    db: Session,
    station: Station,
    active: PlaySession | None,
    raw_power: dict | None = None,
    monitor_config: dict[str, int] | None = None,
) -> tuple[dict, list[dict]]:
    """Return safe display-power status and live operational alerts.

    The station list passes a batched Voltra snapshot here, so one dashboard
    refresh performs one local Voltra request instead of one request per station.
    Billing remains independent from Voltra availability.
    """
    alerts: list[dict] = []
    try:
        raw = raw_power if raw_power is not None else voltra_power_status(station.id, timeout_seconds=0.5)
        outlet = raw.get("outlet_status") or {}
        watts_raw = outlet.get("power_w")
        try:
            watts = round(float(watts_raw), 2) if watts_raw is not None else None
        except (TypeError, ValueError):
            watts = None
        mapped_value = raw.get("mapped")
        power = {
            "mapped": None if mapped_value is None else bool(mapped_value),
            "online": bool(raw.get("online")),
            "relay": raw.get("relay"),
            "watts": watts,
            "outlet": raw.get("outlet"),
            "control_enabled": raw.get("control_enabled", True),
            "strip_state": raw.get("strip_state"),
        }
        if raw.get("error"):
            power["error"] = str(raw.get("error"))
    except VoltraError as exc:
        power = {
            "mapped": None,
            "online": False,
            "relay": None,
            "watts": None,
            "outlet": None,
            "control_enabled": False,
            "error": str(exc),
        }

    config = monitor_config or _power_monitor_config(db)
    threshold = config["voltra_screen_on_watts_threshold"]
    active_hold = config["voltra_active_screen_alert_seconds"]
    idle_hold = config["voltra_idle_screen_alert_seconds"]
    watts = power.get("watts")
    relay = power.get("relay")
    mapped = power.get("mapped")
    online = power.get("online")

    # Alert 1: the automatic ON action at session start did not complete. The
    # result is persisted on the session so a page refresh cannot hide it.
    if active is not None and getattr(active, "power_start_status", None) in {"FAILED", "OFFLINE", "UNAVAILABLE", "UNMAPPED"}:
        alerts.append({
            "code": "POWER_ON_START_FAILED",
            "severity": "critical",
            "title": "أمر تشغيل الشاشة لم يكتمل",
            "message": getattr(active, "power_start_message", None) or "تعذر تنفيذ أمر التشغيل عند بدء الجلسة.",
        })

    running = active is not None and active.status == "RUNNING"
    screen_off_condition = running and (
        relay is False
        or (relay is True and watts is not None and watts < threshold)
        or (mapped is True and online is False)
    )
    if _held_power_condition(station.id, "active_screen_off", screen_off_condition, active_hold):
        if relay is False:
            reason = "مخرج الشاشة OFF بينما الجلسة ما زالت شغالة."
        elif mapped is True and online is False:
            reason = "المشترك غير متصل أثناء جلسة شغالة."
        else:
            reason = f"استهلاك الشاشة {watts:.1f}W فقط، ويبدو أنها مطفأة أو في وضع Standby."
        alerts.append({
            "code": "SCREEN_OFF_DURING_SESSION",
            "severity": "critical",
            "title": "الشاشة مطفأة أثناء الجلسة",
            "message": reason,
        })

    # Alert 3: actual TV load exists while no PlayZone session exists. Relay ON
    # by itself is not enough because a TV in standby may legitimately draw a
    # tiny amount of power.
    screen_on_without_session = (
        active is None
        and online is True
        and relay is True
        and watts is not None
        and watts >= threshold
    )
    if _held_power_condition(station.id, "idle_screen_on", screen_on_without_session, idle_hold):
        alerts.append({
            "code": "SCREEN_ON_WITHOUT_SESSION",
            "severity": "warning",
            "title": "الشاشة تعمل بدون جلسة",
            "message": f"الشاشة تسحب {watts:.1f}W ولا توجد جلسة مفتوحة على {station.code}.",
        })

    return power, alerts


def _station_out(
    db: Session,
    station: Station,
    active: PlaySession | None = None,
    raw_power: dict | None = None,
    monitor_config: dict[str, int] | None = None,
    *,
    active_resolved: bool = False,
) -> StationOut:
    if not active_resolved:
        active = active_session_for_station(db, station.id)
    power, alerts = _station_power_monitor(db, station, active, raw_power, monitor_config)
    return StationOut(
        id=station.id,
        code=station.code,
        name=station.name,
        hourly_rate_piasters=station.hourly_rate_piasters,
        is_enabled=station.is_enabled,
        active_session=session_snapshot(active) if active else None,
        power=power,
        power_alerts=alerts,
    )


@app.get("/api/stations", response_model=list[StationOut])
def stations(user: User = Depends(ready_user), db: Session = Depends(get_db)):
    stations_list = list(db.scalars(select(Station).where(Station.is_enabled.is_(True)).order_by(Station.code)).all())

    # Resolve every active session in one query. selectinload batches the item
    # and event collections used by session_snapshot, avoiding N+1 SQL traffic.
    active_rows = list(db.scalars(
        select(PlaySession)
        .where(PlaySession.status.in_(["RUNNING", "PAUSED", "EXPIRED"]))
        .order_by(PlaySession.id.desc())
        .options(selectinload(PlaySession.items), selectinload(PlaySession.events))
    ).all())
    active_by_station: dict[int, PlaySession] = {}
    mode_row = db.get(SystemSetting, "timed_session_expiry_mode")
    stop_at_zero = (mode_row.value if mode_row else "STOP_AND_WAIT_PAYMENT") == "STOP_AND_WAIT_PAYMENT"
    for session in active_rows:
        if stop_at_zero and session.session_type == "TIMED" and session.status == "RUNNING":
            if expire_timed_session(db, session):
                _run_power_job("power-off", _background_power_off, session.station_id)
        active_by_station.setdefault(session.station_id, session)

    # One overview request replaces one Voltra HTTP request per station.
    power_by_station = voltra_power_statuses([station.id for station in stations_list], timeout_seconds=0.5)
    monitor_config = _power_monitor_config(db)
    return [
        _station_out(
            db,
            station,
            active_by_station.get(station.id),
            power_by_station.get(station.id),
            monitor_config,
            active_resolved=True,
        )
        for station in stations_list
    ]


@app.put("/api/root/stations/count")
def set_station_count(payload: StationCountUpdate, actor: User = Depends(root_ready_user), db: Session = Depends(get_db)):
    """Set the number of customer-visible stations without deleting history.

    Reducing the count disables the highest-numbered idle stations. Increasing
    first re-enables disabled stations, then creates new station rows as needed.
    """
    target = payload.count
    all_stations = list(db.scalars(select(Station).order_by(Station.id)).all())
    enabled = [station for station in all_stations if station.is_enabled]

    if target < len(enabled):
        to_disable = enabled[target:]
        for station in to_disable:
            if active_session_for_station(db, station.id):
                raise HTTPException(409, f"Cannot reduce devices while {station.code} has an active session")
            station.is_enabled = False
            audit(db, actor, "STATION_UPDATED", "station", station.id, "enabled:True->False;root_count")
    elif target > len(enabled):
        needed = target - len(enabled)
        disabled = [station for station in all_stations if not station.is_enabled]
        for station in disabled[:needed]:
            station.is_enabled = True
            audit(db, actor, "STATION_UPDATED", "station", station.id, "enabled:False->True;root_count")
            needed -= 1
        if needed:
            rate_row = db.get(SystemSetting, "default_hourly_rate_piasters")
            rate = int(rate_row.value) if rate_row else 6000
            used_codes = {station.code for station in all_stations}
            next_no = 1
            while needed:
                code = f"PS4-{next_no:02d}"
                next_no += 1
                if code in used_codes:
                    continue
                station = Station(code=code, name=code, hourly_rate_piasters=rate, is_enabled=True)
                db.add(station)
                db.flush()
                used_codes.add(code)
                audit(db, actor, "STATION_CREATED", "station", station.id, "root_count")
                needed -= 1
    db.commit()
    visible = list(db.scalars(select(Station).where(Station.is_enabled.is_(True)).order_by(Station.code)).all())
    return {"count": len(visible), "stations": [{"id": x.id, "code": x.code, "name": x.name} for x in visible]}


@app.patch("/api/stations/{station_id}", response_model=StationOut)
def update_station(station_id: int, payload: StationUpdate, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    station = db.get(Station, station_id)
    if not station:
        raise HTTPException(404, "Station not found")
    if payload.hourly_rate_piasters is not None:
        audit(db, actor, "PRICE_CHANGED", "station", station.id,
              f"old={station.hourly_rate_piasters};new={payload.hourly_rate_piasters}")
        station.hourly_rate_piasters = payload.hourly_rate_piasters
    if payload.is_enabled is not None:
        if not payload.is_enabled and active_session_for_station(db, station.id):
            raise HTTPException(409, "Cannot disable station with active session")
        audit(db, actor, "STATION_UPDATED", "station", station.id, f"enabled:{station.is_enabled}->{payload.is_enabled}")
        station.is_enabled = payload.is_enabled
    db.commit()
    db.refresh(station)
    return _station_out(db, station)


# ---- Embedded Voltra console ---------------------------------------------

_VOLTRA_CONSOLE_API = "http://127.0.0.1:8086/voltra/api"


def _embedded_voltra_console_html() -> str:
    """Serve the native Voltra dashboard in PlayZone mode."""
    html = VOLTRA_DASHBOARD_HTML
    html = html.replace(
        "<title>Voltra Power Manager</title>",
        "<title>PlayZone Manager — Voltra</title>",
    )
    html = html.replace(
        "</style></head>",
        ".pz-playzone-back{position:fixed;top:12px;left:14px;z-index:180;"
        "display:inline-flex;align-items:center;gap:7px;padding:9px 13px;border-radius:10px;"
        "border:1px solid #2b5778;background:#0b2236e8;color:#ddecfa;text-decoration:none;"
        "font-weight:700;box-shadow:0 7px 24px #0006}.pz-playzone-back:hover{background:#123653;color:#fff}"
        "</style></head>",
    )
    html = html.replace(
        '<body><div class="shell">',
        '<body><a class="pz-playzone-back" href="/">← العودة إلى PlayZone</a><div class="shell">',
    )
    return html


@app.get("/voltra-console", response_class=HTMLResponse)
def embedded_voltra_console():
    # The HTML shell itself contains no customer/device data. Every data/action
    # request is proxied through a ROOT-authenticated PlayZone API below.
    return HTMLResponse(_embedded_voltra_console_html(), headers={"Cache-Control": "no-store"})


@app.api_route(
    "/api/root/voltra-console/{subpath:path}",
    methods=["GET", "POST", "PUT", "DELETE"],
)
async def embedded_voltra_console_proxy(
    subpath: str,
    request: Request,
    _: User = Depends(root_ready_user),
):
    target = f"{_VOLTRA_CONSOLE_API}/{subpath.lstrip('/')}"
    body = await request.body()
    headers: dict[str, str] = {}
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type
    voltra_token = os.getenv("VOLTRA_API_TOKEN", "").strip()
    if voltra_token:
        headers["Authorization"] = f"Bearer {voltra_token}"

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            upstream = await client.request(
                request.method,
                target,
                params=request.query_params,
                content=body or None,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"Voltra console unavailable: {exc}") from exc

    response_headers = {"Cache-Control": "no-store"}
    upstream_type = upstream.headers.get("content-type")
    if upstream_type:
        response_headers["Content-Type"] = upstream_type
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )


# ---- Voltra power integration -------------------------------------------

def _voltra_error(exc: VoltraError) -> HTTPException:
    return HTTPException(503, str(exc))


def _station_or_404(db: Session, station_id: int) -> Station:
    station = db.get(Station, station_id)
    if not station:
        raise HTTPException(404, "Station not found")
    return station


@app.post("/api/voltra/sync")
def sync_voltra_devices(actor: User = Depends(root_ready_user), db: Session = Depends(get_db)):
    stations = list(db.scalars(select(Station).order_by(Station.id)).all())
    try:
        result = voltra_sync_stations(stations)
    except VoltraError as exc:
        raise _voltra_error(exc) from exc
    audit(db, actor, "VOLTRA_SYNC", "station", None, f"count={len(stations)}")
    db.commit()
    return result


@app.get("/api/voltra/ps4")
def list_voltra_power(_: User = Depends(root_ready_user), db: Session = Depends(get_db)):
    stations_list = list(db.scalars(select(Station).order_by(Station.code)).all())
    powers = voltra_power_statuses([station.id for station in stations_list], timeout_seconds=1.0)
    return {
        "devices": [
            {"id": station.id, "code": station.code, "name": station.name, "power": powers.get(station.id)}
            for station in stations_list
        ]
    }


@app.get("/api/voltra/ps4/{station_id}/power")
def get_voltra_power(station_id: int, _: User = Depends(root_ready_user), db: Session = Depends(get_db)):
    _station_or_404(db, station_id)
    try:
        return voltra_power_status(station_id)
    except VoltraError as exc:
        raise _voltra_error(exc) from exc


@app.post("/api/voltra/ps4/{station_id}/power/{action}")
def change_voltra_power(station_id: int, action: str, actor: User = Depends(root_ready_user), db: Session = Depends(get_db)):
    station = _station_or_404(db, station_id)
    if action not in ("on", "off"):
        raise HTTPException(404, "Unknown power action")
    try:
        result = voltra_set_power(station.id, action == "on")
    except VoltraError as exc:
        raise _voltra_error(exc) from exc
    audit(db, actor, f"VOLTRA_POWER_{action.upper()}", "station", station.id)
    db.commit()
    return result


@app.get("/api/settings/{key}")
def get_setting(key: str, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    if key not in ("initial_grace_seconds", "default_hourly_rate_piasters", "shift_required"):
        raise HTTPException(404, "Setting not found")
    row = db.get(SystemSetting, key)
    if not row:
        raise HTTPException(404, "Setting not found")
    return {"key": row.key, "value": row.value}


@app.put("/api/settings/{key}")
def set_setting(key: str, payload: SettingUpdate, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    if key not in ("initial_grace_seconds", "default_hourly_rate_piasters", "shift_required"):
        raise HTTPException(404, "Setting not found")
    value = int(payload.value)
    if key == "initial_grace_seconds" and not 0 <= value <= 3600:
        raise HTTPException(422, "Grace must be 0 to 3600 seconds")
    if key == "default_hourly_rate_piasters" and not 1 <= value <= 1_000_000:
        raise HTTPException(422, "Rate must be 1 to 1000000 piasters")
    if key == "shift_required" and value not in (0, 1):
        raise HTTPException(422, "shift_required must be 0 or 1")
    row = db.get(SystemSetting, key)
    old = row.value if row else None
    if row:
        row.value = payload.value
    else:
        row = SystemSetting(key=key, value=payload.value)
        db.add(row)
    if key == "default_hourly_rate_piasters":
        for station in db.scalars(select(Station)):
            station.hourly_rate_piasters = value
    action = "GRACE_CHANGED" if key == "initial_grace_seconds" else "PRICE_CHANGED" if key == "default_hourly_rate_piasters" else "SETTING_CHANGED"
    audit(db, actor, action, "setting", None, f"{key}:old={old};new={value}")
    db.commit()
    return {"key": row.key, "value": row.value}


def _setting_enabled(db: Session, key: str, default: bool = False) -> bool:
    row = db.get(SystemSetting, key)
    if row is None:
        return default
    return str(row.value).strip().lower() in {"1", "true", "yes", "on"}


PAYMENT_METHOD_LABELS = {"CASH": "نقداً", "INSTAPAY": "InstaPay", "VISA": "Visa"}


def _payment_methods_config(db: Session) -> dict:
    mapping = {
        "CASH": _setting_enabled(db, "payment_cash_enabled", True),
        "INSTAPAY": _setting_enabled(db, "payment_instapay_enabled", True),
        "VISA": _setting_enabled(db, "payment_visa_enabled", True),
    }
    enabled = [method for method in ("CASH", "INSTAPAY", "VISA") if mapping[method]]
    # Corrupt/manual DB edits must never leave checkout unusable. Cash is the
    # safe compatibility fallback, while the ROOT API itself prevents an empty set.
    if not enabled:
        enabled = ["CASH"]
    return {
        "enabled": enabled,
        "methods": [
            {"id": method, "label": PAYMENT_METHOD_LABELS[method], "enabled": method in enabled}
            for method in ("CASH", "INSTAPAY", "VISA")
        ],
    }


def _timed_session_config(db: Session) -> dict:
    row = db.get(SystemSetting, "timed_session_presets_seconds")
    raw = row.value if row else "600,1200,1800,3600,7200,10800"
    presets = []
    for part in str(raw).split(","):
        try:
            value = int(part.strip())
        except (TypeError, ValueError):
            continue
        if 60 <= value <= 12 * 60 * 60 and value not in presets:
            presets.append(value)
    if not presets:
        presets = [600, 1200, 1800, 3600, 7200, 10800]
    mode_row = db.get(SystemSetting, "timed_session_expiry_mode")
    mode = str(mode_row.value if mode_row else "STOP_AND_WAIT_PAYMENT").upper()
    if mode not in ("STOP_AND_WAIT_PAYMENT", "NOTIFY_ONLY"):
        mode = "STOP_AND_WAIT_PAYMENT"
    return {"presets_seconds": sorted(presets), "expiry_mode": mode}


def _expire_timed_if_due(db: Session, session: PlaySession, *, queue_power_off: bool = True) -> bool:
    """Apply STOP_AND_WAIT_PAYMENT synchronously on any session action.

    The one-second monitor remains the normal expiry path, but an HTTP action can
    race that monitor by a fraction of a second. This guard ensures billing can
    never continue past the configured timed deadline even in that race window.
    """
    if session.session_type != "TIMED" or session.status != "RUNNING":
        return False
    mode_row = db.get(SystemSetting, "timed_session_expiry_mode")
    mode = str(mode_row.value if mode_row else "STOP_AND_WAIT_PAYMENT").upper()
    if mode != "STOP_AND_WAIT_PAYMENT":
        return False
    expired = expire_timed_session(db, session)
    if expired and queue_power_off:
        _run_power_job("power-off", _background_power_off, session.station_id)
    return expired


def _ui_config(db: Session) -> dict[str, bool]:
    return {
        key: _setting_enabled(db, f"ui_{key}", default)
        for key, default in UI_CONFIG_DEFAULTS.items()
    }


@app.get("/api/ui-config")
def get_ui_config(_: User = Depends(ready_user), db: Session = Depends(get_db)):
    return _ui_config(db)


@app.put("/api/ui-config/{key}")
def set_ui_config(key: str, payload: SettingUpdate, actor: User = Depends(root_ready_user), db: Session = Depends(get_db)):
    if key not in UI_CONFIG_DEFAULTS:
        raise HTTPException(404, "UI control not found")
    value = int(payload.value)
    if value not in (0, 1):
        raise HTTPException(422, "UI control value must be 0 or 1")
    db_key = f"ui_{key}"
    row = db.get(SystemSetting, db_key)
    old = row.value if row else ("1" if UI_CONFIG_DEFAULTS[key] else "0")
    if row:
        row.value = str(value)
    else:
        db.add(SystemSetting(key=db_key, value=str(value)))
    audit(db, actor, "UI_CONFIG_CHANGED", "setting", None, f"{key}:old={old};new={value}")
    db.commit()
    return {"key": key, "value": bool(value), "config": _ui_config(db)}


@app.post("/api/ui-config/reset")
def reset_ui_config(actor: User = Depends(root_ready_user), db: Session = Depends(get_db)):
    for key, default in UI_CONFIG_DEFAULTS.items():
        db_key = f"ui_{key}"
        value = "1" if default else "0"
        row = db.get(SystemSetting, db_key)
        if row:
            row.value = value
        else:
            db.add(SystemSetting(key=db_key, value=value))
    audit(db, actor, "UI_CONFIG_RESET", "setting", None, "customer UI profile restored to defaults")
    db.commit()
    return _ui_config(db)


@app.get("/api/payment-methods")
def get_payment_methods(_: User = Depends(ready_user), db: Session = Depends(get_db)):
    return _payment_methods_config(db)


@app.put("/api/root/payment-methods")
def set_payment_methods(payload: PaymentMethodsUpdate, actor: User = Depends(root_ready_user), db: Session = Depends(get_db)):
    enabled = set(payload.enabled)
    for method, key in (("CASH", "payment_cash_enabled"), ("INSTAPAY", "payment_instapay_enabled"), ("VISA", "payment_visa_enabled")):
        value = "1" if method in enabled else "0"
        row = db.get(SystemSetting, key)
        if row:
            row.value = value
        else:
            db.add(SystemSetting(key=key, value=value))
    audit(db, actor, "PAYMENT_METHODS_CHANGED", "setting", None, f"enabled={','.join(payload.enabled)}")
    db.commit()
    return _payment_methods_config(db)


@app.get("/api/timed-session-settings")
def get_timed_session_settings(_: User = Depends(ready_user), db: Session = Depends(get_db)):
    return _timed_session_config(db)


@app.put("/api/root/timed-session-settings")
def set_timed_session_settings(payload: TimedSessionSettingsUpdate, actor: User = Depends(root_ready_user), db: Session = Depends(get_db)):
    values = {
        "timed_session_presets_seconds": ",".join(str(v) for v in payload.presets_seconds),
        "timed_session_expiry_mode": payload.expiry_mode,
    }
    for key, value in values.items():
        row = db.get(SystemSetting, key)
        if row:
            row.value = value
        else:
            db.add(SystemSetting(key=key, value=value))
    audit(
        db, actor, "TIMED_SESSION_SETTINGS_CHANGED", "setting", None,
        f"presets={values['timed_session_presets_seconds']};expiry={payload.expiry_mode}",
    )
    db.commit()
    return _timed_session_config(db)


def _auto_power_on_after_session_start(db: Session, station: Station) -> dict:
    """Best-effort TV/display outlet ON after a session has been committed.

    Voltra outlets in this deployment are mapped to TVs/displays, not PS4 consoles.
    Never roll back or reject a valid cashier session because the optional local
    power subsystem is unavailable, offline, or not mapped.
    """
    if not _setting_enabled(db, "voltra_auto_power_on_start", True):
        return {"attempted": False, "status": "DISABLED", "message": "Auto display power-on is disabled"}

    try:
        status = voltra_power_status(station.id)
    except VoltraError as exc:
        message = str(exc)
        return {"attempted": True, "status": "UNAVAILABLE", "message": message}

    if not status.get("mapped"):
        return {"attempted": False, "status": "UNMAPPED", "message": "Station has no Voltra display mapping"}

    if not status.get("online"):
        return {"attempted": True, "status": "OFFLINE", "message": "Mapped Voltra strip is offline"}

    if status.get("relay") is True:
        return {"attempted": True, "status": "ALREADY_ON", "message": "Display power was already on", "power": status}

    try:
        result = voltra_set_power(station.id, True)
    except VoltraError as exc:
        message = str(exc)
        return {"attempted": True, "status": "FAILED", "message": message, "power": status}

    return {"attempted": True, "status": "ON", "message": "Display power turned on", "power": result}


def _auto_power_off_after_session_end(db: Session, station: Station) -> dict:
    """Best-effort TV/display outlet OFF after invoice finalization.

    The mapped outlet is explicitly for the station's TV/display. The PS4 console
    must remain on a separate power source. Financial/session finalization happens
    first and is never rolled back if Voltra is unavailable or unmapped.
    """
    if not _setting_enabled(db, "voltra_auto_power_off_end", True):
        return {"attempted": False, "status": "DISABLED", "message": "Auto display power-off is disabled"}

    try:
        status = voltra_power_status(station.id)
    except VoltraError as exc:
        return {"attempted": True, "status": "UNAVAILABLE", "message": str(exc)}

    if not status.get("mapped"):
        return {"attempted": False, "status": "UNMAPPED", "message": "Station has no Voltra display mapping"}

    if not status.get("online"):
        return {"attempted": True, "status": "OFFLINE", "message": "Mapped Voltra strip is offline"}

    if status.get("relay") is False:
        return {"attempted": True, "status": "ALREADY_OFF", "message": "Display power was already off", "power": status}

    try:
        result = voltra_set_power(station.id, False)
    except VoltraError as exc:
        return {"attempted": True, "status": "FAILED", "message": str(exc), "power": status}

    return {"attempted": True, "status": "OFF", "message": "Display power turned off", "power": result}


def _run_power_job(name: str, target, *args) -> None:
    def runner() -> None:
        try:
            target(*args)
        except Exception as exc:
            print(f"[VOLTRA] background {name} failed: {exc}")

    threading.Thread(target=runner, name=f"playzone-{name}", daemon=True).start()


def _background_power_on(session_id: int, station_id: int) -> None:
    """Run optional display power-on without holding the cashier HTTP response."""
    with SessionLocal() as db:
        station = db.get(Station, station_id)
        session = db.get(PlaySession, session_id)
        if station is None or session is None:
            return
        power = _auto_power_on_after_session_start(db, station)
        try:
            session.power_start_status = str(power.get("status") or "UNKNOWN")
            session.power_start_message = str(power.get("message") or "")[:500]
            session.power_start_checked_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            db.rollback()
            raise


def _background_power_off(station_id: int) -> None:
    """Run optional display power-off without delaying invoice/expiry handling."""
    with SessionLocal() as db:
        station = db.get(Station, station_id)
        if station is None:
            return
        _auto_power_off_after_session_end(db, station)


_TIMED_MONITOR_STOP = threading.Event()
_TIMED_MONITOR_THREAD: threading.Thread | None = None


def _timed_session_monitor_loop() -> None:
    while not _TIMED_MONITOR_STOP.wait(1.0):
        try:
            with SessionLocal() as db:
                config = _timed_session_config(db)
                if config["expiry_mode"] != "STOP_AND_WAIT_PAYMENT":
                    continue
                sessions = list(db.scalars(
                    select(PlaySession).where(
                        PlaySession.status == "RUNNING",
                        PlaySession.session_type == "TIMED",
                    )
                ))
                for session in sessions:
                    try:
                        if expire_timed_session(db, session):
                            # Freeze the financial timer first, then turn off the
                            # TV/display best-effort. Never power the PS4 console.
                            _run_power_job("power-off", _background_power_off, session.station_id)
                    except Exception as exc:
                        db.rollback()
                        print(f"[TIMED] expiry error for session {session.id}: {exc}")
        except Exception as exc:
            print(f"[TIMED] monitor error: {exc}")


def start_timed_session_monitor() -> None:
    global _TIMED_MONITOR_THREAD
    if _TIMED_MONITOR_THREAD and _TIMED_MONITOR_THREAD.is_alive():
        return
    _TIMED_MONITOR_STOP.clear()
    _TIMED_MONITOR_THREAD = threading.Thread(
        target=_timed_session_monitor_loop, name="playzone-timed-monitor", daemon=True
    )
    _TIMED_MONITOR_THREAD.start()
    print("[TIMED] session monitor started")


def stop_timed_session_monitor() -> None:
    global _TIMED_MONITOR_THREAD
    _TIMED_MONITOR_STOP.set()
    thread = _TIMED_MONITOR_THREAD
    _TIMED_MONITOR_THREAD = None
    if thread and thread.is_alive():
        thread.join(timeout=2.0)


# ---- Cashier shifts -------------------------------------------------------

@app.get("/api/shifts/current")
def current_shift(user: User = Depends(ready_user), db: Session = Depends(get_db)):
    # STAFF sees only their own shift. ADMIN/ROOT sees the one physical drawer
    # shift so a manager can settle it even after the cashier logs out.
    shift = active_drawer_shift(db) if user.role in ("ROOT", "ADMIN") else active_shift_for_user(db, user.id)
    return shift_snapshot(db, shift) if shift else None


@app.post("/api/shifts/open")
def api_open_shift(payload: ShiftOpenRequest, user: User = Depends(ready_user), db: Session = Depends(get_db)):
    # Staff cannot invent a drawer opening balance. A cashier shift always starts
    # from zero after the previous drawer was settled by an administrator.
    opening_cash = int(payload.opening_cash_piasters)
    if user.role == "STAFF" and opening_cash != 0:
        audit(db, user, "SHIFT_OPENING_CASH_BLOCKED", "shift", None, f"attempted={opening_cash}")
        db.commit()
        raise HTTPException(403, "Staff shifts must start at zero after admin settlement")
    return shift_snapshot(db, open_shift(db, user, opening_cash))


@app.get("/api/shifts")
def list_shifts(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Shift).order_by(Shift.id.desc()).limit(300)).all()
    return [shift_snapshot(db, shift) for shift in rows]


@app.get("/api/shifts/{shift_id}")
def shift_detail(shift_id: int, user: User = Depends(ready_user), db: Session = Depends(get_db)):
    shift = db.get(Shift, shift_id)
    if not shift:
        raise HTTPException(404, "Shift not found")
    if user.role not in ("ROOT", "ADMIN") and shift.employee_id != user.id:
        raise HTTPException(403, "Cannot access another employee's shift")
    result = shift_snapshot(db, shift)
    result["movements"] = [{
        "id": m.id,
        "type": m.movement_type,
        "amount_piasters": m.amount_piasters,
        "reason": m.reason,
        "approval_status": m.approval_status,
        "requested_by_user_id": m.user_id,
        "requested_by": (m.user.display_name or m.user.username) if m.user else str(m.user_id),
        "decided_by_user_id": m.decided_by_user_id,
        "decided_by": ((m.decided_by.display_name or m.decided_by.username) if m.decided_by else None),
        "decided_at": normalize_utc(m.decided_at) if m.decided_at else None,
        "created_at": normalize_utc(m.created_at),
    } for m in sorted(shift.movements, key=lambda row: row.id, reverse=True)]
    return result


@app.post("/api/shifts/{shift_id}/movements")
def api_cash_movement(shift_id: int, payload: CashMovementCreate, user: User = Depends(ready_user), db: Session = Depends(get_db)):
    shift = db.get(Shift, shift_id)
    if not shift:
        raise HTTPException(404, "Shift not found")
    movement = add_cash_movement(db, shift, user, payload.movement_type, payload.amount_piasters, payload.reason)
    return {
        "id": movement.id,
        "shift_id": movement.shift_id,
        "movement_type": movement.movement_type,
        "amount_piasters": movement.amount_piasters,
        "reason": movement.reason,
        "approval_status": movement.approval_status,
        "created_at": normalize_utc(movement.created_at),
    }


@app.post("/api/shifts/{shift_id}/movements/{movement_id}/decision")
def api_cash_movement_decision(
    shift_id: int,
    movement_id: int,
    payload: CashMovementDecisionRequest,
    user: User = Depends(ready_user),
    db: Session = Depends(get_db),
):
    requester_id = user.id
    requester_role = user.role
    with _CASH_DRAWER_LOCK:
        # Authentication dependencies already performed reads on this Session.
        # End that read transaction so approval checks see the latest committed
        # drawer balance after waiting for any previous approval to finish.
        db.rollback()
        requester = db.get(User, requester_id)
        shift = db.get(Shift, shift_id)
        if not shift:
            raise HTTPException(404, "Shift not found")
        if requester_role not in ("ROOT", "ADMIN") and shift.employee_id != requester_id:
            raise HTTPException(403, "Cannot access another employee's shift")
        movement = db.get(CashMovement, movement_id)
        if not movement or movement.shift_id != shift.id:
            raise HTTPException(404, "Cash movement not found")
        admin = _admin_password_approval(
            db,
            admin_username=payload.admin_username,
            admin_password=payload.admin_password,
            requested_by=requester,
            purpose=f"cash_movement:{payload.decision}:{movement.id}",
        )
        movement = decide_cash_movement(db, shift, movement, admin, payload.decision)
        return {
            "id": movement.id,
            "shift_id": movement.shift_id,
            "movement_type": movement.movement_type,
            "amount_piasters": movement.amount_piasters,
            "reason": movement.reason,
            "approval_status": movement.approval_status,
            "decided_by": admin.username,
            "decided_at": normalize_utc(movement.decided_at),
        }


@app.get("/api/shifts/{shift_id}/handoff-candidates")
def shift_handoff_candidates(
    shift_id: int,
    user: User = Depends(ready_user),
    db: Session = Depends(get_db),
):
    shift = db.get(Shift, shift_id)
    if not shift:
        raise HTTPException(404, "Shift not found")
    if shift.status != "OPEN":
        raise HTTPException(409, "Shift is closed")
    if user.role not in ("ROOT", "ADMIN") and shift.employee_id != user.id:
        raise HTTPException(403, "Only the current cashier can hand off this shift")
    rows = db.scalars(
        select(User).where(
            User.role == "STAFF",
            User.is_active.is_(True),
            User.id != shift.employee_id,
        ).order_by(User.display_name, User.username)
    ).all()
    return [
        {"id": row.id, "username": row.username, "display_name": row.display_name or row.username}
        for row in rows
        if not active_shift_for_user(db, row.id)
    ]


@app.post("/api/shifts/{shift_id}/handoff")
def api_shift_handoff(
    shift_id: int,
    payload: ShiftHandoffRequest,
    authorization: str = Header(),
    user: User = Depends(ready_user),
    db: Session = Depends(get_db),
):
    requester_id = user.id
    with _CASH_DRAWER_LOCK:
        db.rollback()
        requester = db.get(User, requester_id)
        shift = db.get(Shift, shift_id)
        if not shift:
            raise HTTPException(404, "Shift not found")
        if shift.status != "OPEN":
            raise HTTPException(409, "Shift is closed")
        if requester.role not in ("ROOT", "ADMIN") and shift.employee_id != requester.id:
            raise HTTPException(403, "Only the current cashier can hand off this shift")

        incoming = db.get(User, payload.to_user_id)
        auth_key = f"handoff:{shift.id}:{payload.to_user_id}"
        _check_auth_rate_limit(auth_key)
        valid = bool(
            incoming
            and incoming.is_active
            and incoming.role == "STAFF"
            and not incoming.must_change_password
            and verify_password(payload.password, incoming.password_hash)
        )
        if not valid:
            _record_auth_failure(auth_key)
            audit(
                db,
                requester,
                "SHIFT_HANDOFF_AUTH_FAILED",
                "shift",
                shift.id,
                f"to_user_id={payload.to_user_id}",
            )
            db.commit()
            raise HTTPException(401, "Invalid receiving employee password")
        _clear_auth_failures(auth_key)

        previous_employee_id = shift.employee_id
        handoff_shift(db, shift, requester, incoming)

        # A handoff is an account switch, not just a name change. Invalidate all
        # cashier sessions for both sides and issue one fresh token to the receiver.
        for token in list(db.scalars(select(AuthToken).where(
            AuthToken.user_id.in_([previous_employee_id, incoming.id])
        ))):
            db.delete(token)
        raw = new_token()
        db.add(AuthToken(token_hash=token_hash(raw), user_id=incoming.id, expires_at=token_expiry()))
        audit(
            db,
            incoming,
            "SHIFT_HANDOFF_LOGIN",
            "shift",
            shift.id,
            f"from={previous_employee_id};to={incoming.id}",
        )
        db.commit()

        refreshed = db.get(Shift, shift.id)
        return {
            "token": raw,
            "role": incoming.role,
            "username": incoming.username,
            "display_name": incoming.display_name or incoming.username,
            "shift": shift_snapshot(db, refreshed),
        }


@app.post("/api/shifts/{shift_id}/close")
def api_close_shift(shift_id: int, payload: ShiftCloseRequest, user: User = Depends(ready_user), db: Session = Depends(get_db)):
    requester_id = user.id
    requester_role = user.role
    with _CASH_DRAWER_LOCK:
        db.rollback()
        requester = db.get(User, requester_id)
        shift = db.get(Shift, shift_id)
        if not shift:
            raise HTTPException(404, "Shift not found")
        if requester_role not in ("ROOT", "ADMIN") and shift.employee_id != requester_id:
            raise HTTPException(403, "Cannot close another employee's shift")
        admin = _admin_password_approval(
            db,
            admin_username=payload.admin_username,
            admin_password=payload.admin_password,
            requested_by=requester,
            purpose=f"close_shift:{shift.id}",
        )
        closed = close_shift(db, shift, admin, payload.actual_cash_piasters)
        return shift_snapshot(db, closed)

# ---- Sessions / invoices -------------------------------------------------

@app.post("/api/stations/{station_id}/sessions/start")
def api_start(
    station_id: int,
    payload: SessionStartRequest | None = None,
    user: User = Depends(ready_user),
    db: Session = Depends(get_db),
):
    require_cashier_shift(db, user)
    station = db.get(Station, station_id)
    if not station:
        raise HTTPException(404, "Station not found")

    payload = payload or SessionStartRequest()
    if payload.session_type == "TIMED" and payload.duration_seconds is None:
        raise HTTPException(422, "Timed session duration is required")

    # Commit the financial/session state first. Voltra is an optional local
    # subsystem, so a mapping/network/hardware failure must never lose or reject
    # a valid cashier session.
    session = start_session(
        db, station, user, session_type=payload.session_type, duration_seconds=payload.duration_seconds,
        controller_count=payload.controller_count,
    )
    # The financial/session commit is complete. Power control now runs in a
    # daemon worker so an offline strip can never add seconds to cashier latency.
    _run_power_job("power-on", _background_power_on, session.id, station.id)
    response = session_snapshot(session)
    response["power"] = {"attempted": True, "status": "QUEUED", "message": "Display power update queued"}
    # Some tests and local deployments reuse one SQLAlchemy Session across API
    # calls. Detach this freshly-started session so later item additions cannot
    # observe the empty relationship collection cached for the start response.
    db.expunge(session)
    return response


@app.post("/api/sessions/{session_id}/controllers")
def api_change_controller_count(
    session_id: int, payload: ControllerCountUpdate, user: User = Depends(ready_user), db: Session = Depends(get_db)
):
    require_cashier_shift(db, user)
    session = db.get(PlaySession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    _expire_timed_if_due(db, session)
    session = change_controller_count(db, session, user, payload.controller_count)
    return session_snapshot(session)


@app.post("/api/sessions/{session_id}/extend")
def api_extend_timed_session(
    session_id: int, payload: TimedSessionExtendRequest, user: User = Depends(ready_user), db: Session = Depends(get_db)
):
    require_cashier_shift(db, user)
    session = db.get(PlaySession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    # If zero was reached just before the monitor tick, freeze at the exact
    # deadline first. We skip OFF here because the same request immediately
    # grants more time and queues ON for the same display.
    _expire_timed_if_due(db, session, queue_power_off=False)
    was_expired = session.status == "EXPIRED"
    session = extend_timed_session(db, session, user, payload.seconds)
    power = None
    if was_expired and session.status == "RUNNING":
        _run_power_job("power-on", _background_power_on, session.id, session.station_id)
        power = {"attempted": True, "status": "QUEUED", "message": "Display power update queued"}
    response = session_snapshot(session)
    if power is not None:
        response["power"] = power
    return response


@app.post("/api/sessions/{session_id}/pause")
def api_pause(session_id: int, user: User = Depends(ready_user), db: Session = Depends(get_db)):
    require_cashier_shift(db, user)
    session = db.get(PlaySession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if _expire_timed_if_due(db, session):
        return session_snapshot(session)
    return session_snapshot(pause_session(db, session, user))


@app.post("/api/sessions/{session_id}/resume")
def api_resume(session_id: int, user: User = Depends(ready_user), db: Session = Depends(get_db)):
    require_cashier_shift(db, user)
    session = db.get(PlaySession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session_snapshot(resume_session(db, session, user))


@app.get("/api/sessions/{session_id}/preview")
def api_preview(session_id: int, discount_piasters: int = Query(default=0, ge=0),
                user: User = Depends(ready_user), db: Session = Depends(get_db)):
    session = db.get(PlaySession, session_id)
    if not session or session.status == "ENDED":
        raise HTTPException(404, "Active session not found")
    _expire_timed_if_due(db, session)
    if discount_piasters and user.role not in ("ROOT", "ADMIN"):
        raise HTTPException(403, "Only admin can apply discounts")
    return session_snapshot(session, discount_piasters=discount_piasters)


@app.post("/api/sessions/{session_id}/end", response_model=InvoiceOut)
def api_end(session_id: int, payload: PaymentRequest, user: User = Depends(ready_user), db: Session = Depends(get_db)):
    shift = require_cashier_shift(db, user)
    session = db.get(PlaySession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    # Finalization must use the timed deadline, not the request arrival time, if
    # this request wins the race against the one-second expiry monitor. The end
    # path itself already queues display OFF, so avoid duplicate OFF jobs here.
    _expire_timed_if_due(db, session, queue_power_off=False)
    if payload.discount_piasters and user.role not in ("ROOT", "ADMIN"):
        raise HTTPException(403, "Only admin can apply discounts")
    enabled_methods = _payment_methods_config(db)["enabled"]
    if payload.payment_method not in enabled_methods:
        raise HTTPException(409, "PAYMENT_METHOD_DISABLED")
    if user.role == "STAFF" and payload.payment_method != "CASH":
        _admin_password_approval(
            db,
            admin_username=payload.admin_username or "",
            admin_password=payload.admin_password or "",
            requested_by=user,
            purpose=f"non_cash_payment:{session.id}:{payload.payment_method}",
        )

    # Finalize the financial record first. Display power is optional and must never
    # make an already-valid invoice/session finalization fail or roll back.
    station = session.station
    invoice = end_session(db, session, user, payment_method=payload.payment_method,
                          discount_piasters=payload.discount_piasters, shift=shift)
    _run_power_job("power-off", _background_power_off, station.id)
    response = InvoiceOut.model_validate(invoice).model_dump()
    response["power"] = {"attempted": True, "status": "QUEUED", "message": "Display power update queued"}
    return response


@app.get("/api/invoices", response_model=list[InvoiceOut])
def invoices(user: User = Depends(ready_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(Invoice).order_by(Invoice.id.desc()).limit(200)).all())


@app.get("/api/invoices/{invoice_id}")
def invoice_detail(invoice_id: int, user: User = Depends(ready_user), db: Session = Depends(get_db)):
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(404, "Invoice not found")
    session = invoice.session
    return {
        "invoice": InvoiceOut.model_validate(invoice),
        "station": session.station.code,
        "employee": invoice.issued_by.display_name or invoice.issued_by.username,
        "session_start": normalize_utc(session.started_at),
        "session_end": normalize_utc(session.ended_at) if session.ended_at else None,
        "hourly_rate_piasters": session.hourly_rate_piasters,
        "session": session_snapshot(session, session.ended_at),
        "items": session_totals(session, session.ended_at)["items"],
    }


# ---- Products ------------------------------------------------------------

@app.get("/api/products", response_model=list[ProductOut])
def products(user: User = Depends(ready_user), db: Session = Depends(get_db)):
    query = select(Product).order_by(Product.name)
    if user.role not in ("ROOT", "ADMIN"):
        query = query.where(Product.is_active == True)
    return list(db.scalars(query).all())


@app.post("/api/products", response_model=ProductOut)
def create_product(payload: ProductCreate, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    product = Product(**payload.model_dump())
    db.add(product)
    db.flush()
    audit(db, user, "PRODUCT_CREATED", "product", product.id, f"name={product.name};price={product.price_piasters}")
    db.commit()
    db.refresh(product)
    return product


@app.patch("/api/products/{product_id}", response_model=ProductOut)
def update_product(product_id: int, payload: ProductUpdate, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    changes = []
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            changes.append(f"{key}:{getattr(product, key)}->{value}")
            setattr(product, key, value)
    audit(db, user, "PRODUCT_UPDATED", "product", product.id, ";".join(changes))
    db.commit()
    db.refresh(product)
    return product


@app.post("/api/sessions/{session_id}/items")
def api_add_item(session_id: int, payload: AddItem, user: User = Depends(ready_user), db: Session = Depends(get_db)):
    require_cashier_shift(db, user)
    session = db.get(PlaySession, session_id)
    product = db.get(Product, payload.product_id)
    if not session or not product:
        raise HTTPException(404, "Session or product not found")
    _expire_timed_if_due(db, session)
    item = add_product(db, session, product, payload.quantity, user)
    return {"id": item.id, "product_name": item.product_name, "quantity": item.quantity,
            "unit_price_piasters": item.unit_price_piasters,
            "line_total_piasters": item.unit_price_piasters * item.quantity}


@app.get("/api/sessions")
def sessions(user: User = Depends(ready_user), db: Session = Depends(get_db)):
    rows = list(db.scalars(
        select(PlaySession)
        .order_by(PlaySession.id.desc())
        .limit(200)
        .options(joinedload(PlaySession.station), selectinload(PlaySession.items), selectinload(PlaySession.events))
    ))
    mode_row = db.get(SystemSetting, "timed_session_expiry_mode")
    stop_at_zero = (mode_row.value if mode_row else "STOP_AND_WAIT_PAYMENT") == "STOP_AND_WAIT_PAYMENT"
    payload = []
    for session in rows:
        if stop_at_zero and session.session_type == "TIMED" and session.status == "RUNNING":
            if expire_timed_session(db, session):
                _run_power_job("power-off", _background_power_off, session.station_id)
        payload.append({
            "station": session.station.code,
            **session_snapshot(session, session.ended_at if session.status == "ENDED" else None),
        })
    return payload


# ---- Dashboards / reports ------------------------------------------------

def _date_bounds(date_from: str | None, date_to: str | None) -> tuple[datetime, datetime]:
    try:
        start_date = date_type.fromisoformat(date_from) if date_from else datetime.now(CAIRO).date()
        end_date = date_type.fromisoformat(date_to) if date_to else start_date
    except ValueError:
        raise HTTPException(422, "Dates must use YYYY-MM-DD")
    if end_date < start_date:
        raise HTTPException(422, "date_to must not be before date_from")
    start = datetime.combine(start_date, time.min, tzinfo=CAIRO).astimezone(timezone.utc)
    end = datetime.combine(end_date, time.max, tzinfo=CAIRO).astimezone(timezone.utc)
    return start, end


def _invoices_between(db: Session, start: datetime, end: datetime) -> list[Invoice]:
    return list(db.scalars(
        select(Invoice)
        .where(Invoice.created_at >= start, Invoice.created_at <= end)
        .order_by(Invoice.id)
        .options(
            joinedload(Invoice.session).selectinload(PlaySession.items),
            joinedload(Invoice.session).selectinload(PlaySession.events),
        )
    ))


def _dashboard_data(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    start, end = _date_bounds(None, None)
    enabled_stations = int(db.scalar(
        select(func.count()).select_from(Station).where(Station.is_enabled == True)
    ) or 0)
    active = int(db.scalar(
        select(func.count()).select_from(PlaySession).where(
            PlaySession.status.in_(["RUNNING", "PAUSED", "EXPIRED"])
        )
    ) or 0)
    invoice_row = db.execute(
        select(
            func.count(Invoice.id),
            func.coalesce(func.sum(Invoice.amount_piasters), 0),
            func.coalesce(func.sum(Invoice.gameplay_amount_piasters), 0),
            func.coalesce(func.sum(Invoice.products_amount_piasters), 0),
            func.coalesce(func.sum(Invoice.play_seconds), 0),
            func.coalesce(func.sum(Invoice.multi_amount_piasters), 0),
            func.coalesce(func.sum(case((Invoice.payment_method == "CASH", Invoice.amount_piasters), else_=0)), 0),
            func.coalesce(func.sum(case((Invoice.payment_method == "INSTAPAY", Invoice.amount_piasters), else_=0)), 0),
            func.coalesce(func.sum(case((Invoice.payment_method == "VISA", Invoice.amount_piasters), else_=0)), 0),
        ).where(Invoice.created_at >= start, Invoice.created_at <= end)
    ).one()
    return {
        "active_stations": active,
        "total_stations": enabled_stations,
        "available_stations": max(0, enabled_stations - active),
        "today_sales_piasters": int(invoice_row[1] or 0),
        "today_gameplay_piasters": int(invoice_row[2] or 0),
        "today_products_piasters": int(invoice_row[3] or 0),
        "today_multi_piasters": int(invoice_row[5] or 0),
        "today_cash_piasters": int(invoice_row[6] or 0),
        "today_instapay_piasters": int(invoice_row[7] or 0),
        "today_visa_piasters": int(invoice_row[8] or 0),
        "today_sessions": int(invoice_row[0] or 0),
        "today_gameplay_seconds": int(invoice_row[4] or 0),
        "open_shifts": int(db.scalar(
            select(func.count()).select_from(Shift).where(Shift.status == "OPEN")
        ) or 0),
        "ui_config": _ui_config(db),
        "payment_methods": _payment_methods_config(db),
        "timed_session": _timed_session_config(db),
        "server_time": now,
    }


@app.get("/api/dashboard/summary")
def dashboard_summary(user: User = Depends(ready_user), db: Session = Depends(get_db)):
    return _dashboard_data(db)


@app.get("/api/reports/today")
def report_today(user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return _dashboard_data(db)


@app.get("/api/reports/summary")
def report_summary(date_from: str | None = None, date_to: str | None = None,
                   user: User = Depends(admin_user), db: Session = Depends(get_db)):
    start, end = _date_bounds(date_from, date_to)
    invs = _invoices_between(db, start, end)
    invoice_ids = {i.id for i in invs}
    sessions_rows = [i.session for i in invs]
    sales = {
        "invoice_count": len(invs),
        "total_revenue_piasters": sum(i.amount_piasters for i in invs),
        "gameplay_revenue_piasters": sum(i.gameplay_amount_piasters for i in invs),
        "base_gameplay_revenue_piasters": sum(i.base_gameplay_amount_piasters for i in invs),
        "multi_revenue_piasters": sum(i.multi_amount_piasters for i in invs),
        "multi_3_seconds": sum(i.multi_3_seconds for i in invs),
        "multi_3_revenue_piasters": sum(i.multi_3_amount_piasters for i in invs),
        "multi_4_seconds": sum(i.multi_4_seconds for i in invs),
        "multi_4_revenue_piasters": sum(i.multi_4_amount_piasters for i in invs),
        "product_revenue_piasters": sum(i.products_amount_piasters for i in invs),
        "cash_piasters": sum(i.amount_piasters for i in invs if i.payment_method == "CASH"),
        "instapay_piasters": sum(i.amount_piasters for i in invs if i.payment_method == "INSTAPAY"),
        "visa_piasters": sum(i.amount_piasters for i in invs if i.payment_method == "VISA"),
    }
    station_rows = []
    for station in db.scalars(select(Station).order_by(Station.code)):
        station_invoices = [i for i in invs if i.session.station_id == station.id]
        station_sessions = [i.session for i in station_invoices]
        station_rows.append({
            "station": station.code,
            "sessions": len(station_invoices),
            "physical_seconds": sum(session_totals(s, s.ended_at)["elapsed_seconds"] for s in station_sessions),
            "billable_seconds": sum(i.play_seconds for i in station_invoices),
            "gameplay_revenue_piasters": sum(i.gameplay_amount_piasters for i in station_invoices),
            "multi_revenue_piasters": sum(i.multi_amount_piasters for i in station_invoices),
            "multi_3_seconds": sum(i.multi_3_seconds for i in station_invoices),
            "multi_4_seconds": sum(i.multi_4_seconds for i in station_invoices),
            "average_session_seconds": round(sum(session_totals(s, s.ended_at)["elapsed_seconds"] for s in station_sessions) / len(station_sessions)) if station_sessions else 0,
        })
    product_totals: dict[str, dict] = {}
    for inv in invs:
        for item in inv.session.items:
            row = product_totals.setdefault(item.product_name, {"product": item.product_name, "quantity": 0, "revenue_piasters": 0})
            row["quantity"] += item.quantity
            row["revenue_piasters"] += item.quantity * item.unit_price_piasters
    employee_rows = []
    for employee in db.scalars(select(User).order_by(User.username)):
        issued = [i for i in invs if i.issued_by_user_id == employee.id]
        opened_sessions = [s for s in sessions_rows if s.opened_by_user_id == employee.id]
        ended_sessions = [s for s in sessions_rows if s.closed_by_user_id == employee.id]
        shifts = [s for s in db.scalars(select(Shift).where(Shift.employee_id == employee.id))
                  if start <= normalize_utc(s.opened_at) <= end]
        employee_rows.append({
            "employee": employee.display_name or employee.username,
            "username": employee.username,
            "shifts": len(shifts),
            "invoices": len(issued),
            "sessions_started": len(opened_sessions),
            "sessions_ended": len(ended_sessions),
            "total_collected_piasters": sum(i.amount_piasters for i in issued),
            "cash_difference_piasters": sum(s.cash_difference_piasters or 0 for s in shifts if s.status == "CLOSED"),
        })
    shift_rows = [shift_snapshot(db, shift) for shift in db.scalars(select(Shift).order_by(Shift.id.desc()))
                  if start <= normalize_utc(shift.opened_at) <= end]
    multi_rows = [
        {
            "controller_count": 3,
            "seconds": sales["multi_3_seconds"],
            "revenue_piasters": sales["multi_3_revenue_piasters"],
            "invoice_count": sum(1 for i in invs if i.multi_3_seconds > 0),
        },
        {
            "controller_count": 4,
            "seconds": sales["multi_4_seconds"],
            "revenue_piasters": sales["multi_4_revenue_piasters"],
            "invoice_count": sum(1 for i in invs if i.multi_4_seconds > 0),
        },
    ]
    settlement_rows = []
    for row in db.scalars(
        select(DrawerSettlement)
        .where(DrawerSettlement.settled_at >= start, DrawerSettlement.settled_at <= end)
        .order_by(DrawerSettlement.id.desc())
        .options(joinedload(DrawerSettlement.employee), joinedload(DrawerSettlement.closed_by))
    ):
        settlement_rows.append({
            "settlement_number": row.id,
            "shift_id": row.shift_id,
            "shift_opened_at": normalize_utc(row.shift_opened_at),
            "settled_at": normalize_utc(row.settled_at),
            "employee": row.employee.display_name or row.employee.username,
            "username": row.employee.username,
            "closed_by": row.closed_by.display_name or row.closed_by.username,
            "closed_by_username": row.closed_by.username,
            "opening_cash_piasters": row.opening_cash_piasters,
            "cash_sales_piasters": row.cash_sales_piasters,
            "cash_in_piasters": row.cash_in_piasters,
            "cash_out_piasters": row.cash_out_piasters,
            "expected_cash_piasters": row.expected_cash_piasters,
            "actual_cash_piasters": row.actual_cash_piasters,
            "cash_difference_piasters": row.cash_difference_piasters,
            "invoice_count": row.invoice_count,
            "active_sessions_at_close": row.active_sessions_at_close,
        })

    handoff_rows = []
    for row in db.scalars(
        select(ShiftHandoff)
        .where(ShiftHandoff.handed_off_at >= start, ShiftHandoff.handed_off_at <= end)
        .order_by(ShiftHandoff.id.desc())
        .options(joinedload(ShiftHandoff.from_user), joinedload(ShiftHandoff.to_user))
    ):
        handoff_rows.append({
            "id": row.id,
            "shift_id": row.shift_id,
            "handed_off_at": normalize_utc(row.handed_off_at),
            "from_employee": row.from_user.display_name or row.from_user.username,
            "from_username": row.from_user.username,
            "to_employee": row.to_user.display_name or row.to_user.username,
            "to_username": row.to_user.username,
        })

    return {"date_from": start, "date_to": end, "sales": sales, "multi": multi_rows, "stations": station_rows,
            "employees": employee_rows, "products": list(product_totals.values()), "shifts": shift_rows,
            "drawer_settlements": settlement_rows, "shift_handoffs": handoff_rows}


@app.get("/api/audit")
def audit_log(user: User = Depends(admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(AuditLog).order_by(AuditLog.id.desc()).limit(500).options(joinedload(AuditLog.user))
    )
    return [{"id": row.id, "created_at": normalize_utc(row.created_at), "username": row.user.username,
             "action": row.action, "entity": row.entity, "entity_id": row.entity_id, "details": row.details}
            for row in rows]



@app.get("/api/root/system-logs")
def root_system_logs(user: User = Depends(root_ready_user), db: Session = Depends(get_db)):
    """ROOT-only operational/audit log view used by the System Logs page."""
    rows = db.scalars(
        select(AuditLog).order_by(AuditLog.id.desc()).limit(500).options(joinedload(AuditLog.user))
    )
    return [{"id": row.id, "created_at": normalize_utc(row.created_at), "username": row.user.username,
             "action": row.action, "entity": row.entity, "entity_id": row.entity_id, "details": row.details}
            for row in rows]

# ---- Backups -------------------------------------------------------------

def _backup_database(db: Session, filename_prefix: str = "playzone") -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{filename_prefix}-{datetime.now(CAIRO).strftime('%Y%m%d-%H%M%S-%f')}.db"
    destination = BACKUP_DIR / name
    raw = db.get_bind().raw_connection()
    try:
        src = getattr(raw, "driver_connection", None) or raw.connection
        with sqlite3.connect(destination) as dest:
            src.backup(dest)
    finally:
        raw.close()
    return destination


def _validate_backup(path: Path) -> None:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            required = {"users", "stations", "play_sessions", "invoices"}
            if not required.issubset(names):
                raise HTTPException(422, "Invalid PlayZone backup")
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or str(integrity[0]).lower() != "ok":
                raise HTTPException(422, "Backup integrity check failed")
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        raise HTTPException(422, f"Invalid SQLite backup: {exc}")


@app.get("/api/backups")
def list_backups(_: User = Depends(admin_user)):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(BACKUP_DIR.glob("*.db"), reverse=True):
        stat = path.stat()
        rows.append({"filename": path.name, "size": stat.st_size,
                     "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc)})
    return rows


@app.post("/api/backups")
def create_backup(user: User = Depends(admin_user), db: Session = Depends(get_db)):
    path = _backup_database(db)
    audit(db, user, "BACKUP_CREATED", "backup", None, f"filename={path.name};size={path.stat().st_size}")
    db.commit()
    return {"filename": path.name, "size": path.stat().st_size}


@app.post("/api/backups/{filename}/restore")
def restore_backup(filename: str, confirm: bool = Query(False), user: User = Depends(admin_user), db: Session = Depends(get_db)):
    if not confirm:
        raise HTTPException(422, "Explicit confirmation is required")
    if Path(filename).name != filename:
        raise HTTPException(400, "Invalid backup filename")
    source = BACKUP_DIR / filename
    if not source.is_file():
        raise HTTPException(404, "Backup not found")
    _validate_backup(source)
    safety = _backup_database(db, "pre-restore")
    raw = db.get_bind().raw_connection()
    try:
        target = getattr(raw, "driver_connection", None) or raw.connection
        with sqlite3.connect(source) as src:
            src.backup(target)
    finally:
        raw.close()
    migrate_existing_database()
    return {"ok": True, "restored": filename, "safety_backup": safety.name, "restart_recommended": True}


# Production UI: when `npm run build` has created frontend/dist, FastAPI serves
# the same local URL for the cashier UI while preserving all /api and /docs routes.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
