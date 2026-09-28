from __future__ import annotations

from datetime import datetime, timezone
import socket
import threading
import time
from typing import Callable

from .protocol import (
    BOOTINFO_PREFIX,
    GETINFO_PREFIX,
    GETINFO_REQUEST,
    BootInfo,
    OutletInfo,
    format_onoff,
    looks_like_incomplete_getinfo,
    parse_boot_info,
    parse_getinfo,
    parse_onoff,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DeviceSession:
    def __init__(self, server: "MTTLServer", sock: socket.socket, address: tuple[str, int]):
        self.server = server
        self.sock = sock
        self.address = address
        self.boot: BootInfo | None = None
        self.connected_at = utc_now()
        self.last_seen_at = self.connected_at
        self.last_info_at: str | None = None
        self.outlets: dict[int, OutletInfo] = {}
        self.closed = threading.Event()
        self._send_lock = threading.Lock()
        self._command_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending_predicate: Callable[[str], bool] | None = None
        self._pending_event: threading.Event | None = None
        self._pending_result: str | None = None
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._buffer = ""
        self._partial_getinfo: str | None = None

    @property
    def mac(self) -> str | None:
        return self.boot.mac if self.boot else None

    def start(self) -> None:
        self.sock.settimeout(1.0)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self._reader.start()

    def close(self) -> None:
        if self.closed.is_set():
            return
        self.closed.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
        with self._pending_lock:
            if self._pending_event:
                self._pending_event.set()

    def snapshot(self) -> dict:
        return {
            "mac": self.mac,
            "model": self.boot.model if self.boot else None,
            "firmware_version": self.boot.firmware_version if self.boot else None,
            "online": not self.closed.is_set(),
            "remote_address": f"{self.address[0]}:{self.address[1]}",
            "connected_at": self.connected_at,
            "last_seen_at": self.last_seen_at,
            "last_info_at": self.last_info_at,
            "outlets": [self.outlets[idx].to_dict() for idx in sorted(self.outlets)],
        }

    def set_outlet(self, outlet: int, on: bool) -> dict:
        command = format_onoff(outlet, on)
        self.request(command, lambda frame: frame.strip() == command)
        current = self.outlets.get(outlet)
        if current:
            current.relay = on
        return self.snapshot()

    def query_info(self) -> dict:
        self.request(GETINFO_REQUEST, lambda frame: parse_getinfo(frame) is not None)
        return self.snapshot()

    def request(self, command: str, predicate: Callable[[str], bool]) -> str:
        if self.closed.is_set():
            raise RuntimeError("device is offline")
        with self._command_lock:
            event = threading.Event()
            with self._pending_lock:
                self._pending_predicate = predicate
                self._pending_event = event
                self._pending_result = None
            self._send_line(command)
            if not event.wait(self.server.response_timeout):
                with self._pending_lock:
                    self._pending_predicate = None
                    self._pending_event = None
                    self._pending_result = None
                raise TimeoutError(f"timeout waiting for response to {command!r}")
            if self.closed.is_set():
                raise RuntimeError("device disconnected")
            with self._pending_lock:
                result = self._pending_result
                self._pending_predicate = None
                self._pending_event = None
                self._pending_result = None
            if result is None:
                raise RuntimeError("request ended without a response")
            return result

    def _send_line(self, line: str) -> None:
        payload = (line + "\r\n").encode("utf-8")
        with self._send_lock:
            self.sock.sendall(payload)

    def _read_loop(self) -> None:
        boot_deadline = time.monotonic() + self.server.boot_timeout
        try:
            while not self.closed.is_set():
                if not self.boot and time.monotonic() > boot_deadline:
                    raise TimeoutError("bootinfo timeout")
                try:
                    chunk = self.sock.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                self.last_seen_at = utc_now()
                self._buffer += chunk.decode("utf-8", errors="replace")
                if len(self._buffer) > 64 * 1024:
                    raise RuntimeError("receive buffer exceeded 64 KiB")
                while "\r\n" in self._buffer:
                    line, self._buffer = self._buffer.split("\r\n", 1)
                    self._accept_wire_line(line.strip("\x00"))
        except Exception as exc:
            if not self.closed.is_set():
                print(f"[TCP] {self.address}: {exc}")
        finally:
            self.close()
            self.server.unregister(self)

    def _accept_wire_line(self, line: str) -> None:
        if not line:
            return
        candidate = line
        if self._partial_getinfo:
            if line.startswith("up:"):
                print(f"[TCP] discarded incomplete getinfo from {self.mac or self.address}")
            else:
                candidate = self._partial_getinfo + line
            self._partial_getinfo = None
        if candidate.startswith(GETINFO_PREFIX) and parse_getinfo(candidate) is None and looks_like_incomplete_getinfo(candidate):
            self._partial_getinfo = candidate
            return
        self._handle_frame(candidate)

    def _handle_frame(self, frame: str) -> None:
        if self.boot is None:
            if not frame.startswith(BOOTINFO_PREFIX):
                return
            boot = parse_boot_info(frame)
            if not boot or boot.model.lower() != "lgutap":
                raise RuntimeError("invalid bootinfo")
            self.boot = boot
            self.server.register(self)
            print(f"[TCP] registered {boot.mac} firmware={boot.firmware_version} from {self.address[0]}")
            threading.Thread(target=self._initial_query, daemon=True).start()
            return

        info = parse_getinfo(frame)
        if info is not None:
            self.outlets = {item.channel: item for item in info}
            self.last_info_at = utc_now()

        onoff = parse_onoff(frame)
        if onoff:
            outlet, on = onoff
            current = self.outlets.get(outlet)
            if current:
                current.relay = on

        with self._pending_lock:
            predicate = self._pending_predicate
            event = self._pending_event
            if predicate and event and predicate(frame):
                self._pending_result = frame
                event.set()

    def _initial_query(self) -> None:
        time.sleep(0.15)
        try:
            self.query_info()
        except Exception as exc:
            print(f"[TCP] initial getinfo failed for {self.mac}: {exc}")


class MTTLServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 10086, poll_interval: float = 10.0,
                 response_timeout: float = 3.0, boot_timeout: float = 10.0,
                 on_device_seen: Callable[[dict], None] | None = None):
        self.host = host
        self.port = port
        self.poll_interval = poll_interval
        self.response_timeout = response_timeout
        self.boot_timeout = boot_timeout
        self.on_device_seen = on_device_seen
        self._listen: socket.socket | None = None
        self._stop = threading.Event()
        self._sessions: dict[str, DeviceSession] = {}
        self._lock = threading.RLock()

    def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(32)
        sock.settimeout(1.0)
        self._listen = sock
        threading.Thread(target=self._accept_loop, daemon=True).start()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        print(f"[TCP] listening on {self.host}:{self.port}")

    def stop(self) -> None:
        self._stop.set()
        if self._listen:
            try:
                self._listen.close()
            except OSError:
                pass
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            session.close()

    def register(self, session: DeviceSession) -> None:
        assert session.mac
        with self._lock:
            previous = self._sessions.get(session.mac)
            self._sessions[session.mac] = session
        if previous and previous is not session:
            previous.close()
        if self.on_device_seen:
            try:
                self.on_device_seen(session.snapshot())
            except Exception as exc:
                print(f"[STORE] failed to persist {session.mac}: {exc}")

    def unregister(self, session: DeviceSession) -> None:
        if not session.mac:
            return
        with self._lock:
            if self._sessions.get(session.mac) is session:
                del self._sessions[session.mac]
                print(f"[TCP] {session.mac} disconnected")

    def get(self, mac: str) -> DeviceSession:
        normalized = mac.replace(":", "").replace("-", "").upper()
        with self._lock:
            session = self._sessions.get(normalized)
        if not session or session.closed.is_set():
            raise KeyError(f"device {normalized} is offline")
        return session

    def list_devices(self) -> list[dict]:
        with self._lock:
            return [session.snapshot() for session in self._sessions.values()]

    def _accept_loop(self) -> None:
        assert self._listen
        while not self._stop.is_set():
            try:
                client, address = self._listen.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    break
                raise
            DeviceSession(self, client, address).start()

    def _poll_loop(self) -> None:
        while not self._stop.wait(self.poll_interval):
            with self._lock:
                sessions = list(self._sessions.values())
            for session in sessions:
                if session.closed.is_set():
                    continue
                try:
                    session.query_info()
                except Exception as exc:
                    print(f"[TCP] poll failed for {session.mac}: {exc}")
