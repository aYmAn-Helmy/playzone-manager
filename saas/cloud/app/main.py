from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import get_db, init_db
from .materializer import apply_edge_event
from .models import Branch, CloudInvoice, CloudSession, CloudStation, CloudUser, EdgeDevice, EdgeEvent, InstallationCode, Tenant, UserToken
from .schemas import (
    CustomerUserCreate,
    EdgeActivateRequest,
    EdgeEventsRequest,
    EdgeHeartbeatRequest,
    InstallationCodeCreate,
    LoginRequest,
    PasswordChange,
    TenantCreate,
    TenantStatusUpdate,
    UserPasswordUpdate,
    UserStatusUpdate,
)
from .security import future, hash_password, new_secret, not_expired, secret_hash, utcnow, verify_password
from .webui import CUSTOMER_PORTAL_HTML, PLATFORM_ADMIN_HTML

APP_VERSION = "saas-v1.0"
USER_TOKEN_HOURS = 12
bearer = HTTPBearer(auto_error=False)


def _tenant_code(tenant_id: int) -> str:
    return f"PZM-{tenant_id:04d}"


def _public_user(user: CloudUser) -> dict:
    return {
        "id": user.id,
        "tenant_id": user.tenant_id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
    }


def _bootstrap_platform_admin(db: Session) -> None:
    username = os.getenv("PLAYZONE_PLATFORM_ADMIN_USERNAME", "").strip()
    password = os.getenv("PLAYZONE_PLATFORM_ADMIN_PASSWORD", "")
    if not username or not password:
        return
    existing = db.scalar(
        select(CloudUser).where(
            CloudUser.tenant_id.is_(None),
            func.lower(CloudUser.username) == username.lower(),
        )
    )
    if existing:
        return
    db.add(
        CloudUser(
            tenant_id=None,
            username=username,
            display_name="PlayZone Platform Admin",
            password_hash=hash_password(password),
            role="PLATFORM_ADMIN",
        )
    )
    db.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    db = next(get_db())
    try:
        _bootstrap_platform_admin(db)
    finally:
        db.close()
    yield


app = FastAPI(title="PlayZone Manager Cloud", version=APP_VERSION, lifespan=lifespan)


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> CloudUser:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="authentication required")
    row = db.scalar(select(UserToken).where(UserToken.token_hash == secret_hash(credentials.credentials)))
    if not row or not not_expired(row.expires_at):
        raise HTTPException(status_code=401, detail="invalid or expired token")
    user = db.get(CloudUser, row.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="user disabled")
    if user.tenant_id is not None:
        tenant = db.get(Tenant, user.tenant_id)
        if not tenant or tenant.status != "ACTIVE":
            raise HTTPException(status_code=403, detail="customer account inactive")
    return user


def require_platform_admin(user: Annotated[CloudUser, Depends(current_user)]) -> CloudUser:
    if user.role != "PLATFORM_ADMIN" or user.tenant_id is not None:
        raise HTTPException(status_code=403, detail="platform admin required")
    return user


def require_customer_user(user: Annotated[CloudUser, Depends(current_user)]) -> CloudUser:
    if user.tenant_id is None or user.role not in {"OWNER", "MANAGER", "CASHIER"}:
        raise HTTPException(status_code=403, detail="customer user required")
    return user


def require_customer_owner(user: Annotated[CloudUser, Depends(current_user)]) -> CloudUser:
    if user.tenant_id is None or user.role != "OWNER":
        raise HTTPException(status_code=403, detail="customer owner required")
    return user


def current_edge(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    x_device_id: Annotated[str | None, Header(alias="X-Device-ID")] = None,
) -> EdgeDevice:
    if not authorization or not authorization.lower().startswith("bearer ") or not x_device_id:
        raise HTTPException(status_code=401, detail="device authentication required")
    raw = authorization.split(" ", 1)[1].strip()
    edge = db.get(EdgeDevice, x_device_id)
    if not edge or edge.status != "ACTIVE" or edge.revoked_at is not None:
        raise HTTPException(status_code=401, detail="device disabled or unknown")
    if not secrets.compare_digest(edge.token_hash, secret_hash(raw)):
        raise HTTPException(status_code=401, detail="invalid device token")
    tenant = db.get(Tenant, edge.tenant_id)
    if not tenant or tenant.status != "ACTIVE":
        raise HTTPException(status_code=403, detail="customer account inactive")
    return edge


