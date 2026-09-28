from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import threading
from urllib.parse import unquote, urlsplit

from . import __version__
from .dashboard import DASHBOARD
from .provisioner import provision_device
from .store import ConfigStore
from .tcp_server import MTTLServer

# Backward-compatible low-level device API.
_DEVICE_RE = re.compile(r"^/api/devices/([^/]+)$")
_REFRESH_RE = re.compile(r"^/api/devices/([^/]+)/refresh$")
_STATE_RE = re.compile(r"^/api/devices/([^/]+)/outlets/([1-4])/state$")
_ACTION_RE = re.compile(r"^/api/devices/([^/]+)/outlets/([1-4])/(on|off)$")

# Namespaced API for embedding into the PlayStation management project.
_V_STRIP_RE = re.compile(r"^/voltra/api/strips/([^/]+)$")
_V_STRIP_STATE_RE = re.compile(r"^/voltra/api/strips/([^/]+)/outlets/([1-4])/state$")
_V_STRIP_ADOPT_RE = re.compile(r"^/voltra/api/strips/([^/]+)/adopt$")
_V_STRIP_ENABLED_RE = re.compile(r"^/voltra/api/strips/([^/]+)/enabled$")
_V_STRIP_IGNORE_RE = re.compile(r"^/voltra/api/strips/([^/]+)/ignore$")
_V_STRIP_REPLACE_RE = re.compile(r"^/voltra/api/strips/([^/]+)/replace$")
_V_PS4_RE = re.compile(r"^/voltra/api/ps4/([^/]+)$")
_V_MAPPING_RE = re.compile(r"^/voltra/api/ps4/([^/]+)/power-mapping$")
_V_POWER_RE = re.compile(r"^/voltra/api/ps4/([^/]+)/power$")
_V_POWER_ACTION_RE = re.compile(r"^/voltra/api/ps4/([^/]+)/power/(on|off)$")


def _decoded(value: str) -> str:
    return unquote(value)


