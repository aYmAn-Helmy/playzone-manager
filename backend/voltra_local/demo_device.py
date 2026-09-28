from __future__ import annotations

import socket
import time


def _getinfo(states: dict[int, bool]) -> str:
    chunks: list[str] = []
    for ch in range(1, 5):
        relay = "on" if states[ch] else "off"
        fields = [
            "0", relay, "0", "off", "off",
            str(4500 if states[ch] else 0),
            f"{ch * 100:08X}", "00000000", "00000000",
            "on", "00", "27",
        ]
        chunks.extend([str(ch), ";".join(fields)])
    return "up:getinfo:" + ":".join(chunks)


def run_demo_device(host: str = "127.0.0.1", port: int = 10086, mac: str = "D8AA59D28888") -> None:
    """Run an in-process fake MTTL-W01. Disabled by default."""
    states = {1: False, 2: False, 3: False, 4: False}
    while True:
        try:
            with socket.create_connection((host, port), timeout=5) as sock:
                sock.settimeout(None)
                sock.sendall(
                    f"up:bootinfo:lgutap;{mac};{mac};1.0.66-demo;connect\r\n".encode()
                )
                buffer = ""
                while True:
                    data = sock.recv(4096)
                    if not data:
                        break
                    buffer += data.decode("utf-8", errors="replace")
                    while "\r\n" in buffer:
                        line, buffer = buffer.split("\r\n", 1)
                        if not line:
                            continue
                        if line == "up:getinfo:all":
                            reply = _getinfo(states)
                        elif line.startswith("up:onoff:"):
                            _, _, channel, action = line.split(":")
                            states[int(channel)] = action == "on"
                            reply = line
                        else:
                            reply = line
                        sock.sendall((reply + "\r\n").encode())
        except OSError as exc:
            print(f"[DEMO] reconnecting after error: {exc}")
            time.sleep(2)
