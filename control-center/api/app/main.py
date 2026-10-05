from __future__ import annotations

import os
import platform
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Base, SessionLocal, engine
from .models import Device, EnrollmentCode
from .security import hash_secret, new_secret, require_admin

CONTROL_CENTER_VERSION = "0.1.0"
OFFLINE_SECONDS = max(30, int(os.environ.get("DEVICE_OFFLINE_SECONDS", "180")))
HEARTBEAT_INTERVAL = max(15, int(os.environ.get("HEARTBEAT_INTERVAL_SECONDS", "60")))

app = FastAPI(title="nourxplay Control Center", version=CONTROL_CENTER_VERSION)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(engine)


class EnrollmentCreate(BaseModel):
    customer_name: str = Field(default="", max_length=160)
    site_name: str = Field(default="", max_length=160)
    ttl_minutes: int = Field(default=60, ge=5, le=1440)


class EnrollRequest(BaseModel):
    enrollment_code: str = Field(min_length=8, max_length=200)
    installation_id: str = Field(min_length=8, max_length=120)
    hostname: str = Field(default="", max_length=160)
    app_version: str = Field(default="", max_length=40)
    os_version: str = Field(default="", max_length=160)


class HeartbeatRequest(BaseModel):
    installation_id: str = Field(min_length=8, max_length=120)
    hostname: str = Field(default="", max_length=160)
    app_version: str = Field(default="", max_length=40)
    os_version: str = Field(default="", max_length=160)
    tailscale_ipv4: str | None = Field(default=None, max_length=64)
    tailscale_dns_name: str | None = Field(default=None, max_length=255)
    remote_url: str | None = Field(default=None, max_length=1000)
    tailscale_connected: bool = False
    serve_active: bool = False


def _device_from_auth(authorization: str | None, db: Session) -> Device:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing device token")
    raw = authorization.split(" ", 1)[1].strip()
    if not raw:
        raise HTTPException(401, "Missing device token")
    device = db.scalar(select(Device).where(Device.token_hash == hash_secret(raw)))
    if device is None:
        raise HTTPException(401, "Invalid device token")
    return device


def _device_out(device: Device) -> dict:
    now = datetime.now(timezone.utc)
    last_seen = device.last_seen_at
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    online = (now - last_seen).total_seconds() <= OFFLINE_SECONDS
    return {
        "id": device.id,
        "installation_id": device.installation_id,
        "customer_name": device.customer_name,
        "site_name": device.site_name,
        "hostname": device.hostname,
        "app_version": device.app_version,
        "os_version": device.os_version,
        "tailscale_ipv4": device.tailscale_ipv4,
        "tailscale_dns_name": device.tailscale_dns_name,
        "remote_url": device.remote_url,
        "tailscale_connected": device.tailscale_connected,
        "serve_active": device.serve_active,
        "online": online,
        "first_seen_at": device.first_seen_at,
        "last_seen_at": device.last_seen_at,
    }


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "nourxplay-control-center",
        "version": CONTROL_CENTER_VERSION,
        "time": datetime.now(timezone.utc),
    }


@app.post("/api/admin/enrollment-codes", dependencies=[Depends(require_admin)])
def create_enrollment(payload: EnrollmentCreate, db: Session = Depends(get_db)) -> dict:
    raw = new_secret("nxc_", 18)
    now = datetime.now(timezone.utc)
    row = EnrollmentCode(
        code_hash=hash_secret(raw),
        customer_name=payload.customer_name.strip(),
        site_name=payload.site_name.strip(),
        created_at=now,
        expires_at=now + timedelta(minutes=payload.ttl_minutes),
    )
    db.add(row)
    db.commit()
    return {
        "enrollment_code": raw,
        "customer_name": row.customer_name,
        "site_name": row.site_name,
        "expires_at": row.expires_at,
    }


@app.get("/api/admin/devices", dependencies=[Depends(require_admin)])
def admin_devices(db: Session = Depends(get_db)) -> list[dict]:
    devices = list(db.scalars(select(Device).order_by(Device.last_seen_at.desc())))
    return [_device_out(device) for device in devices]


