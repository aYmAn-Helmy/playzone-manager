from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_TAG = ""
SERVE_TARGET = "http://127.0.0.1:8000"
SERVE_HTTPS_PORT = 443


class TailscaleSupportError(RuntimeError):
    pass


def _remote_support_always_on() -> bool:
    value = os.getenv("PLAYZONE_REMOTE_SUPPORT_ALWAYS_ON", "0").strip().lower()
    return value not in {"", "0", "false", "no", "off"}


def _headless_enabled() -> bool:
    value = os.getenv("PLAYZONE_TAILSCALE_HEADLESS", "0").strip().lower()
    return value not in {"", "0", "false", "no", "off"}


def _creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0


def _find_tailscale() -> str | None:
    found = shutil.which("tailscale") or shutil.which("tailscale.exe")
    if found:
        return found
    if os.name != "nt":
        return None
    candidates: list[Path] = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(env_name)
        if base:
            candidates.append(Path(base) / "Tailscale" / "tailscale.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _run(exe: str, args: list[str], *, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [exe, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=_creation_flags(),
        )
    except subprocess.TimeoutExpired as exc:
        raise TailscaleSupportError("انتهت مهلة تنفيذ أمر Tailscale.") from exc
    except OSError as exc:
        raise TailscaleSupportError(f"تعذر تشغيل Tailscale: {exc}") from exc


def _clean_message(proc: subprocess.CompletedProcess[str]) -> str:
    text = (proc.stderr or proc.stdout or "").strip()
    if not text:
        return f"Tailscale exit code {proc.returncode}"
    return text[-1200:]


def _support_hostname() -> str:
    raw = socket.gethostname().lower()
    safe = re.sub(r"[^a-z0-9-]+", "-", raw).strip("-") or "windows"
    return f"nourxplay-{safe}"[:63]


