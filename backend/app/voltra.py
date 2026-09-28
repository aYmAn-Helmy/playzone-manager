from __future__ import annotations

import os
from urllib.parse import quote

import httpx


VOLTRA_BASE_URL = os.getenv("VOLTRA_BASE_URL", "http://127.0.0.1:8086").rstrip("/")
VOLTRA_API_TOKEN = os.getenv("VOLTRA_API_TOKEN", "").strip()
VOLTRA_TIMEOUT_SECONDS = float(os.getenv("VOLTRA_TIMEOUT_SECONDS", "3"))


class VoltraError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    if not VOLTRA_API_TOKEN:
        return {}
    return {"Authorization": f"Bearer {VOLTRA_API_TOKEN}"}


def request(method: str, path: str, payload: dict | None = None, timeout_seconds: float | None = None) -> dict:
    try:
        response = httpx.request(
            method,
            f"{VOLTRA_BASE_URL}{path}",
            headers=_headers(),
            json=payload,
            timeout=VOLTRA_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds,
        )
    except httpx.RequestError as exc:
        raise VoltraError("Voltra local service is unavailable") from exc

    if response.is_error:
        try:
            detail = response.json().get("error") or response.json().get("detail")
        except (ValueError, AttributeError):
            detail = None
        raise VoltraError(str(detail or f"Voltra returned HTTP {response.status_code}"))

    try:
        value = response.json()
    except ValueError as exc:
        raise VoltraError("Voltra returned an invalid response") from exc
    if not isinstance(value, dict):
        raise VoltraError("Voltra returned an invalid response")
    return value


def sync_stations(stations: list[object]) -> dict:
    devices = [
        {
            "id": str(getattr(station, "id")),
            "name": str(getattr(station, "name") or getattr(station, "code")),
        }
        for station in stations
    ]
    return request("POST", "/voltra/api/ps4/sync", {"devices": devices, "prune": False})


def power_status(station_id: int, timeout_seconds: float | None = None) -> dict:
    device_id = quote(str(station_id), safe="")
    return request("GET", f"/voltra/api/ps4/{device_id}/power", timeout_seconds=timeout_seconds)


def power_statuses(station_ids: list[int], timeout_seconds: float | None = None) -> dict[int, dict]:
    """Fetch display-power state for many stations using one Voltra request.

    The embedded Voltra API already exposes a complete overview.  Reading that
    once avoids one HTTP round-trip per station during the dashboard poll.  If
    an older external Voltra build does not expose the overview endpoint, fall
    back to the individual endpoint for compatibility.
    """
    ids = [int(value) for value in station_ids]
    if not ids:
        return {}

    try:
        overview = request("GET", "/voltra/api/overview", timeout_seconds=timeout_seconds)
        mappings_raw = overview.get("mappings") or {}
        strips_raw = overview.get("strips") or []
        mappings = mappings_raw if isinstance(mappings_raw, dict) else {}
        strips = {
            str(strip.get("mac") or "").upper(): strip
            for strip in strips_raw
            if isinstance(strip, dict) and strip.get("mac")
        }

        result: dict[int, dict] = {}
        for station_id in ids:
            device_id = str(station_id)
            mapping = mappings.get(device_id)
            if not isinstance(mapping, dict):
                result[station_id] = {
                    "ps4_id": device_id,
                    "mapped": False,
                    "online": False,
                    "relay": None,
                }
                continue

            mac = str(mapping.get("mac") or "").upper()
            outlet = mapping.get("outlet")
            strip = strips.get(mac) or {}
            controllable = bool(
                strip.get("managed")
                and strip.get("enabled")
                and strip.get("state") == "active"
            )
            online = bool(strip.get("online")) and controllable
            outlets = strip.get("outlets") or []
            outlet_info = next(
                (
                    item
                    for item in outlets
                    if isinstance(item, dict) and item.get("channel") == outlet
                ),
                None,
            )
            result[station_id] = {
                "ps4_id": device_id,
                "mapped": True,
                "online": online,
                "control_enabled": controllable,
                "relay": outlet_info.get("relay") if outlet_info else None,
                "outlet_status": outlet_info,
                "strip_state": strip.get("state"),
                **mapping,
            }
        return result
    except VoltraError as exc:
        # Do not fan a failed overview out into N sequential requests.  A single
        # local-service timeout is enough to mark the optional power subsystem
        # unavailable while keeping the cashier dashboard responsive.
        return {
            station_id: {
                "ps4_id": str(station_id),
                "mapped": None,
                "online": False,
                "relay": None,
                "control_enabled": False,
                "error": str(exc),
            }
            for station_id in ids
        }


def set_power(station_id: int, on: bool) -> dict:
    device_id = quote(str(station_id), safe="")
    action = "on" if on else "off"
    return request("POST", f"/voltra/api/ps4/{device_id}/power/{action}")
