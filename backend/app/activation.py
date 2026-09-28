from __future__ import annotations

import hashlib
import os
import platform
from pathlib import Path

from sqlalchemy.orm import Session

from .models import SystemSetting

ACTIVATION_HASH_KEY = "activation_machine_hash"
ACTIVATION_LABEL_KEY = "activation_machine_label"
ACTIVATION_AT_KEY = "activation_activated_at"
ACTIVATION_BY_KEY = "activation_activated_by"
PASSWORDLESS_PRIVILEGED_KEY = "development_passwordless_privileged"


def _windows_machine_guid() -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg  # type: ignore

        access = winreg.KEY_READ
        try:
            access |= winreg.KEY_WOW64_64KEY
        except AttributeError:
            pass
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            access,
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value).strip()
    except Exception:
        return None


def _unix_machine_id() -> str | None:
    for path in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        try:
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            pass
    return None


def machine_material() -> str:
    stable_id = _windows_machine_guid() or _unix_machine_id()
    if not stable_id:
        # Final fallback for unusual systems. This is less stable than MachineGuid,
        # but still prevents a simple copied database from auto-activating elsewhere.
        stable_id = f"{platform.node()}|{platform.machine()}|{platform.system()}"
    return f"playzone-v1|{platform.system()}|{stable_id}"


def machine_hash() -> str:
    return hashlib.sha256(machine_material().encode("utf-8")).hexdigest()


def machine_short_id() -> str:
    digest = machine_hash().upper()
    return f"{digest[:6]}-{digest[6:12]}-{digest[12:18]}"


def machine_label() -> str:
    name = platform.node().strip() or "Local-PC"
    return name[:100]


def _setting(db: Session, key: str) -> str | None:
    row = db.get(SystemSetting, key)
    return row.value if row else None


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(SystemSetting, key)
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=key, value=value))


def passwordless_privileged_enabled(db: Session) -> bool:
    return _setting(db, PASSWORDLESS_PRIVILEGED_KEY) == "1"


def is_activated(db: Session) -> bool:
    bound = _setting(db, ACTIVATION_HASH_KEY)
    return bool(bound) and bound == machine_hash()


def activation_status(db: Session) -> dict:
    bound = _setting(db, ACTIVATION_HASH_KEY)
    current = machine_hash()
    return {
        "activated": bool(bound) and bound == current,
        "machine_id": machine_short_id(),
        "machine_label": machine_label(),
        "bound_machine_id": (f"{bound[:6].upper()}-{bound[6:12].upper()}-{bound[12:18].upper()}" if bound else None),
        "bound_to_this_machine": bool(bound) and bound == current,
        # ROOT is never passwordless in v0.31. Keep this legacy UI field false
        # even if an ADMIN-only development bypass is manually enabled.
        "passwordless_privileged": False,
        "activated_at": _setting(db, ACTIVATION_AT_KEY),
        "activated_by": _setting(db, ACTIVATION_BY_KEY),
        "activated_machine_label": _setting(db, ACTIVATION_LABEL_KEY),
    }