def _suppress_tray_gui() -> None:
    if os.name != "nt" or not _headless_enabled():
        return
    try:
        subprocess.run(
            ["taskkill.exe", "/F", "/IM", "tailscale-ipn.exe"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=_creation_flags(),
        )
    except Exception:
        pass
    common_startup = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Tailscale.lnk"
    try:
        common_startup.unlink(missing_ok=True)
    except OSError:
        pass


def _service_state() -> str | None:
    if os.name != "nt":
        return None
    try:
        proc = subprocess.run(
            ["sc.exe", "query", "Tailscale"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=_creation_flags(),
        )
    except Exception:
        return None
    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).upper()
    if "RUNNING" in output:
        return "RUNNING"
    if "STOPPED" in output:
        return "STOPPED"
    if proc.returncode != 0:
        return "NOT_FOUND"
    return "UNKNOWN"


def _normalize_proxy_target(value: str | None) -> str:
    return str(value or "").strip().rstrip("/").lower()


def _collect_proxy_targets(value: Any) -> list[str]:
    targets: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() == "proxy" and isinstance(child, str):
                targets.append(child)
            else:
                targets.extend(_collect_proxy_targets(child))
    elif isinstance(value, list):
        for child in value:
            targets.extend(_collect_proxy_targets(child))
    return targets


def _remote_url_from_serve_config(config: dict, dns_name: str | None) -> str | None:
    wanted = _normalize_proxy_target(SERVE_TARGET)
    web = config.get("Web")
    if isinstance(web, dict):
        for endpoint, details in web.items():
            if wanted not in {_normalize_proxy_target(x) for x in _collect_proxy_targets(details)}:
                continue
            host = str(endpoint).strip()
            if host.endswith(":443"):
                host = host[:-4]
            if host:
                return f"https://{host}"
    if dns_name:
        return f"https://{dns_name.rstrip('.')}"
    return None


def _serve_details(exe: str, dns_name: str | None) -> dict:
    details = {
        "serve_active": False,
        "serve_target": SERVE_TARGET,
        "serve_https_port": SERVE_HTTPS_PORT,
        "remote_url": None,
        "serve_status": "INACTIVE",
        "serve_message": None,
    }
    proc = _run(exe, ["serve", "status", "--json"], timeout=8)
    if proc.returncode != 0:
        # A missing Serve configuration is not a Tailscale connection failure.
        details["serve_status"] = "UNKNOWN"
        details["serve_message"] = _clean_message(proc)
        return details
    try:
        config = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        details["serve_status"] = "ERROR"
        details["serve_message"] = "تعذر قراءة حالة Tailscale Serve."
        return details

    targets = {_normalize_proxy_target(x) for x in _collect_proxy_targets(config)}
    active = _normalize_proxy_target(SERVE_TARGET) in targets
    details["serve_active"] = active
    details["serve_status"] = "ACTIVE" if active else "INACTIVE"
    if active:
        details["remote_url"] = _remote_url_from_serve_config(config, dns_name)
    return details


def get_status() -> dict:
    supported = os.name == "nt"
    base = {
        "supported": supported,
        "installed": False,
        "connected": False,
        "needs_login": False,
        "state": "UNSUPPORTED" if not supported else "NOT_INSTALLED",
        "service_state": _service_state(),
        "ipv4": None,
        "dns_name": None,
        "hostname": None,
        "version": None,
        "always_on": False,
        "remote_access_always_on": _remote_support_always_on(),
        "headless": _headless_enabled(),
        "message": None,
        "serve_active": False,
        "serve_target": SERVE_TARGET,
        "serve_https_port": SERVE_HTTPS_PORT,
        "remote_url": None,
        "serve_status": "UNAVAILABLE" if not supported else "INACTIVE",
        "serve_message": None,
    }
    if not supported:
        base["message"] = "دعم Tailscale متاح في نسخة nourxplay المحلية على Windows فقط."
        return base

    exe = _find_tailscale()
    if not exe:
        base["message"] = "Tailscale غير مثبت على هذا الجهاز."
        return base
    base["installed"] = True

    version_proc = _run(exe, ["version"], timeout=5)
    if version_proc.returncode == 0:
        lines = (version_proc.stdout or "").strip().splitlines()
        if lines:
            base["version"] = lines[0].strip()

    proc = _run(exe, ["status", "--json"], timeout=8)
    if proc.returncode != 0:
        base["state"] = "ERROR"
        base["message"] = _clean_message(proc)
        return base
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        base["state"] = "ERROR"
        base["message"] = "تعذر قراءة حالة Tailscale."
        return base

    backend_state = str(payload.get("BackendState") or "Unknown")
    self_node = payload.get("Self") or {}
    ips = self_node.get("TailscaleIPs") or []
    ipv4 = next((ip for ip in ips if isinstance(ip, str) and ":" not in ip), None)
    online = bool(self_node.get("Online"))
    dns_name = (self_node.get("DNSName") or "").rstrip(".") or None

    # ForceDaemon is the Windows preference behind Tailscale Run Unattended.
    force_daemon = False
    prefs_proc = _run(exe, ["debug", "prefs"], timeout=8)
    if prefs_proc.returncode == 0:
        try:
            prefs = json.loads(prefs_proc.stdout or "{}")
            force_daemon = bool(prefs.get("ForceDaemon"))
        except json.JSONDecodeError:
            force_daemon = False
    always_on = force_daemon and base["service_state"] == "RUNNING"

    base.update(
        {
            "connected": backend_state.lower() == "running" and online,
            "needs_login": backend_state.lower() in {"needslogin", "nostate"},
            "state": backend_state,
            "ipv4": ipv4,
            "dns_name": dns_name,
            "hostname": self_node.get("HostName") or None,
            "always_on": always_on,
            "message": None,
        }
    )
    if base["connected"]:
        base.update(_serve_details(exe, dns_name))
    return base


def _up_args() -> list[str]:
    args = [
        "up",
        "--unattended=true",
        "--accept-dns=false",
        "--accept-routes=false",
        f"--hostname={_support_hostname()}",
    ]
    tag = os.getenv("PLAYZONE_TAILSCALE_TAG", DEFAULT_TAG).strip()
    if tag:
        args.append(f"--advertise-tags={tag}")
    return args


def provision(auth_key: str) -> dict:
    """Register this Windows node using a ROOT-supplied auth key without persisting it."""
    status = get_status()
    if not status["supported"]:
        raise TailscaleSupportError("دعم Tailscale متاح في نسخة Windows المحلية فقط.")
    if not status["installed"]:
        raise TailscaleSupportError("Tailscale غير مثبت على هذا الجهاز.")
    key = (auth_key or "").strip()
    if not key.startswith("tskey-"):
        raise TailscaleSupportError("صيغة Auth Key غير صحيحة.")
    exe = _find_tailscale()
    if not exe:
        raise TailscaleSupportError("لم يتم العثور على tailscale.exe.")

    # Use Tailscale's file: form so the secret is not exposed in the process command line.
    fd, key_path = tempfile.mkstemp(prefix="pz-ts-", suffix=".key")
    try:
        os.write(fd, key.encode("utf-8"))
        os.close(fd)
        fd = -1
        args = _up_args()
        args.insert(1, f"--auth-key=file:{key_path}")
        proc = _run(exe, args, timeout=35)
        if proc.returncode != 0:
            raise TailscaleSupportError(_clean_message(proc))
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.remove(key_path)
        except OSError:
            pass

    ensure_always_on()
    try:
        return enable_remote_access()
    except TailscaleSupportError as exc:
        # Registration succeeded; keep that success even if the tailnet still
        # needs one-time HTTPS/Serve approval in the Tailscale admin flow.
        result = get_status()
        result["serve_message"] = str(exc)
        return result


def reconnect() -> dict:
    status = get_status()
    if not status["supported"]:
        raise TailscaleSupportError("دعم Tailscale متاح في نسخة Windows المحلية فقط.")
    if not status["installed"]:
        raise TailscaleSupportError("مكوّن Remote Support غير مثبت. أعد تشغيل Install-nourxplay.bat كمسؤول.")
    if status["needs_login"]:
        raise TailscaleSupportError("الجهاز غير مربوط بالـTailnet. استخدم Auth Key من صفحة ROOT مرة واحدة.")

    exe = _find_tailscale()
    if not exe:
        raise TailscaleSupportError("لم يتم العثور على tailscale.exe.")
    proc = _run(exe, _up_args(), timeout=25)
    if proc.returncode != 0:
        raise TailscaleSupportError(_clean_message(proc))
    return get_status()


def enable_remote_access() -> dict:
    status = get_status()
    if not status.get("supported"):
        raise TailscaleSupportError("دعم Tailscale متاح في نسخة Windows المحلية فقط.")
    if not status.get("installed"):
        raise TailscaleSupportError("Tailscale غير مثبت على هذا الجهاز.")
    if not status.get("connected"):
        if status.get("needs_login"):
            raise TailscaleSupportError("يجب ربط الجهاز بالـTailnet أولاً.")
        raise TailscaleSupportError("Tailscale غير متصل حالياً.")
    if status.get("serve_active"):
        return status

    exe = _find_tailscale()
    if not exe:
        raise TailscaleSupportError("لم يتم العثور على tailscale.exe.")
    proc = _run(
        exe,
        ["serve", "--bg", "--yes", f"--https={SERVE_HTTPS_PORT}", SERVE_TARGET],
        timeout=35,
    )
    if proc.returncode != 0:
        raise TailscaleSupportError(_clean_message(proc))
    result = get_status()
    if not result.get("serve_active"):
        raise TailscaleSupportError(result.get("serve_message") or "تم تنفيذ Tailscale Serve لكن لم يتم تأكيد تفعيله.")
    return result


def disable_remote_access() -> dict:
    if _remote_support_always_on():
        raise TailscaleSupportError(
            "Remote Support مضبوط على Always-On بواسطة nourxplay وسيتم تشغيل Tailscale Serve تلقائياً."
        )
    status = get_status()
    if not status.get("supported"):
        raise TailscaleSupportError("دعم Tailscale متاح في نسخة Windows المحلية فقط.")
    if not status.get("installed"):
        raise TailscaleSupportError("Tailscale غير مثبت على هذا الجهاز.")
    if not status.get("serve_active"):
        return status

    exe = _find_tailscale()
    if not exe:
        raise TailscaleSupportError("لم يتم العثور على tailscale.exe.")
    # Remove only the default HTTPS endpoint used by nourxplay. Do not reset any
    # unrelated Serve configuration that an administrator may have on the node.
    proc = _run(exe, ["serve", f"--https={SERVE_HTTPS_PORT}", "off"], timeout=20)
    if proc.returncode != 0:
        raise TailscaleSupportError(_clean_message(proc))
    return get_status()


def ensure_always_on() -> dict:
    """Recover the Tailscale daemon and, when policy is enabled, nourxplay Serve."""
    if os.name != "nt":
        return get_status()
    exe = _find_tailscale()
    if not exe:
        return get_status()

    _suppress_tray_gui()
    subprocess.run(["sc.exe", "config", "Tailscale", "start=", "auto"], capture_output=True, creationflags=_creation_flags())
    subprocess.run(
        ["sc.exe", "failure", "Tailscale", "reset=", "86400", "actions=", "restart/5000/restart/15000/restart/30000"],
        capture_output=True,
        creationflags=_creation_flags(),
    )
    subprocess.run(["sc.exe", "failureflag", "Tailscale", "1"], capture_output=True, creationflags=_creation_flags())
    subprocess.run(["sc.exe", "start", "Tailscale"], capture_output=True, creationflags=_creation_flags())

    status = get_status()
    if (
        status.get("installed")
        and not status.get("needs_login")
        and (not status.get("connected") or not status.get("always_on"))
    ):
        try:
            status = reconnect()
        except TailscaleSupportError:
            status = get_status()

    # nourxplay customer installs run with this policy enabled. If Serve is
    # cleared, crashes, or is manually turned off, the service watchdog
    # restores private HTTPS access to the local backend automatically.
    if (
        _remote_support_always_on()
        and status.get("installed")
        and status.get("connected")
        and not status.get("serve_active")
    ):
        try:
            status = enable_remote_access()
        except TailscaleSupportError as exc:
            status = get_status()
            status["serve_message"] = str(exc)
    _suppress_tray_gui()
    return status
