from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TARGET_URL = "http://127.0.0.1:8000"
TRY_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)
START_TIMEOUT_SECONDS = 15.0
MAX_LOG_LINES = 40


class CloudflareSupportError(RuntimeError):
    pass


_lock = threading.RLock()
_proc: subprocess.Popen[str] | None = None
_reader_thread: threading.Thread | None = None
_remote_url: str | None = None
_started_at: str | None = None
_last_message: str | None = None
_log_lines: list[str] = []
_cached_version: str | None = None


def _app_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _state_root() -> Path:
    override = os.getenv("PLAYZONE_CLOUDFLARE_STATE_DIR", "").strip()
    if override:
        return Path(override)
    program_data = os.getenv("PROGRAMDATA")
    if program_data:
        return Path(program_data) / "PlayZone Manager" / "cloudflare-quick"
    return _app_root() / ".cloudflare-quick"


def _state_file() -> Path:
    return _state_root() / "state.json"


def _supported() -> bool:
    return os.name == "nt" or os.getenv("PLAYZONE_CLOUDFLARE_ALLOW_NONWINDOWS") == "1"


def _find_cloudflared() -> str | None:
    override = os.getenv("PLAYZONE_CLOUDFLARED_PATH", "").strip()
    if override and Path(override).is_file():
        return override

    found = shutil.which("cloudflared") or shutil.which("cloudflared.exe")
    if found:
        return found

    candidates = [_app_root() / "cloudflared.exe"]
    if os.name == "nt":
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.getenv(env_name)
            if base:
                candidates.extend([
                    Path(base) / "cloudflared" / "cloudflared.exe",
                    Path(base) / "Cloudflared" / "cloudflared.exe",
                ])
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _append_log(line: str) -> None:
    global _last_message
    text = (line or "").strip()
    if not text:
        return
    with _lock:
        _log_lines.append(text[-2000:])
        del _log_lines[:-MAX_LOG_LINES]
        _last_message = text[-1000:]


def _write_state(pid: int | None, remote_url: str | None, started_at: str | None) -> None:
    root = _state_root()
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": pid,
        "remote_url": remote_url,
        "started_at": started_at,
        "target_url": TARGET_URL,
    }
    tmp = _state_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_state_file())


