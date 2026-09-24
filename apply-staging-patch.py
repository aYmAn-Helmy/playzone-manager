from pathlib import Path
import shutil

PLAYZONE = Path("/app/playzone")
VOLTRA = Path("/app/voltra")
BACKEND_DIR = PLAYZONE / "backend"
MAIN = BACKEND_DIR / "app" / "main.py"
DIST = PLAYZONE / "frontend" / "dist" / "assets"

# ---------------------------------------------------------------------------
# v0.7: merge Voltra into PlayZone.
# Copy the existing, verified Voltra package inside the PlayZone backend and
# start it from the FastAPI lifecycle. The old /app/voltra tree is removed by
# Dockerfile after this patch completes.
# ---------------------------------------------------------------------------
src_voltra = VOLTRA / "voltra_local"
dst_voltra = BACKEND_DIR / "voltra_local"
if not src_voltra.exists():
    raise RuntimeError("Bundled Voltra source was not found")
if dst_voltra.exists():
    shutil.rmtree(dst_voltra)
shutil.copytree(src_voltra, dst_voltra)

embedded = r'''from __future__ import annotations

import os
import threading
from pathlib import Path

from .db import DB_PATH
from voltra_local.demo_device import run_demo_device
from voltra_local.http_api import start_http
from voltra_local.store import ConfigStore
from voltra_local.tcp_server import MTTLServer


_lock = threading.Lock()
_mttl: MTTLServer | None = None
_http = None
_store: ConfigStore | None = None


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def start_embedded_voltra() -> None:
    """Start Voltra inside the PlayZone backend process."""
    global _mttl, _http, _store
    if not _env_bool("VOLTRA_EMBEDDED", True):
        print("[VOLTRA] embedded subsystem disabled")
        return

    with _lock:
        if _mttl is not None:
            return

        tcp_port = int(os.getenv("VOLTRA_TCP_PORT", "10086"))
        http_port = int(os.getenv("VOLTRA_HTTP_PORT", "8086"))
        poll_interval = float(os.getenv("VOLTRA_POLL_INTERVAL", "10"))
        response_timeout = float(os.getenv("VOLTRA_RESPONSE_TIMEOUT", "3"))
        demo = _env_bool("VOLTRA_DEMO", False)
        api_token = os.getenv("VOLTRA_API_TOKEN", "")
        data_path = Path(
            os.getenv("VOLTRA_DATA_PATH", str(DB_PATH.parent / "voltra.json"))
        ).expanduser().resolve()
        data_path.parent.mkdir(parents=True, exist_ok=True)

        store = ConfigStore(data_path)
        mttl = MTTLServer(
            host="0.0.0.0",
            port=tcp_port,
            poll_interval=poll_interval,
            response_timeout=response_timeout,
            on_device_seen=store.record_strip,
        )
        mttl.start()
        http = start_http(
            mttl,
            "127.0.0.1",
            http_port,
            store=store,
            api_token=api_token,
            cors_origin="http://127.0.0.1",
        )

        if demo:
            threading.Thread(
                target=run_demo_device,
                kwargs={"host": "127.0.0.1", "port": tcp_port},
                daemon=True,
            ).start()
            print("[VOLTRA] demo strip enabled")

        _store = store
        _mttl = mttl
        _http = http
        print(f"[VOLTRA] embedded TCP listening on 0.0.0.0:{tcp_port}")
        print(f"[VOLTRA] internal API listening on 127.0.0.1:{http_port}")
        print(f"[VOLTRA] data={data_path}")


def stop_embedded_voltra() -> None:
    global _mttl, _http, _store
    with _lock:
        http = _http
        mttl = _mttl
        _http = None
        _mttl = None
        _store = None

    if http is not None:
        try:
            http.shutdown()
            http.server_close()
        except Exception as exc:
            print(f"[VOLTRA] HTTP shutdown error: {exc}")
    if mttl is not None:
        try:
            mttl.stop()
        except Exception as exc:
            print(f"[VOLTRA] TCP shutdown error: {exc}")
'''
(BACKEND_DIR / "app" / "embedded_voltra.py").write_text(embedded, encoding="utf-8")

backend = MAIN.read_text(encoding="utf-8")
import_marker = "from .db import BACKUP_DIR, Base, SessionLocal, engine, get_db, migrate_existing_database\n"
embedded_import = "from .embedded_voltra import start_embedded_voltra, stop_embedded_voltra\n"
if embedded_import not in backend:
    if import_marker not in backend:
        raise RuntimeError("Could not locate PlayZone db import")
    backend = backend.replace(import_marker, import_marker + embedded_import, 1)

