from __future__ import annotations

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
    """Start the Voltra subsystem inside the PlayZone backend process.

    The HTTP API is bound to loopback only and is used internally by app.voltra.
    The MTTL TCP listener binds publicly so real smart strips can connect on 10086.
    """
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
        data_path = Path(os.getenv("VOLTRA_DATA_PATH", str(DB_PATH.parent / "voltra.json"))).expanduser().resolve()
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
        except Exception as exc:  # pragma: no cover - defensive shutdown
            print(f"[VOLTRA] HTTP shutdown error: {exc}")
    if mttl is not None:
        try:
            mttl.stop()
        except Exception as exc:  # pragma: no cover - defensive shutdown
            print(f"[VOLTRA] TCP shutdown error: {exc}")