def _read_state() -> dict[str, Any]:
    try:
        raw = json.loads(_state_file().read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _clear_state_file() -> None:
    try:
        _state_file().unlink(missing_ok=True)
    except OSError:
        pass


def _pid_is_running(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        try:
            proc = subprocess.run(
                ["tasklist.exe", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        out = (proc.stdout or "").lower()
        return proc.returncode == 0 and f'"{pid}"' in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _remember_recovered_state() -> tuple[int | None, str | None, str | None]:
    global _remote_url, _started_at
    state = _read_state()
    try:
        pid = int(state.get("pid") or 0) or None
    except (TypeError, ValueError):
        pid = None
    if not _pid_is_running(pid):
        _clear_state_file()
        return None, None, None
    url = state.get("remote_url")
    started = state.get("started_at")
    _remote_url = str(url) if url else None
    _started_at = str(started) if started else None
    return pid, _remote_url, _started_at


def _cloudflared_version(exe: str | None) -> str | None:
    global _cached_version
    if _cached_version:
        return _cached_version
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = ((proc.stdout or "") + " " + (proc.stderr or "")).strip()
    if proc.returncode == 0 and text:
        _cached_version = text.splitlines()[0][:240]
    return _cached_version


def _current_pid() -> int | None:
    global _proc
    if _proc is not None:
        if _proc.poll() is None:
            return _proc.pid
        _proc = None
    pid, _, _ = _remember_recovered_state()
    return pid


def _reader_loop(proc: subprocess.Popen[str]) -> None:
    global _remote_url, _started_at, _last_message
    try:
        stream = proc.stdout
        if stream is None:
            return
        for raw_line in iter(stream.readline, ""):
            line = raw_line.strip()
            if not line:
                continue
            _append_log(line)
            match = TRY_URL_RE.search(line)
            if match:
                url = match.group(0)
                with _lock:
                    _remote_url = url
                    if not _started_at:
                        _started_at = datetime.now(timezone.utc).isoformat()
                    _write_state(proc.pid, _remote_url, _started_at)
    finally:
        try:
            code = proc.wait(timeout=1)
        except Exception:
            code = proc.poll()
        with _lock:
            if code not in (None, 0):
                _last_message = f"cloudflared exited with code {code}. " + (_last_message or "")
            state = _read_state()
            if int(state.get("pid") or 0) == proc.pid and not _pid_is_running(proc.pid):
                _clear_state_file()


def get_status() -> dict[str, Any]:
    with _lock:
        supported = _supported()
        exe = _find_cloudflared()
        pid = _current_pid() if supported else None
        running = bool(pid and _pid_is_running(pid))
        if not running:
            remote_url = None
            started_at = None
        else:
            state = _read_state()
            remote_url = _remote_url or state.get("remote_url")
            started_at = _started_at or state.get("started_at")
        return {
            "provider": "cloudflare",
            "mode": "quick_tunnel",
            "supported": supported,
            "installed": bool(exe),
            "running": running,
            "connected": running and bool(remote_url),
            "starting": running and not bool(remote_url),
            "remote_url": remote_url,
            "target_url": TARGET_URL,
            "pid": pid if running else None,
            "started_at": started_at,
            "cloudflared_path": exe,
            "cloudflared_version": _cloudflared_version(exe) if supported else None,
            "message": _last_message,
            "test_only": True,
        }


def start_quick_tunnel() -> dict[str, Any]:
    global _proc, _reader_thread, _remote_url, _started_at, _last_message
    if not _supported():
        raise CloudflareSupportError("دعم Cloudflare Quick Tunnel متاح في نسخة Windows المحلية فقط.")

    with _lock:
        current = get_status()
        if current["running"]:
            return current

        exe = _find_cloudflared()
        if not exe:
            raise CloudflareSupportError(
                "cloudflared غير موجود. أعد تشغيل Installer التجريبي أو ضع cloudflared.exe داخل مجلد البرنامج."
            )

        root = _state_root()
        root.mkdir(parents=True, exist_ok=True)
        profile = root / "profile"
        (profile / ".cloudflared").mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["USERPROFILE"] = str(profile)
        env["HOME"] = str(profile)

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        _remote_url = None
        _started_at = datetime.now(timezone.utc).isoformat()
        _last_message = "Starting Cloudflare Quick Tunnel..."
        _log_lines.clear()
        try:
            _proc = subprocess.Popen(
                [exe, "tunnel", "--url", TARGET_URL],
                cwd=str(root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
        except OSError as exc:
            _proc = None
            raise CloudflareSupportError(f"تعذر تشغيل cloudflared: {exc}") from exc

        _write_state(_proc.pid, None, _started_at)
        _reader_thread = threading.Thread(
            target=_reader_loop,
            args=(_proc,),
            name="cloudflare-quick-reader",
            daemon=True,
        )
        _reader_thread.start()

    deadline = time.monotonic() + START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        status = get_status()
        if status["remote_url"]:
            return status
        if not status["running"]:
            raise CloudflareSupportError(status.get("message") or "cloudflared توقف قبل إنشاء رابط TryCloudflare.")
        time.sleep(0.15)

    return get_status()


def _stop_pid(pid: int) -> None:
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        return

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline and _pid_is_running(pid):
        time.sleep(0.1)
    if _pid_is_running(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def stop_quick_tunnel() -> dict[str, Any]:
    global _proc, _remote_url, _started_at, _last_message
    if not _supported():
        raise CloudflareSupportError("دعم Cloudflare Quick Tunnel متاح في نسخة Windows المحلية فقط.")

    with _lock:
        pid = _current_pid()
        if pid:
            _stop_pid(pid)
        _proc = None
        _remote_url = None
        _started_at = None
        _last_message = "Cloudflare Quick Tunnel stopped."
        _clear_state_file()
    return get_status()


def restart_quick_tunnel() -> dict[str, Any]:
    stop_quick_tunnel()
    return start_quick_tunnel()


def _cleanup() -> None:
    try:
        if _proc is not None and _proc.poll() is None:
            _stop_pid(_proc.pid)
    except Exception:
        pass


atexit.register(_cleanup)