startup_old = '''@app.on_event("startup")
def on_startup():
    seed_data()
'''
startup_new = '''@app.on_event("startup")
def on_startup():
    seed_data()
    start_embedded_voltra()


@app.on_event("shutdown")
def on_shutdown():
    stop_embedded_voltra()
'''
if "start_embedded_voltra()" not in backend:
    if startup_old not in backend:
        raise RuntimeError("Could not locate PlayZone startup hook")
    backend = backend.replace(startup_old, startup_new, 1)

# ---------------------------------------------------------------------------
# v0.6 permissions: manual Voltra management is ROOT-only at the API layer.
# Automatic Start/End display power remains part of the session workflow.
# ---------------------------------------------------------------------------
root_block = '''def root_user(user: User = Depends(current_user)) -> User:
    if user.role != "ROOT":
        raise HTTPException(403, "Root role required")
    return user
'''
root_ready = root_block + '''

def root_ready_user(user: User = Depends(ready_user)) -> User:
    if user.role != "ROOT":
        raise HTTPException(403, "Root role required")
    return user
'''
if "def root_ready_user(" not in backend:
    if root_block not in backend:
        raise RuntimeError("Could not locate root_user block")
    backend = backend.replace(root_block, root_ready, 1)

route_replacements = {
    "def sync_voltra_devices(actor: User = Depends(admin_user), db: Session = Depends(get_db)):": "def sync_voltra_devices(actor: User = Depends(root_ready_user), db: Session = Depends(get_db)):",
    "def list_voltra_power(_: User = Depends(admin_user), db: Session = Depends(get_db)):": "def list_voltra_power(_: User = Depends(root_ready_user), db: Session = Depends(get_db)):",
    "def get_voltra_power(station_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):": "def get_voltra_power(station_id: int, _: User = Depends(root_ready_user), db: Session = Depends(get_db)):",
    "def change_voltra_power(station_id: int, action: str, actor: User = Depends(admin_user), db: Session = Depends(get_db)):": "def change_voltra_power(station_id: int, action: str, actor: User = Depends(root_ready_user), db: Session = Depends(get_db)):",
}
for old, new in route_replacements.items():
    if old in backend:
        backend = backend.replace(old, new, 1)
    elif new not in backend:
        raise RuntimeError(f"Could not locate backend route: {old}")

# Passwordless development mode must be consistent across login, /auth/me,
# user edits, and frontend refreshes. Otherwise resetting ROOT/ADMIN password
# can leave must_change_password=true and make the dashboard stop loading.
me_old = '''@app.get("/api/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
'''
me_new = '''@app.get("/api/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    payload = UserOut.model_validate(user).model_dump()
    if user.role in ("ROOT", "ADMIN") and passwordless_privileged_enabled(db):
        payload["must_change_password"] = False
    return payload
'''
if me_old in backend:
    backend = backend.replace(me_old, me_new, 1)
elif me_new not in backend:
    raise RuntimeError("Could not patch /api/auth/me passwordless behavior")

password_reset_old = '''    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
        user.must_change_password = True
        changes.append("password reset;must_change_password=true")
'''
password_reset_new = '''    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
        privileged_passwordless = user.role in ("ROOT", "ADMIN") and passwordless_privileged_enabled(db)
        user.must_change_password = False if privileged_passwordless else True
        changes.append(
            "password reset;must_change_password=false"
            if privileged_passwordless
            else "password reset;must_change_password=true"
        )
'''
if password_reset_old in backend:
    backend = backend.replace(password_reset_old, password_reset_new, 1)
elif password_reset_new not in backend:
    raise RuntimeError("Could not patch password reset behavior")

MAIN.write_text(backend, encoding="utf-8")

# ---------------------------------------------------------------------------
# Hide Voltra navigation/view for ADMIN. ROOT keeps the page.
# ---------------------------------------------------------------------------
js_files = list(DIST.glob("*.js"))
if len(js_files) != 1:
    raise RuntimeError(f"Expected one JS asset, found {len(js_files)}")
