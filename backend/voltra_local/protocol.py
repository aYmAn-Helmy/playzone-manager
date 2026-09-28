from __future__ import annotations

from dataclasses import asdict, dataclass
import re

BOOTINFO_PREFIX = "up:bootinfo:"
GETINFO_PREFIX = "up:getinfo:"
GETINFO_REQUEST = "up:getinfo:all"

_BOOTINFO_RE = re.compile(
    r"^up:bootinfo:([^;\r\n]{1,32});([0-9a-fA-F]{12});([0-9a-fA-F]{12});([^;\r\n]{1,64});connect$"
)
_ONOFF_RE = re.compile(r"^up:(?:event:)?onoff:([1-4]):(on|off)$")


@dataclass(frozen=True)
class BootInfo:
    model: str
    mac: str
    client_id: str
    firmware_version: str


@dataclass
class OutletInfo:
    channel: int
    relay: bool
    overload_protection: bool
    overheat_protection: bool
    power_raw: int
    power_w: float
    energy_wh: int
    energy_kwh: float
    previous_energy_wh: int
    temperature_c: int
    device_status: bool
    event_code: str
    configuration_hex: str
    test_state: int
    fixed_value: int

    def to_dict(self) -> dict:
        return asdict(self)


def parse_boot_info(frame: str) -> BootInfo | None:
    match = _BOOTINFO_RE.match(frame.strip())
    if not match:
        return None
    mac = match.group(2).upper()
    client_id = match.group(3).upper()
    if mac != client_id:
        return None
    return BootInfo(
        model=match.group(1),
        mac=mac,
        client_id=client_id,
        firmware_version=match.group(4),
    )


def format_onoff(outlet: int, on: bool) -> str:
    if outlet not in (1, 2, 3, 4):
        raise ValueError("outlet must be 1..4")
    return f"up:onoff:{outlet}:{'on' if on else 'off'}"


def parse_onoff(frame: str) -> tuple[int, bool] | None:
    match = _ONOFF_RE.match(frame.strip())
    if not match:
        return None
    return int(match.group(1)), match.group(2) == "on"


def parse_getinfo(frame: str) -> list[OutletInfo] | None:
    value = frame.strip()
    if not value.startswith(GETINFO_PREFIX):
        return None
    parts = value[len(GETINFO_PREFIX):].split(":")
    if len(parts) != 8:
        return None

    outlets: list[OutletInfo] = []
    seen: set[int] = set()
    for idx in range(0, 8, 2):
        try:
            channel = int(parts[idx], 10)
        except ValueError:
            return None
        if channel not in (1, 2, 3, 4) or channel in seen:
            return None

        fields = parts[idx + 1].split(";")
        if len(fields) != 12:
            return None
        try:
            test_state = int(fields[0], 10)
            relay = _parse_onoff_word(fields[1])
            fixed_value = int(fields[2], 10)
            overload = _parse_onoff_word(fields[3])
            overheat = _parse_onoff_word(fields[4])
            power_raw = int(fields[5], 10)
            energy_wh = _parse_hex(fields[6], 8)
            previous_energy_wh = _parse_hex(fields[7], 8)
            _parse_hex(fields[8], 8)
            device_status = _parse_onoff_word(fields[9])
            _parse_hex(fields[10], 2)
            temperature_c = int(fields[11], 10)
        except (TypeError, ValueError):
            return None

        seen.add(channel)
        outlets.append(
            OutletInfo(
                channel=channel,
                relay=relay,
                overload_protection=overload,
                overheat_protection=overheat,
                power_raw=power_raw,
                power_w=power_raw / 1000.0,
                energy_wh=energy_wh,
                energy_kwh=energy_wh / 1000.0,
                previous_energy_wh=previous_energy_wh,
                temperature_c=temperature_c,
                device_status=device_status,
                event_code=fields[10].upper(),
                configuration_hex=fields[8].upper(),
                test_state=test_state,
                fixed_value=fixed_value,
            )
        )

    if len(seen) != 4:
        return None
    outlets.sort(key=lambda item: item.channel)
    return outlets


def looks_like_incomplete_getinfo(frame: str) -> bool:
    value = frame.lstrip()
    if not value.startswith(GETINFO_PREFIX):
        return False
    parts = value[len(GETINFO_PREFIX):].split(":")
    if len(parts) < 8:
        return True
    if len(parts) > 8:
        return False
    return len(parts[-1].split(";")) < 12


def _parse_onoff_word(value: str) -> bool:
    if value == "on":
        return True
    if value == "off":
        return False
    raise ValueError("expected on/off")


def _parse_hex(value: str, length: int) -> int:
    if len(value) != length or not re.fullmatch(r"[0-9a-fA-F]+", value):
        raise ValueError("invalid hex field")
    return int(value, 16)
