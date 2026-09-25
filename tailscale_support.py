from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

DEFAULT_TAG = "tag:playzone-client"

class TailscaleSupportError(RuntimeError):
    pass

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
    return text[-800:]

def _hostname() -> str:
    raw = socket.gethostname().lower()
    safe = re.sub(r"[^a-z0-9-]+", "-", raw).strip("-") or "windows"
    return f"playzone-{safe}"[:63]

def get_status() -> dict:
    supported = os.name == "nt"
    base = {
        "supported": supported,
        "installed": False,
        "connected": False,
        "needs_login": False,
        "state": "UNSUPPORTED" if not supported else "NOT_INSTALLED",
        "ipv4": None,
        "dns_name": None,
        "hostname": None,
        "version": None,
        "message": None,
    }
    if not supported:
        base["message"] = "دعم Tailscale متاح في نسخة PlayZone المحلية على Windows فقط."
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
    base.update({
        "connected": backend_state.lower() == "running" and online,
        "needs_login": backend_state.lower() in {"needslogin", "nostate"},
        "state": backend_state,
        "ipv4": ipv4,
        "dns_name": (self_node.get("DNSName") or "").rstrip(".") or None,
        "hostname": self_node.get("HostName") or None,
        "message": None,
    })
    return base

def start_support() -> dict:
    status = get_status()
    if not status["supported"]:
        raise TailscaleSupportError("دعم Tailscale متاح في نسخة Windows المحلية فقط.")
    if not status["installed"]:
        raise TailscaleSupportError("Tailscale غير مثبت. شغّل Provision-Tailscale-Support.bat مرة واحدة كمسؤول.")
    if status["needs_login"]:
        raise TailscaleSupportError("Tailscale يحتاج تهيئة أول مرة. شغّل Provision-Tailscale-Support.bat وأدخل مفتاح Tailscale المؤقت.")
    if status["connected"]:
        return status
    exe = _find_tailscale()
    if not exe:
        raise TailscaleSupportError("لم يتم العثور على tailscale.exe.")
    tag = os.getenv("PLAYZONE_TAILSCALE_TAG", DEFAULT_TAG).strip()
    args = ["up", "--accept-dns=false", "--accept-routes=false", f"--hostname={_hostname()}"]
    if tag:
        args.append(f"--advertise-tags={tag}")
    proc = _run(exe, args, timeout=20)
    if proc.returncode != 0:
        raise TailscaleSupportError(_clean_message(proc))
    latest = get_status()
    for _ in range(5):
        if latest["connected"]:
            break
        time.sleep(0.4)
        latest = get_status()
    return latest

def stop_support() -> dict:
    status = get_status()
    if not status["supported"] or not status["installed"]:
        return status
    exe = _find_tailscale()
    if not exe:
        return status
    proc = _run(exe, ["down"], timeout=12)
    if proc.returncode != 0:
        raise TailscaleSupportError(_clean_message(proc))
    time.sleep(0.3)
    return get_status()