@app.post("/api/device/enroll")
def enroll_device(payload: EnrollRequest, db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    code = db.scalar(
        select(EnrollmentCode).where(
            EnrollmentCode.code_hash == hash_secret(payload.enrollment_code)
        )
    )
    if code is None or code.used_at is not None:
        raise HTTPException(409, "Invalid or already used enrollment code")

    expires = code.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= now:
        raise HTTPException(409, "Enrollment code expired")

    existing = db.scalar(
        select(Device).where(Device.installation_id == payload.installation_id)
    )
    device_token = new_secret("nxd_", 32)
    if existing is None:
        device = Device(
            id=str(uuid.uuid4()),
            installation_id=payload.installation_id,
            token_hash=hash_secret(device_token),
            customer_name=code.customer_name,
            site_name=code.site_name,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(device)
    else:
        device = existing
        device.token_hash = hash_secret(device_token)
        device.customer_name = code.customer_name or device.customer_name
        device.site_name = code.site_name or device.site_name
        device.last_seen_at = now

    device.hostname = payload.hostname.strip()
    device.app_version = payload.app_version.strip()
    device.os_version = payload.os_version.strip()
    code.used_at = now
    db.commit()

    return {
        "device_id": device.id,
        "device_token": device_token,
        "heartbeat_interval_seconds": HEARTBEAT_INTERVAL,
        "control_center_version": CONTROL_CENTER_VERSION,
    }


@app.post("/api/device/heartbeat")
def heartbeat(
    payload: HeartbeatRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    device = _device_from_auth(authorization, db)
    if device.installation_id != payload.installation_id:
        raise HTTPException(409, "installation_id does not match token")

    device.hostname = payload.hostname.strip()
    device.app_version = payload.app_version.strip()
    device.os_version = payload.os_version.strip()
    device.tailscale_ipv4 = payload.tailscale_ipv4
    device.tailscale_dns_name = payload.tailscale_dns_name
    device.remote_url = payload.remote_url
    device.tailscale_connected = payload.tailscale_connected
    device.serve_active = payload.serve_active
    device.last_seen_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "ok": True,
        "heartbeat_interval_seconds": HEARTBEAT_INTERVAL,
        "server_time": datetime.now(timezone.utc),
    }


DASHBOARD = """<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>nourxplay Control Center</title>
<style>
:root{color-scheme:dark;font-family:Segoe UI,Tahoma,Arial,sans-serif}
body{margin:0;background:#07111f;color:#eef6ff}
main{max-width:1200px;margin:auto;padding:28px}
h1{margin:0 0 6px}.sub{color:#91a8c0;margin-bottom:24px}
.toolbar,.stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px}
input,button{background:#0d1d2e;color:#eef6ff;border:1px solid #24486b;border-radius:10px;padding:10px 12px}
button{cursor:pointer;background:#1677e8;font-weight:700}
.card{background:#0d1d2e;border:1px solid #1e4163;border-radius:14px;padding:16px;margin:10px 0}
.row{display:flex;gap:14px;justify-content:space-between;flex-wrap:wrap}
.badge{border-radius:999px;padding:5px 9px;font-size:12px;background:#18304a}
.online{background:#123f2a;color:#9bf3bd}.offline{background:#472327;color:#ffb1b8}.warn{background:#4a3716;color:#ffd98a}
small{color:#91a8c0} a{color:#69b6ff}
pre{white-space:pre-wrap}
</style>
</head>
<body><main>
<h1>nourxplay Control Center</h1>
<div class="sub">Fleet monitoring — MVP v0.36.0</div>
<div class="toolbar">
<input id="token" type="password" placeholder="Admin Token" style="min-width:280px">
<button onclick="loadDevices()">تحديث الأجهزة</button>
<input id="customer" placeholder="اسم العميل">
<input id="site" placeholder="الفرع">
<button onclick="newCode()">Enrollment Code جديد</button>
</div>
<div id="message"></div>
<div id="devices"></div>
<script>
const tokenEl=document.getElementById('token');
tokenEl.value=sessionStorage.getItem('nxc_admin')||'';
function headers(){sessionStorage.setItem('nxc_admin',tokenEl.value);return {'X-Admin-Token':tokenEl.value,'Content-Type':'application/json'}}
function esc(x){return String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function loadDevices(){
 const r=await fetch('/api/admin/devices',{headers:headers()}); if(!r.ok){msg(await r.text());return}
 const rows=await r.json(); if(!rows.length){document.getElementById('devices').innerHTML='<div class="card">لا توجد أجهزة مسجلة بعد.</div>';return}
 document.getElementById('devices').innerHTML=rows.map(d=>{
  const state=d.online?'<span class="badge online">ONLINE</span>':'<span class="badge offline">OFFLINE</span>';
  const remote=d.serve_active?'<span class="badge online">REMOTE ✓</span>':'<span class="badge warn">REMOTE —</span>';
  const link=d.remote_url?'<a target="_blank" rel="noreferrer" href="'+esc(d.remote_url)+'">فتح Remote</a>':'';
  return '<div class="card"><div class="row"><strong>'+esc(d.customer_name||d.hostname||d.installation_id)+'</strong><div>'+state+' '+remote+'</div></div>'+
   '<div>'+esc(d.site_name)+' · '+esc(d.hostname)+' · v'+esc(d.app_version||'-')+'</div>'+
   '<small>Tailscale: '+esc(d.tailscale_ipv4||'-')+' · آخر اتصال: '+esc(d.last_seen_at)+'</small><div>'+link+'</div></div>'
 }).join('');
}
async function newCode(){
 const body={customer_name:document.getElementById('customer').value,site_name:document.getElementById('site').value,ttl_minutes:60};
 const r=await fetch('/api/admin/enrollment-codes',{method:'POST',headers:headers(),body:JSON.stringify(body)});
 const t=await r.text(); if(!r.ok){msg(t);return} const j=JSON.parse(t);
 msg('Enrollment Code: '+j.enrollment_code+'\nينتهي: '+j.expires_at);
}
function msg(t){document.getElementById('message').innerHTML='<div class="card"><pre>'+esc(t)+'</pre></div>'}
if(tokenEl.value) loadDevices();
</script>
</main></body></html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return DASHBOARD
