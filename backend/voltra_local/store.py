from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConfigStore:
    """Thread-safe JSON persistence for strips, PS4 references, and outlet mappings."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data = self._load()

    def _default(self) -> dict:
        return {"version": 2, "strips": {}, "ps4_devices": {}, "mappings": {}}

    def _load(self) -> dict:
        if not self.path.exists():
            return self._default()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._default()
        if not isinstance(value, dict):
            return self._default()
        base = self._default()
        for key in ("strips", "ps4_devices", "mappings"):
            item = value.get(key, {})
            base[key] = item if isinstance(item, dict) else {}

        # v1 -> v2 migration: any strip that was already stored by an older
        # PlayZone/Voltra build is treated as approved and active so existing
        # installations keep working after the upgrade.
        old_version = int(value.get("version") or 1)
        if old_version < 2:
            for meta in base["strips"].values():
                if isinstance(meta, dict):
                    meta.setdefault("managed", True)
                    meta.setdefault("enabled", True)
                    meta.setdefault("state", "active")
                    meta.setdefault("approved_at", meta.get("first_seen_at") or utc_now())
        else:
            for meta in base["strips"].values():
                if not isinstance(meta, dict):
                    continue
                state = str(meta.get("state") or "active")
                meta.setdefault("managed", state == "active")
                meta.setdefault("enabled", state == "active")
        base["version"] = 2
        return base

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="voltra-", suffix=".json", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @staticmethod
    def normalize_mac(mac: str) -> str:
        value = mac.replace(":", "").replace("-", "").strip().upper()
        if len(value) != 12 or any(ch not in "0123456789ABCDEF" for ch in value):
            raise ValueError("invalid MAC address")
        return value

    def record_strip(self, snapshot: dict) -> None:
        mac = snapshot.get("mac")
        if not mac:
            return
        mac = self.normalize_mac(str(mac))
        with self._lock:
            current = self._data["strips"].get(mac)
            now = utc_now()
            if not isinstance(current, dict):
                # New strips are discovered automatically but are deliberately
                # NOT controllable until ROOT explicitly adopts them.
                current = {
                    "name": f"Voltra {mac[-4:]}",
                    "first_seen_at": now,
                    "managed": False,
                    "enabled": False,
                    "state": "pending",
                }
                self._data["strips"][mac] = current
            current.setdefault("name", f"Voltra {mac[-4:]}")
            current.setdefault("first_seen_at", now)
            current.setdefault("managed", False)
            current.setdefault("enabled", False)
            current.setdefault("state", "pending")
            current["last_seen_at"] = now
            current["model"] = snapshot.get("model")
            current["firmware_version"] = snapshot.get("firmware_version")
            remote = str(snapshot.get("remote_address") or "")
            current["last_ip"] = remote.rsplit(":", 1)[0] if ":" in remote else remote
            self._save_locked()

    def strip(self, mac: str) -> dict | None:
        mac = self.normalize_mac(mac)
        with self._lock:
            item = self._data["strips"].get(mac)
            return dict(item) if isinstance(item, dict) else None

    def rename_strip(self, mac: str, name: str) -> dict:
        mac = self.normalize_mac(mac)
        name = name.strip()
        if not name:
            raise ValueError("strip name cannot be empty")
        if len(name) > 80:
            raise ValueError("strip name is too long")
        with self._lock:
            current = self._data["strips"].get(mac)
            if not isinstance(current, dict):
                raise KeyError(f"unknown strip: {mac}")
            current["name"] = name
            current["updated_at"] = utc_now()
            self._save_locked()
            return dict(current)

    def adopt_strip(self, mac: str, name: str | None = None) -> dict:
        mac = self.normalize_mac(mac)
        with self._lock:
            current = self._data["strips"].get(mac)
            if not isinstance(current, dict):
                raise KeyError(f"unknown strip: {mac}")
            clean_name = (name or current.get("name") or f"Voltra {mac[-4:]}").strip()
            if not clean_name or len(clean_name) > 80:
                raise ValueError("invalid strip name")
            current["name"] = clean_name
            current["managed"] = True
            current["enabled"] = True
            current["state"] = "active"
            current["approved_at"] = utc_now()
            current.pop("ignored_at", None)
            current.pop("removed_at", None)
            current.pop("replaced_by", None)
            self._save_locked()
            return dict(current)

    def set_strip_enabled(self, mac: str, enabled: bool) -> dict:
        mac = self.normalize_mac(mac)
        with self._lock:
            current = self._data["strips"].get(mac)
            if not isinstance(current, dict):
                raise KeyError(f"unknown strip: {mac}")
            if not current.get("managed"):
                raise ValueError("strip must be added before it can be enabled or disabled")
            if current.get("state") == "replaced":
                raise ValueError("replaced strip cannot be enabled")
            current["enabled"] = bool(enabled)
            current["state"] = "active" if enabled else "disabled"
            current["updated_at"] = utc_now()
            self._save_locked()
            return dict(current)

    def ignore_strip(self, mac: str) -> dict:
        mac = self.normalize_mac(mac)
        with self._lock:
            current = self._data["strips"].get(mac)
            if not isinstance(current, dict):
                raise KeyError(f"unknown strip: {mac}")
            if current.get("managed"):
                raise ValueError("disable or remove an added strip instead of ignoring it")
            current["managed"] = False
            current["enabled"] = False
            current["state"] = "ignored"
            current["ignored_at"] = utc_now()
            self._save_locked()
            return dict(current)

    def remove_strip(self, mac: str) -> dict:
        """Remove a strip from management and clear every mapping to it.

        The metadata is retained as a tombstone while the physical device may
        still be connected, preventing it from instantly reappearing as a new
        pending strip during the same session. It can be adopted again later.
        """
        mac = self.normalize_mac(mac)
        with self._lock:
            current = self._data["strips"].get(mac)
            if not isinstance(current, dict):
                raise KeyError(f"unknown strip: {mac}")
            removed_mappings = []
            for device_id, mapping in list(self._data["mappings"].items()):
                if mapping.get("mac") == mac:
                    removed_mappings.append(device_id)
                    self._data["mappings"].pop(device_id, None)
            current["managed"] = False
            current["enabled"] = False
            current["state"] = "removed"
            current["removed_at"] = utc_now()
            current["removed_mappings"] = removed_mappings
            self._save_locked()
            return {"strip": dict(current), "removed_mappings": removed_mappings}

    def replace_strip(self, old_mac: str, new_mac: str) -> dict:
        old_mac = self.normalize_mac(old_mac)
        new_mac = self.normalize_mac(new_mac)
        if old_mac == new_mac:
            raise ValueError("old and new strip cannot be the same")
        with self._lock:
            old = self._data["strips"].get(old_mac)
            new = self._data["strips"].get(new_mac)
            if not isinstance(old, dict):
                raise KeyError(f"unknown strip: {old_mac}")
            if not isinstance(new, dict):
                raise KeyError(f"unknown replacement strip: {new_mac}")
            if not old.get("managed"):
                raise ValueError("old strip is not an added strip")
            # The replacement should be a newly discovered/unmanaged strip.
            if new.get("managed") and new.get("state") not in {"pending", "ignored", "removed"}:
                raise ValueError("replacement strip is already managed")

            # Refuse to merge two independent mapping sets implicitly.
            new_conflicts = [
                device_id
                for device_id, mapping in self._data["mappings"].items()
                if mapping.get("mac") == new_mac
            ]
            if new_conflicts:
                raise ValueError("replacement strip already has mapped devices")

            transferred: list[str] = []
            for device_id, mapping in self._data["mappings"].items():
                if mapping.get("mac") == old_mac:
                    mapping["mac"] = new_mac
                    mapping["updated_at"] = utc_now()
                    transferred.append(device_id)

            old_name = str(old.get("name") or f"Voltra {old_mac[-4:]}")
            now = utc_now()
            new["name"] = old_name
            new["managed"] = True
            new["enabled"] = True
            new["state"] = "active"
            new["approved_at"] = now
            new["replaced_from"] = old_mac
            new.pop("ignored_at", None)
            new.pop("removed_at", None)

            old["managed"] = False
            old["enabled"] = False
            old["state"] = "replaced"
            old["replaced_by"] = new_mac
            old["retired_at"] = now
            self._save_locked()
            return {
                "old_mac": old_mac,
                "new_mac": new_mac,
                "transferred_devices": transferred,
                "old": dict(old),
                "new": dict(new),
            }

    def strip_controllable(self, mac: str) -> bool:
        mac = self.normalize_mac(mac)
        with self._lock:
            current = self._data["strips"].get(mac)
            return bool(
                isinstance(current, dict)
                and current.get("managed")
                and current.get("enabled")
                and current.get("state") == "active"
            )

    def require_strip_controllable(self, mac: str) -> dict:
        mac = self.normalize_mac(mac)
        with self._lock:
            current = self._data["strips"].get(mac)
            if not isinstance(current, dict):
                raise KeyError(f"unknown strip: {mac}")
            if not current.get("managed"):
                raise ValueError("strip is not added to Voltra")
            if not current.get("enabled") or current.get("state") != "active":
                raise ValueError("strip is disabled")
            return dict(current)

    def strips(self) -> dict[str, dict]:
        with self._lock:
            return {mac: dict(item) for mac, item in self._data["strips"].items()}

    def upsert_ps4(self, device_id: str, name: str | None = None) -> dict:
        device_id = device_id.strip()
        if not device_id or len(device_id) > 100:
            raise ValueError("invalid PS4 device id")
        clean_name = (name or device_id).strip()
        if not clean_name or len(clean_name) > 120:
            raise ValueError("invalid PS4 name")
        with self._lock:
            current = self._data["ps4_devices"].setdefault(device_id, {})
            current["id"] = device_id
            current["name"] = clean_name
            current.setdefault("created_at", utc_now())
            current["updated_at"] = utc_now()
            self._save_locked()
            return dict(current)

    def sync_ps4(self, devices: list[dict], prune: bool = False) -> list[dict]:
        parsed: dict[str, tuple[str, str]] = {}
        for raw in devices:
            if not isinstance(raw, dict):
                raise ValueError("each PS4 device must be an object")
            device_id = str(raw.get("id") or "").strip()
            name = str(raw.get("name") or device_id).strip()
            if not device_id or len(device_id) > 100 or not name or len(name) > 120:
                raise ValueError("invalid PS4 device in sync payload")
            parsed[device_id] = (device_id, name)
        with self._lock:
            for device_id, (_, name) in parsed.items():
                current = self._data["ps4_devices"].setdefault(device_id, {})
                current["id"] = device_id
                current["name"] = name
                current.setdefault("created_at", utc_now())
                current["updated_at"] = utc_now()
            if prune:
                for old_id in list(self._data["ps4_devices"]):
                    if old_id not in parsed:
                        self._data["ps4_devices"].pop(old_id, None)
                        self._data["mappings"].pop(old_id, None)
            self._save_locked()
            return self.ps4_devices()

    def delete_ps4(self, device_id: str) -> bool:
        with self._lock:
            existed = device_id in self._data["ps4_devices"]
            self._data["ps4_devices"].pop(device_id, None)
            self._data["mappings"].pop(device_id, None)
            if existed:
                self._save_locked()
            return existed

    def ps4_devices(self) -> list[dict]:
        with self._lock:
            values = [dict(item) for item in self._data["ps4_devices"].values()]
        values.sort(key=lambda item: (str(item.get("name", "")).lower(), str(item.get("id", ""))))
        return values

    def set_mapping(self, device_id: str, mac: str, outlet: int) -> dict:
        if outlet not in (1, 2, 3, 4):
            raise ValueError("outlet must be 1..4")
        mac = self.normalize_mac(mac)
        with self._lock:
            if device_id not in self._data["ps4_devices"]:
                raise KeyError(f"unknown PS4 device: {device_id}")
            strip = self._data["strips"].get(mac)
            if not isinstance(strip, dict) or not strip.get("managed"):
                raise ValueError("strip must be added before mapping")
            if not strip.get("enabled") or strip.get("state") != "active":
                raise ValueError("cannot create a new mapping to a disabled strip")
            conflict = next(
                (
                    other_id
                    for other_id, mapping in self._data["mappings"].items()
                    if other_id != device_id
                    and mapping.get("mac") == mac
                    and mapping.get("outlet") == outlet
                ),
                None,
            )
            if conflict:
                raise ValueError(f"outlet {outlet} on {mac} is already assigned to {conflict}")
            mapping = {"ps4_id": device_id, "mac": mac, "outlet": outlet, "updated_at": utc_now()}
            self._data["mappings"][device_id] = mapping
            self._save_locked()
            return dict(mapping)

    def clear_mapping(self, device_id: str) -> bool:
        with self._lock:
            existed = device_id in self._data["mappings"]
            self._data["mappings"].pop(device_id, None)
            if existed:
                self._save_locked()
            return existed

    def mapping(self, device_id: str) -> dict | None:
        with self._lock:
            value = self._data["mappings"].get(device_id)
            return dict(value) if value else None

    def mappings(self) -> dict[str, dict]:
        with self._lock:
            return {key: dict(value) for key, value in self._data["mappings"].items()}