@app.get("/", response_class=HTMLResponse)
def customer_portal() -> HTMLResponse:
    return HTMLResponse(CUSTOMER_PORTAL_HTML)


@app.get("/platform", response_class=HTMLResponse)
def platform_dashboard() -> HTMLResponse:
    return HTMLResponse(PLATFORM_ADMIN_HTML)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "playzone-cloud", "version": APP_VERSION}


@app.post("/api/auth/login")
def login(body: LoginRequest, db: Annotated[Session, Depends(get_db)]) -> dict:
    query = select(CloudUser).where(func.lower(CloudUser.username) == body.username.lower())
    if body.customer_code:
        tenant = db.scalar(select(Tenant).where(func.lower(Tenant.code) == body.customer_code.lower()))
        if not tenant:
            raise HTTPException(status_code=401, detail="invalid credentials")
        query = query.where(CloudUser.tenant_id == tenant.id)
    else:
        query = query.where(CloudUser.tenant_id.is_(None))
    user = db.scalar(query)
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")
    if user.tenant_id is not None:
        tenant = db.get(Tenant, user.tenant_id)
        if not tenant or tenant.status != "ACTIVE":
            raise HTTPException(status_code=403, detail="customer account inactive")
    raw = new_secret()
    db.add(UserToken(token_hash=secret_hash(raw), user_id=user.id, expires_at=future(USER_TOKEN_HOURS)))
    db.commit()
    return {"token": raw, "token_type": "bearer", "user": _public_user(user)}