class APIHandler(BaseHTTPRequestHandler):
    server_version = "VoltraLocal/0.4"

    @property
    def app(self) -> "VoltraHTTPServer":
        return self.server  # type: ignore[return-value]

    def do_OPTIONS(self):
        self.send_response(204)
        self._common_headers()
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,Authorization")
        self.end_headers()

    def do_GET(self):
        try:
            path = urlsplit(self.path).path
            if path == "/":
                self.send_response(302)
                self.send_header("Location", "/voltra")
                self._common_headers()
                self.end_headers()
                return
            if path in ("/voltra", "/voltra/"):
                return self._send_text(200, DASHBOARD, "text/html; charset=utf-8")
            if path == "/health":
                return self._json(200, {"ok": True, "version": __version__})

            self._require_auth()
            if path == "/api/status":
                devices = self.app.mttl.list_devices()
                return self._json(200, {"ok": True, "version": __version__, "device_count": len(devices)})
            if path == "/api/devices":
                return self._json(200, {"devices": self.app.mttl.list_devices()})
            match = _DEVICE_RE.match(path)
            if match:
                return self._json(200, self.app.mttl.get(_decoded(match.group(1))).snapshot())

            if path == "/voltra/api/overview":
                return self._json(200, self.app.overview())
            if path == "/voltra/api/strips":
                return self._json(200, {"strips": self.app.list_strips()})
            if path == "/voltra/api/ps4":
                return self._json(200, {"devices": self.app.store.ps4_devices()})
            match = _V_POWER_RE.match(path)
            if match:
                return self._json(200, self.app.ps4_power_status(_decoded(match.group(1))))
            match = _V_PS4_RE.match(path)
            if match:
                device_id = _decoded(match.group(1))
                device = next((x for x in self.app.store.ps4_devices() if x["id"] == device_id), None)
                if not device:
                    raise KeyError(f"unknown PS4 device: {device_id}")
                return self._json(200, {**device, "mapping": self.app.store.mapping(device_id)})

            return self._json(404, {"error": "not found"})
        except KeyError as exc:
            return self._json(404, {"error": str(exc)})
        except PermissionError as exc:
            return self._json(401, {"error": str(exc)})
        except Exception as exc:
            return self._json(500, {"error": str(exc)})

    def do_POST(self):
        try:
            path = urlsplit(self.path).path
            self._require_auth()

            match = _REFRESH_RE.match(path)
            if match:
                return self._json(200, self.app.mttl.get(_decoded(match.group(1))).query_info())
            match = _STATE_RE.match(path)
            if match:
                body = self._read_json()
                on = body.get("on")
                if not isinstance(on, bool):
                    return self._json(400, {"error": "JSON field 'on' must be boolean"})
                return self._json(200, self.app.mttl.get(_decoded(match.group(1))).set_outlet(int(match.group(2)), on))
            match = _ACTION_RE.match(path)
            if match:
                return self._json(200, self.app.mttl.get(_decoded(match.group(1))).set_outlet(int(match.group(2)), match.group(3) == "on"))

            if path == "/voltra/api/ps4":
                body = self._read_json()
                device_id = str(body.get("id") or "")
                name = body.get("name")
                return self._json(201, self.app.store.upsert_ps4(device_id, str(name) if name is not None else None))
            if path == "/voltra/api/ps4/sync":
                body = self._read_json()
                devices = body.get("devices")
                if not isinstance(devices, list):
                    return self._json(400, {"error": "devices must be an array"})
                prune = body.get("prune", False)
                if not isinstance(prune, bool):
                    return self._json(400, {"error": "prune must be boolean"})
                return self._json(200, {"devices": self.app.store.sync_ps4(devices, prune=prune)})
            if path == "/voltra/api/provision":
                body = self._read_json()
                result = provision_device(
                    ssid=str(body.get("ssid") or ""),
                    password=str(body.get("password") or ""),
                    server_ip=str(body.get("server_ip") or ""),
                    device_ip=str(body.get("device_ip") or "192.168.1.1"),
                )
                return self._json(200, result)
            match = _V_STRIP_ADOPT_RE.match(path)
            if match:
                body = self._read_json()
                name = body.get("name")
                return self._json(200, {"mac": self.app.store.normalize_mac(_decoded(match.group(1))), **self.app.store.adopt_strip(_decoded(match.group(1)), str(name) if name is not None else None)})
            match = _V_STRIP_ENABLED_RE.match(path)
            if match:
                body = self._read_json()
                enabled = body.get("enabled")
                if not isinstance(enabled, bool):
                    return self._json(400, {"error": "JSON field 'enabled' must be boolean"})
                return self._json(200, {"mac": self.app.store.normalize_mac(_decoded(match.group(1))), **self.app.store.set_strip_enabled(_decoded(match.group(1)), enabled)})
            match = _V_STRIP_IGNORE_RE.match(path)
            if match:
                return self._json(200, {"mac": self.app.store.normalize_mac(_decoded(match.group(1))), **self.app.store.ignore_strip(_decoded(match.group(1)))})
            match = _V_STRIP_REPLACE_RE.match(path)
            if match:
                body = self._read_json()
                new_mac = str(body.get("new_mac") or "")
                return self._json(200, self.app.store.replace_strip(_decoded(match.group(1)), new_mac))
            match = _V_STRIP_STATE_RE.match(path)
            if match:
                body = self._read_json()
                on = body.get("on")
                if not isinstance(on, bool):
                    return self._json(400, {"error": "JSON field 'on' must be boolean"})
                mac = _decoded(match.group(1))
                self.app.store.require_strip_controllable(mac)
                return self._json(200, self.app.mttl.get(mac).set_outlet(int(match.group(2)), on))
            match = _V_POWER_ACTION_RE.match(path)
            if match:
                return self._json(200, self.app.set_ps4_power(_decoded(match.group(1)), match.group(2) == "on"))

            return self._json(404, {"error": "not found"})
        except KeyError as exc:
            return self._json(404, {"error": str(exc)})
        except TimeoutError as exc:
            return self._json(504, {"error": str(exc)})
        except (ValueError, json.JSONDecodeError) as exc:
            return self._json(400, {"error": str(exc)})
        except PermissionError as exc:
            return self._json(401, {"error": str(exc)})
        except Exception as exc:
            return self._json(500, {"error": str(exc)})

    def do_PUT(self):
        try:
            path = urlsplit(self.path).path
            self._require_auth()
            body = self._read_json()

            match = _V_STRIP_RE.match(path)
            if match:
                mac = _decoded(match.group(1))
                name = str(body.get("name") or "")
                return self._json(200, {"mac": self.app.store.normalize_mac(mac), **self.app.store.rename_strip(mac, name)})
            match = _V_PS4_RE.match(path)
            if match:
                device_id = _decoded(match.group(1))
                return self._json(200, self.app.store.upsert_ps4(device_id, str(body.get("name") or device_id)))
            match = _V_MAPPING_RE.match(path)
            if match:
                device_id = _decoded(match.group(1))
                mac = str(body.get("mac") or "")
                outlet = body.get("outlet")
                if not isinstance(outlet, int):
                    return self._json(400, {"error": "outlet must be integer 1..4"})
                return self._json(200, self.app.store.set_mapping(device_id, mac, outlet))

            return self._json(404, {"error": "not found"})
        except KeyError as exc:
            return self._json(404, {"error": str(exc)})
        except (ValueError, json.JSONDecodeError) as exc:
            return self._json(400, {"error": str(exc)})
        except PermissionError as exc:
            return self._json(401, {"error": str(exc)})
        except Exception as exc:
            return self._json(500, {"error": str(exc)})

    def do_DELETE(self):
        try:
            path = urlsplit(self.path).path
            self._require_auth()
            match = _V_MAPPING_RE.match(path)
            if match:
                device_id = _decoded(match.group(1))
                return self._json(200, {"ok": True, "removed": self.app.store.clear_mapping(device_id)})
            match = _V_STRIP_RE.match(path)
            if match:
                mac = _decoded(match.group(1))
                return self._json(200, {"ok": True, **self.app.store.remove_strip(mac)})
            match = _V_PS4_RE.match(path)
            if match:
                device_id = _decoded(match.group(1))
                removed = self.app.store.delete_ps4(device_id)
                if not removed:
                    raise KeyError(f"unknown PS4 device: {device_id}")
                return self._json(200, {"ok": True, "removed": True})
            return self._json(404, {"error": "not found"})
        except KeyError as exc:
            return self._json(404, {"error": str(exc)})
        except PermissionError as exc:
            return self._json(401, {"error": str(exc)})
        except Exception as exc:
            return self._json(500, {"error": str(exc)})

    def _require_auth(self):
        token = self.app.api_token
        if token and self.headers.get("Authorization") != f"Bearer {token}":
            raise PermissionError("invalid or missing API token")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1024 * 1024:
            raise ValueError("request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON object expected")
        return value

    def _json(self, status: int, value: object):
        payload = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self._common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_text(self, status: int, value: str, content_type: str):
        payload = value.encode("utf-8")
        self.send_response(status)
        self._common_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _common_headers(self):
        self.send_header("Access-Control-Allow-Origin", self.app.cors_origin)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")

    def log_message(self, fmt, *args):
        print("[HTTP] " + (fmt % args))


class VoltraHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, mttl: MTTLServer, store: ConfigStore, api_token: str = "", cors_origin: str = "*"):
        self.mttl = mttl
        self.store = store
        self.api_token = api_token
        self.cors_origin = cors_origin
        super().__init__(address, APIHandler)

    def list_strips(self) -> list[dict]:
        live = {str(item["mac"]).upper(): item for item in self.mttl.list_devices() if item.get("mac")}
        saved = self.store.strips()
        mappings = self.store.mappings()
        result: list[dict] = []
        for mac in sorted(set(saved) | set(live)):
            meta = saved.get(mac, {})
            current = live.get(mac)
            state = str(meta.get("state") or ("pending" if current else "removed"))
            managed = bool(meta.get("managed", state == "active"))
            enabled = bool(meta.get("enabled", state == "active"))
            mapped_devices = [
                device_id for device_id, mapping in mappings.items() if mapping.get("mac") == mac
            ]
            outlets = (current or {}).get("outlets", [])
            item = {
                "mac": mac,
                "name": meta.get("name", f"Voltra {mac[-4:]}"),
                "online": bool(current),
                "managed": managed,
                "enabled": enabled,
                "state": state,
                "model": (current or {}).get("model") or meta.get("model"),
                "firmware_version": (current or {}).get("firmware_version") or meta.get("firmware_version"),
                "last_ip": ((current or {}).get("remote_address") or meta.get("last_ip") or "").rsplit(":", 1)[0],
                "connected_at": (current or {}).get("connected_at"),
                "last_seen_at": (current or {}).get("last_seen_at") or meta.get("last_seen_at"),
                "outlets": outlets,
                "mapped_devices": mapped_devices,
                "mapped_count": len(mapped_devices),
                "total_power_w": round(sum(float(x.get("power_w") or 0) for x in outlets), 2),
                "replaced_by": meta.get("replaced_by"),
                "replaced_from": meta.get("replaced_from"),
            }
            result.append(item)
        return result

    def overview(self) -> dict:
        strips = self.list_strips()
        active = [s for s in strips if s.get("managed") and s.get("state") in {"active", "disabled"}]
        pending = [s for s in strips if s.get("state") == "pending"]
        online = [s for s in active if s.get("online")]
        return {
            "version": __version__,
            "mode": "demo" if os.getenv("VOLTRA_DEMO", "").lower() in {"1", "true", "yes", "on"} else "real",
            "strips": strips,
            "ps4_devices": self.store.ps4_devices(),
            "mappings": self.store.mappings(),
            "summary": {
                "active_strips": len(active),
                "online_strips": len(online),
                "pending_strips": len(pending),
                "mapped_devices": len(self.store.mappings()),
                "total_power_w": round(sum(float(s.get("total_power_w") or 0) for s in active), 2),
            },
        }


    def ps4_power_status(self, device_id: str) -> dict:
        mapping = self.store.mapping(device_id)
        if not mapping:
            return {"ps4_id": device_id, "mapped": False, "online": False, "relay": None}
        mac = mapping["mac"]
        outlet = mapping["outlet"]
        strip_meta = self.store.strip(mac) or {}
        controllable = self.store.strip_controllable(mac)
        if not controllable:
            return {
                "ps4_id": device_id,
                "mapped": True,
                "online": False,
                "relay": None,
                "control_enabled": False,
                "strip_state": strip_meta.get("state"),
                **mapping,
            }
        try:
            session = self.mttl.get(mac)
        except KeyError:
            return {"ps4_id": device_id, "mapped": True, "online": False, "relay": None, "control_enabled": True, **mapping}
        snapshot = session.snapshot()
        outlet_info = next((x for x in snapshot.get("outlets", []) if x.get("channel") == outlet), None)
        return {
            "ps4_id": device_id,
            "mapped": True,
            "online": True,
            "control_enabled": True,
            "relay": outlet_info.get("relay") if outlet_info else None,
            "outlet_status": outlet_info,
            **mapping,
        }

    def set_ps4_power(self, device_id: str, on: bool) -> dict:
        mapping = self.store.mapping(device_id)
        if not mapping:
            raise KeyError(f"PS4 device {device_id} has no power mapping")
        self.store.require_strip_controllable(mapping["mac"])
        session = self.mttl.get(mapping["mac"])
        snapshot = session.set_outlet(int(mapping["outlet"]), on)
        return {
            "ok": True,
            "ps4_id": device_id,
            "on": on,
            "mapping": mapping,
            "device": snapshot,
        }


def start_http(
    mttl: MTTLServer,
    host: str,
    port: int,
    store: ConfigStore | None = None,
    api_token: str = "",
    cors_origin: str = "*",
):
    store = store or ConfigStore("data/voltra.json")
    server = VoltraHTTPServer((host, port), mttl, store=store, api_token=api_token, cors_origin=cors_origin)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[HTTP] dashboard: http://{host}:{port}/voltra")
    print(f"[HTTP] API root:  http://{host}:{port}/voltra/api")
    return server