js_path = js_files[0]
js = js_path.read_text(encoding="utf-8")
js_replacements = {
    "t===`voltra`&&n&&[`ROOT`,`ADMIN`].includes(n.role)".replace("\\", ""): "t===`voltra`&&n?.role===`ROOT`".replace("\\", ""),
    "Ue=He?[`home`,`stations`,`sessions`,`invoices`,`products`,`reports`,`users`,`voltra`,`settings`]:[`home`,`stations`,`sessions`,`invoices`]".replace("\\", ""): "Ue=He?[`home`,`stations`,`sessions`,`invoices`,`products`,`reports`,`users`,`voltra`,`settings`].filter(e=>e!==`voltra`||n?.role===`ROOT`):[`home`,`stations`,`sessions`,`invoices`]".replace("\\", ""),
    "o===`voltra`&&He&&(0,j.jsx)(pt,{devices:ae,run:Le,api:A})".replace("\\", ""): "o===`voltra`&&n?.role===`ROOT`&&(0,j.jsx)(pt,{devices:ae,run:Le,api:A})".replace("\\", ""),
}
for old, new in js_replacements.items():
    if old in js:
        js = js.replace(old, new, 1)
    elif new not in js:
        raise RuntimeError(f"Could not locate frontend marker: {old[:80]}")

# In passwordless development mode, a stale must_change_password flag must not
# suppress station/dashboard requests after a ROOT/ADMIN account edit.
passwordless_guard = '!(n?.must_change_password&&!(i?.passwordless_privileged&&n&&[`ROOT`,`ADMIN`].includes(n.role)))'
frontend_replacements = {
    'e&&!n?.must_change_password&&i?.activated!==!1': f'e&&{passwordless_guard}&&i?.activated!==!1',
    'if(e&&!n?.must_change_password)try': f'if(e&&{passwordless_guard})try',
    'if(!e||!n||n.must_change_password||i?.activated!==!0)return;': f'if(!e||!n||!({passwordless_guard})||i?.activated!==!0)return;',
    'n&&!n.must_change_password&&i?.activated===!0&&Ie(o)': f'n&&{passwordless_guard}&&i?.activated===!0&&Ie(o)',
}
for old, new in frontend_replacements.items():
    if old in js:
        js = js.replace(old, new, 1)
    elif new not in js:
        raise RuntimeError(f"Could not patch passwordless dashboard guard: {old}")

js_path.write_text(js, encoding="utf-8")

# ---------------------------------------------------------------------------
# Readability pass.
# ---------------------------------------------------------------------------
css_files = list(DIST.glob("*.css"))
if len(css_files) != 1:
    raise RuntimeError(f"Expected one CSS asset, found {len(css_files)}")
css_path = css_files[0]
css = css_path.read_text(encoding="utf-8")
readability = r'''
/* PlayZone readability pass v0.6 */
.brand small,.side-caption,.eyebrow,.page-heading p,.clock-card small,
.shift-chip b,.shift-chip small,.stat span,.mini-stat span,.section-title p,
.section-title>span,.status-pill,.station-title span,.grace-banner,
.station-actions .button,.rail-title small,.recent-row strong,.empty-state,
.system-row b,label,.muted,.security-message,.shift-warning span,.login-panel p,
.receipt-head p,.activation-notice span,.machine-card span,.machine-mismatch span,
.activation-status-badge{font-size:12px!important}
.mini-stat strong,.modal-line,.station-total,.text-button,table,.recent-row b,
.activation-settings-grid strong{font-size:12px!important}
.live-dot,.recent-row span,.system-row small{font-size:10px!important}
.activation-settings-grid span,.drawer-formula{font-size:11px!important}
'''
if "PlayZone readability pass v0.6" not in css:
    css += readability
css_path.write_text(css, encoding="utf-8")


