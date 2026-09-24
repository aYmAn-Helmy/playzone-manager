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
