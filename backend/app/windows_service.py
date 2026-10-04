from __future__ import annotations

import logging
import os
import sys
import subprocess
import threading
import time
from pathlib import Path

import servicemanager
import win32event
import win32service
import win32serviceutil

SERVICE_NAME = "PlayZoneManager"
SERVICE_DISPLAY_NAME = "nourxplay Service"
SERVICE_DESCRIPTION = "nourxplay local session, billing, Voltra and web runtime"


def _program_data() -> Path:
    base = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "PlayZone Manager"
    base.mkdir(parents=True, exist_ok=True)
    (base / "logs").mkdir(parents=True, exist_ok=True)
    return base


def _protect_secure_data(secure_data: Path) -> None:
    if os.name != "nt":
        return
    commands = [
        ["icacls.exe", str(secure_data), "/inheritance:r", "/Q"],
        [
            "icacls.exe",
            str(secure_data),
            "/grant:r",
            "*S-1-5-18:(OI)(CI)F",
            "*S-1-5-32-544:(OI)(CI)F",
            "/Q",
        ],
    ]
    for command in commands:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=15)
        if completed.returncode != 0:
            raise RuntimeError(
                f"Could not secure PlayZone financial data ACL: {' '.join(command)}; "
                f"{completed.stdout} {completed.stderr}"
            )
    # Existing children may have been moved from the legacy ProgramData root and
    # therefore carry their old ACL. Reset them to inherit only the protected
    # SYSTEM/Administrators rules from secure-data.
    for child in secure_data.iterdir():
        completed = subprocess.run(
            ["icacls.exe", str(child), "/reset", "/T", "/C", "/Q"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Could not secure PlayZone data item {child}: "
                f"{completed.stdout} {completed.stderr}"
            )


def _configure_environment() -> Path:
    data = _program_data()
    secure_data = data / "secure-data"
    secure_data.mkdir(parents=True, exist_ok=True)
    _protect_secure_data(secure_data)
    os.environ["PLAYZONE_DB_PATH"] = str(secure_data / "playzone.db")
    os.environ["VOLTRA_DATA_PATH"] = str(secure_data / "voltra.json")
    os.environ["VOLTRA_BASE_URL"] = "http://127.0.0.1:8086"
    os.environ["VOLTRA_EMBEDDED"] = "1"
    os.environ.setdefault("VOLTRA_DEMO", "0")
    os.environ["VOLTRA_TCP_PORT"] = "10086"
    os.environ["VOLTRA_HTTP_PORT"] = "8086"
    os.environ.setdefault("VOLTRA_POLL_INTERVAL", "10")
    os.environ.setdefault("VOLTRA_RESPONSE_TIMEOUT", "3")
    os.environ.setdefault("PLAYZONE_CLOUD_SYNC_ENABLED", "0")
    # Customer installations keep private Tailscale Serve available without
    # requiring a user to open nourxplay or press Enable Remote Access.
    os.environ.setdefault("PLAYZONE_REMOTE_SUPPORT_ALWAYS_ON", "1")
    os.environ.setdefault("PLAYZONE_TAILSCALE_HEADLESS", "1")
    return data


def _configure_logging(data: Path) -> None:
    log_file = data / "logs" / "service.log"
    stream = open(log_file, "a", encoding="utf-8", buffering=1)
    sys.stdout = stream
    sys.stderr = stream
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8")],
        force=True,
    )


class PlayZoneManagerService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY_NAME
    _svc_description_ = SERVICE_DESCRIPTION

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.server = None
        self.server_thread: threading.Thread | None = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self.server is not None:
            self.server.should_exit = True
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        try:
            data = _configure_environment()
            _configure_logging(data)
            logging.info("Starting nourxplay Windows Service")

            import uvicorn

            config = uvicorn.Config(
                "app.main:app",
                host="127.0.0.1",
                port=8000,
                log_level="info",
                access_log=False,
            )
            self.server = uvicorn.Server(config)
            self.server.install_signal_handlers = lambda: None

            def run_server():
                try:
                    self.server.run()
                except Exception:
                    logging.exception("Local web runtime crashed")
                    win32event.SetEvent(self.stop_event)

            self.server_thread = threading.Thread(target=run_server, name="playzone-web", daemon=True)
            self.server_thread.start()

            def tailscale_watchdog():
                from app.tailscale_support import ensure_always_on
                while win32event.WaitForSingleObject(self.stop_event, 60000) != win32event.WAIT_OBJECT_0:
                    try:
                        status = ensure_always_on()
                        logging.info(
                            "Tailscale watchdog: installed=%s connected=%s daemon_always_on=%s serve_active=%s remote_policy=%s",
                            status.get("installed"),
                            status.get("connected"),
                            status.get("always_on"),
                            status.get("serve_active"),
                            status.get("remote_access_always_on"),
                        )
                    except Exception:
                        logging.exception("Tailscale watchdog recovery failed")

            # Run once immediately, then every minute for automatic recovery.
            try:
                from app.tailscale_support import ensure_always_on
                ensure_always_on()
            except Exception:
                logging.exception("Initial Tailscale always-on check failed")
            threading.Thread(target=tailscale_watchdog, name="tailscale-watchdog", daemon=True).start()

            while self.server_thread.is_alive():
                rc = win32event.WaitForSingleObject(self.stop_event, 1000)
                if rc == win32event.WAIT_OBJECT_0:
                    break

            if self.server is not None:
                self.server.should_exit = True
            if self.server_thread and self.server_thread.is_alive():
                self.server_thread.join(timeout=15)
            logging.info("nourxplay Windows Service stopped")
        except Exception:
            try:
                logging.exception("nourxplay service failed")
            except Exception:
                pass
            servicemanager.LogErrorMsg("nourxplay service failed; see service.log")
            raise


if __name__ == "__main__":
    _configure_environment()
    win32serviceutil.HandleCommandLine(PlayZoneManagerService)