# ---------------------------------------------------------------------------
# v0.8: protected online Voltra console on the same PlayZone domain.
# ---------------------------------------------------------------------------
backend2 = MAIN.read_text(encoding="utf-8")
if "def issue_voltra_console_ticket(" not in backend2:
    backend2 = backend2.replace(
        "import sqlite3\nimport secrets\n",
        "import sqlite3\nimport secrets\nimport os\nimport time\nimport httpx\n",
        1,
    )
    backend2 = backend2.replace(
        "from fastapi import Depends, FastAPI, Header, HTTPException, Query\n",
        "from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request\n"
        "from fastapi.responses import RedirectResponse, Response\n",
        1,
    )

    voltra_console_code = r'''
_VOLTRA_CONSOLE_COOKIE = "playzone_voltra_console"
_VOLTRA_CONSOLE_TICKETS: dict[str, float] = {}
_VOLTRA_CONSOLE_SESSIONS: dict[str, float] = {}


def _cleanup_voltra_console(now: float) -> None:
    for store in (_VOLTRA_CONSOLE_TICKETS, _VOLTRA_CONSOLE_SESSIONS):
        for key, expires_at in list(store.items()):
            if expires_at <= now:
                store.pop(key, None)


@app.post("/api/voltra/console-ticket")
def issue_voltra_console_ticket(_: User = Depends(root_ready_user)):
    now = time.time()
    _cleanup_voltra_console(now)
    ticket = secrets.token_urlsafe(32)
    _VOLTRA_CONSOLE_TICKETS[ticket] = now + 60
    return {"url": f"/voltra/authorize?ticket={ticket}"}


@app.get("/voltra/authorize")
def authorize_voltra_console(request: Request, ticket: str = Query(...)):
    now = time.time()
    _cleanup_voltra_console(now)
    expires_at = _VOLTRA_CONSOLE_TICKETS.pop(ticket, None)
    if not expires_at or expires_at <= now:
        raise HTTPException(401, "Invalid or expired Voltra console ticket")

    session_id = secrets.token_urlsafe(32)
    _VOLTRA_CONSOLE_SESSIONS[session_id] = now + 1800
    secure = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"
    )
    response = RedirectResponse(url="/voltra", status_code=303)
    response.set_cookie(
        _VOLTRA_CONSOLE_COOKIE,
        session_id,
        max_age=1800,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/voltra",
    )
    return response


def _require_voltra_console(request: Request) -> None:
    now = time.time()
    _cleanup_voltra_console(now)
    session_id = request.cookies.get(_VOLTRA_CONSOLE_COOKIE)
    expires_at = _VOLTRA_CONSOLE_SESSIONS.get(session_id or "")
    if not expires_at or expires_at <= now:
        raise HTTPException(401, "Open Voltra from the ROOT dashboard")


async def _proxy_voltra_request(request: Request, path: str = "") -> Response:
    _require_voltra_console(request)
    target = "http://127.0.0.1:8086/voltra"
    if path:
        target += "/" + path
    if request.url.query:
        target += "?" + request.url.query

    headers: dict[str, str] = {}
    if request.headers.get("content-type"):
        headers["content-type"] = request.headers["content-type"]
    internal_token = os.getenv("VOLTRA_API_TOKEN", "").strip()
    if internal_token:
        headers["authorization"] = f"Bearer {internal_token}"

    body = await request.body()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            upstream = await client.request(
                request.method,
                target,
                headers=headers,
                content=body if body else None,
            )
    except httpx.RequestError as exc:
        raise HTTPException(503, f"Voltra console unavailable: {exc}") from exc

    response_headers = {}
    content_type = upstream.headers.get("content-type")
    if content_type:
        response_headers["content-type"] = content_type
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )


@app.api_route("/voltra", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_voltra_root(request: Request):
    return await _proxy_voltra_request(request)


@app.api_route("/voltra/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_voltra_path(path: str, request: Request):
    return await _proxy_voltra_request(request, path)
'''
    static_marker = "# Production UI: when `npm run build` has created frontend/dist, FastAPI serves"
    if static_marker not in backend2:
        raise RuntimeError("Could not locate frontend static mount marker for Voltra proxy")
    backend2 = backend2.replace(static_marker, voltra_console_code + "\n\n" + static_marker, 1)
    MAIN.write_text(backend2, encoding="utf-8")

js2 = js_path.read_text(encoding="utf-8")
old_console_link = '(0,j.jsx)(`a`,{className:`button ghost`,href:`http://127.0.0.1:8086/voltra`,target:`_blank`,rel:`noreferrer`,children:`لوحة Voltra`})'
new_console_link = '(0,j.jsx)(`button`,{className:`button ghost`,onClick:()=>{let e=window.open(``,`_blank`);e&&(e.opener=null),t(async()=>{let r=await n(`/voltra/console-ticket`,`POST`);e?e.location.href=r.url:window.location.href=r.url},!1)},children:`لوحة Voltra`})'
if old_console_link in js2:
    js2 = js2.replace(old_console_link, new_console_link, 1)
elif new_console_link not in js2:
    raise RuntimeError("Could not patch Voltra console localhost link")
js_path.write_text(js2, encoding="utf-8")