@app.get("/api/auth/me")
def me(user: Annotated[CloudUser, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> dict:
    tenant = db.get(Tenant, user.tenant_id) if user.tenant_id else None
    return {
        "user": _public_user(user),
        "customer": None if not tenant else {"id": tenant.id, "code": tenant.code, "name": tenant.name},
    }


@app.post("/api/auth/change-password")
def change_password(
    body: PasswordChange,
    user: Annotated[CloudUser, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    managed = db.get(CloudUser, user.id)
    if not managed or not verify_password(body.current_password, managed.password_hash):
        raise HTTPException(status_code=401, detail="current password is incorrect")
    managed.password_hash = hash_password(body.new_password)
    # Revoke every existing login token after a password change.
    for token in db.scalars(select(UserToken).where(UserToken.user_id == managed.id)).all():
        db.delete(token)
    db.commit()
    return {"ok": True}


@app.post("/api/admin/tenants", status_code=status.HTTP_201_CREATED)
def create_tenant(
    body: TenantCreate,
    admin: Annotated[CloudUser, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    tenant = Tenant(code=f"PENDING-{secrets.token_hex(6)}", name=body.name.strip(), status="ACTIVE")
    db.add(tenant)
    db.flush()
    tenant.code = _tenant_code(tenant.id)
    branch = Branch(tenant_id=tenant.id, code="MAIN", name="Main Branch")
    db.add(branch)
    db.flush()
    owner = CloudUser(
        tenant_id=tenant.id,
        username=body.owner_username.strip(),
        display_name=body.owner_display_name,
        password_hash=hash_password(body.owner_password),
        role="OWNER",
    )
    db.add(owner)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="customer or username already exists")
    return {
        "customer": {"id": tenant.id, "code": tenant.code, "name": tenant.name, "status": tenant.status},
        "branch": {"id": branch.id, "code": branch.code, "name": branch.name},
        "owner": _public_user(owner),
    }


@app.put("/api/admin/tenants/{tenant_id}/status")
def set_tenant_status(
    tenant_id: int,
    body: TenantStatusUpdate,
    admin: Annotated[CloudUser, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="customer not found")
    tenant.status = body.status
    db.commit()
    return {"id": tenant.id, "code": tenant.code, "status": tenant.status}


@app.put("/api/admin/tenants/{tenant_id}/owner-password")
def reset_owner_password(
    tenant_id: int,
    body: UserPasswordUpdate,
    admin: Annotated[CloudUser, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    owner = db.scalar(
        select(CloudUser).where(
            CloudUser.tenant_id == tenant_id,
            CloudUser.role == "OWNER",
        ).order_by(CloudUser.id)
    )
    if not owner:
        raise HTTPException(status_code=404, detail="customer owner not found")
    owner.password_hash = hash_password(body.password)
    for token in db.scalars(select(UserToken).where(UserToken.user_id == owner.id)).all():
        db.delete(token)
    db.commit()
    return {"ok": True, "owner_user_id": owner.id}


@app.get("/api/admin/tenants")
def list_tenants(
    admin: Annotated[CloudUser, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    tenants = db.scalars(select(Tenant).order_by(Tenant.id)).all()
    result = []
    for tenant in tenants:
        branch = db.scalar(select(Branch).where(Branch.tenant_id == tenant.id).order_by(Branch.id))
        edges = db.scalars(select(EdgeDevice).where(EdgeDevice.tenant_id == tenant.id)).all()
        seen_count = sum(1 for edge in edges if edge.status == "ACTIVE" and edge.last_seen_at is not None)
        result.append(
            {
                "id": tenant.id,
                "code": tenant.code,
                "name": tenant.name,
                "status": tenant.status,
                "branch": None if not branch else {"id": branch.id, "name": branch.name},
                "edge_devices": len(edges),
                "edge_seen": seen_count,
            }
        )
    return {"customers": result}


@app.post("/api/admin/tenants/{tenant_id}/installation-codes")
def create_installation_code(
    tenant_id: int,
    body: InstallationCodeCreate,
    admin: Annotated[CloudUser, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="customer not found")
    branch = db.scalar(
        select(Branch).where(Branch.tenant_id == tenant_id, Branch.is_active.is_(True)).order_by(Branch.id)
    )
    if not branch:
        raise HTTPException(status_code=409, detail="active branch not found")
    raw = "PZM-" + new_secret(12).replace("_", "").replace("-", "").upper()[:16]
    code = InstallationCode(
        tenant_id=tenant.id,
        branch_id=branch.id,
        code_hash=secret_hash(raw),
        expires_at=future(body.expires_hours),
        created_by_user_id=admin.id,
    )
    db.add(code)
    db.commit()
    return {"installation_code": raw, "expires_at": code.expires_at, "customer_code": tenant.code}


@app.get("/api/admin/edge-devices")
def list_edge_devices(
    admin: Annotated[CloudUser, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    rows = db.scalars(select(EdgeDevice).order_by(EdgeDevice.registered_at.desc())).all()
    return {
        "devices": [
            {
                "id": x.id,
                "tenant_id": x.tenant_id,
                "branch_id": x.branch_id,
                "device_name": x.device_name,
                "status": x.status,
                "app_version": x.app_version,
                "last_seen_at": x.last_seen_at,
                "registered_at": x.registered_at,
            }
            for x in rows
        ]
    }


@app.post("/api/admin/edge-devices/{device_id}/revoke")
def revoke_edge(
    device_id: str,
    admin: Annotated[CloudUser, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    edge = db.get(EdgeDevice, device_id)
    if not edge:
        raise HTTPException(status_code=404, detail="device not found")
    edge.status = "REVOKED"
    edge.revoked_at = utcnow()
    db.commit()
    return {"ok": True, "device_id": edge.id, "status": edge.status}


@app.get("/api/customer/users")
def list_customer_users(
    owner: Annotated[CloudUser, Depends(require_customer_owner)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    rows = db.scalars(
        select(CloudUser)
        .where(CloudUser.tenant_id == owner.tenant_id)
        .order_by(CloudUser.role, func.lower(CloudUser.username))
    ).all()
    return {
        "users": [
            {
                **_public_user(item),
                "is_active": item.is_active,
                "created_at": item.created_at,
            }
            for item in rows
        ]
    }


@app.post("/api/customer/users", status_code=status.HTTP_201_CREATED)
def create_customer_user(
    body: CustomerUserCreate,
    owner: Annotated[CloudUser, Depends(require_customer_owner)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    if body.role == "OWNER":
        raise HTTPException(status_code=403, detail="only platform admin may provision the primary owner")
    existing = db.scalar(
        select(CloudUser).where(
            CloudUser.tenant_id == owner.tenant_id,
            func.lower(CloudUser.username) == body.username.strip().lower(),
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="username already exists")
    item = CloudUser(
        tenant_id=owner.tenant_id,
        username=body.username.strip(),
        display_name=body.display_name,
        password_hash=hash_password(body.password),
        role=body.role,
        is_active=True,
    )
    db.add(item)
    db.commit()
    return {**_public_user(item), "is_active": item.is_active, "created_at": item.created_at}


@app.put("/api/customer/users/{user_id}/status")
def set_customer_user_status(
    user_id: int,
    body: UserStatusUpdate,
    owner: Annotated[CloudUser, Depends(require_customer_owner)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    item = db.get(CloudUser, user_id)
    if not item or item.tenant_id != owner.tenant_id:
        raise HTTPException(status_code=404, detail="user not found")
    if item.id == owner.id and not body.is_active:
        raise HTTPException(status_code=409, detail="owner cannot disable own account")
    if item.role == "OWNER" and item.id != owner.id:
        raise HTTPException(status_code=403, detail="cannot manage another owner")
    item.is_active = body.is_active
    if not item.is_active:
        for token in db.scalars(select(UserToken).where(UserToken.user_id == item.id)).all():
            db.delete(token)
    db.commit()
    return {"id": item.id, "is_active": item.is_active}


@app.put("/api/customer/users/{user_id}/password")
def reset_customer_user_password(
    user_id: int,
    body: UserPasswordUpdate,
    owner: Annotated[CloudUser, Depends(require_customer_owner)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    item = db.get(CloudUser, user_id)
    if not item or item.tenant_id != owner.tenant_id:
        raise HTTPException(status_code=404, detail="user not found")
    if item.role == "OWNER" and item.id != owner.id:
        raise HTTPException(status_code=403, detail="cannot manage another owner")
    item.password_hash = hash_password(body.password)
    for token in db.scalars(select(UserToken).where(UserToken.user_id == item.id)).all():
        db.delete(token)
    db.commit()
    return {"ok": True, "id": item.id}


@app.post("/api/edge/activate", status_code=status.HTTP_201_CREATED)
def activate_edge(body: EdgeActivateRequest, db: Annotated[Session, Depends(get_db)]) -> dict:
    code = db.scalar(select(InstallationCode).where(InstallationCode.code_hash == secret_hash(body.installation_code)))
    if not code or code.used_at is not None or not not_expired(code.expires_at):
        raise HTTPException(status_code=401, detail="invalid or expired installation code")
    tenant = db.get(Tenant, code.tenant_id)
    branch = db.get(Branch, code.branch_id)
    if not tenant or tenant.status != "ACTIVE" or not branch or not branch.is_active:
        raise HTTPException(status_code=403, detail="customer or branch inactive")
    duplicate = db.scalar(
        select(EdgeDevice).where(
            EdgeDevice.tenant_id == tenant.id,
            EdgeDevice.machine_fingerprint == body.machine_fingerprint,
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="this machine is already registered")
    device_id = "EDG-" + secrets.token_hex(12).upper()
    token = new_secret(32)
    edge = EdgeDevice(
        id=device_id,
        tenant_id=tenant.id,
        branch_id=branch.id,
        device_name=body.device_name.strip(),
        machine_fingerprint=body.machine_fingerprint,
        token_hash=secret_hash(token),
        status="ACTIVE",
        app_version=body.app_version,
        last_seen_at=utcnow(),
    )
    db.add(edge)
    code.used_at = utcnow()
    db.commit()
    return {
        "device_id": edge.id,
        "device_token": token,
        "customer": {"id": tenant.id, "code": tenant.code, "name": tenant.name},
        "branch": {"id": branch.id, "code": branch.code, "name": branch.name},
    }


@app.post("/api/edge/heartbeat")
def edge_heartbeat(
    body: EdgeHeartbeatRequest,
    edge: Annotated[EdgeDevice, Depends(current_edge)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    managed = db.get(EdgeDevice, edge.id)
    managed.last_seen_at = utcnow()
    if body.app_version:
        managed.app_version = body.app_version
    db.commit()
    return {"ok": True, "server_time": utcnow(), "device_id": edge.id}


@app.get("/api/edge/config")
def edge_config(
    edge: Annotated[EdgeDevice, Depends(current_edge)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    tenant = db.get(Tenant, edge.tenant_id)
    branch = db.get(Branch, edge.branch_id)
    return {
        "customer": {"id": tenant.id, "code": tenant.code, "name": tenant.name},
        "branch": {"id": branch.id, "code": branch.code, "name": branch.name},
        "edge": {"id": edge.id, "device_name": edge.device_name},
        "sync": {"max_batch_events": 500},
    }


@app.post("/api/edge/events")
def ingest_events(
    body: EdgeEventsRequest,
    edge: Annotated[EdgeDevice, Depends(current_edge)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    accepted: list[str] = []
    duplicates: list[str] = []
    for item in body.events:
        existing = db.scalar(
            select(EdgeEvent).where(
                EdgeEvent.edge_device_id == edge.id,
                EdgeEvent.event_id == item.event_id,
            )
        )
        if existing:
            duplicates.append(item.event_id)
            continue
        seq_owner = db.scalar(
            select(EdgeEvent).where(
                EdgeEvent.edge_device_id == edge.id,
                EdgeEvent.sequence == item.sequence,
            )
        )
        if seq_owner:
            raise HTTPException(status_code=409, detail=f"sequence {item.sequence} already belongs to another event")
        db.add(
            EdgeEvent(
                tenant_id=edge.tenant_id,
                branch_id=edge.branch_id,
                edge_device_id=edge.id,
                event_id=item.event_id,
                sequence=item.sequence,
                event_type=item.event_type,
                session_ref=item.session_ref,
                occurred_at=item.occurred_at,
                payload=item.payload,
            )
        )
        apply_edge_event(
            db,
            edge,
            event_type=item.event_type,
            session_ref=item.session_ref,
            occurred_at=item.occurred_at,
            payload=item.payload,
        )
        accepted.append(item.event_id)
    managed = db.get(EdgeDevice, edge.id)
    managed.last_seen_at = utcnow()
    db.commit()
    return {"accepted": accepted, "duplicates": duplicates}


@app.get("/api/customer/overview")
def customer_overview(
    user: Annotated[CloudUser, Depends(require_customer_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    tenant = db.get(Tenant, user.tenant_id)
    branch = db.scalar(select(Branch).where(Branch.tenant_id == user.tenant_id).order_by(Branch.id))
    edges = db.scalars(select(EdgeDevice).where(EdgeDevice.tenant_id == user.tenant_id)).all()
    stations = db.scalars(
        select(CloudStation)
        .where(CloudStation.tenant_id == user.tenant_id)
        .order_by(CloudStation.code, CloudStation.source_station_id)
    ).all()
    active_sessions = db.scalars(
        select(CloudSession)
        .where(
            CloudSession.tenant_id == user.tenant_id,
            CloudSession.status.in_(["RUNNING", "PAUSED", "EXPIRED"]),
        )
        .order_by(CloudSession.last_event_at.desc())
    ).all()
    invoice_row = db.execute(
        select(
            func.count(CloudInvoice.id),
            func.coalesce(func.sum(CloudInvoice.amount_piasters), 0),
            func.coalesce(func.sum(CloudInvoice.multi_amount_piasters), 0),
            func.coalesce(func.sum(CloudInvoice.multi_3_seconds), 0),
            func.coalesce(func.sum(CloudInvoice.multi_4_seconds), 0),
        ).where(CloudInvoice.tenant_id == user.tenant_id)
    ).one()
    event_count = db.scalar(select(func.count(EdgeEvent.id)).where(EdgeEvent.tenant_id == user.tenant_id)) or 0
    return {
        "customer": {"id": tenant.id, "code": tenant.code, "name": tenant.name},
        "branch": None if not branch else {"id": branch.id, "name": branch.name},
        "edge_devices": [
            {
                "id": x.id,
                "device_name": x.device_name,
                "status": x.status,
                "app_version": x.app_version,
                "last_seen_at": x.last_seen_at,
            }
            for x in edges
        ],
        "stations": [
            {
                "source_station_id": x.source_station_id,
                "code": x.code,
                "power_state": x.power_state,
                "last_event_at": x.last_event_at,
            }
            for x in stations
        ],
        "active_sessions": [
            {
                "session_ref": x.local_session_ref,
                "station_id": x.source_station_id,
                "station_code": x.station_code,
                "status": x.status,
                "session_type": x.session_type,
                "controller_count": x.controller_count,
                "hourly_rate_piasters": x.hourly_rate_piasters,
                "started_at": x.started_at,
                "ended_at": x.ended_at,
                "timed_total_seconds": x.timed_total_seconds,
                "timed_remaining_seconds": x.timed_remaining_seconds,
                "multi_3_billable_seconds": x.multi_3_billable_seconds,
                "multi_4_billable_seconds": x.multi_4_billable_seconds,
                "last_event_at": x.last_event_at,
            }
            for x in active_sessions
        ],
        "sales_summary": {
            "invoice_count": int(invoice_row[0] or 0),
            "sales_piasters": int(invoice_row[1] or 0),
            "multi_revenue_piasters": int(invoice_row[2] or 0),
            "multi_3_seconds": int(invoice_row[3] or 0),
            "multi_4_seconds": int(invoice_row[4] or 0),
        },
        "received_events": int(event_count),
    }
