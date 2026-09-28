from __future__ import annotations

import ipaddress
import socket


def _command(sock: socket.socket, command: str) -> str:
    sock.sendall((command + "\r\n").encode("utf-8"))
    response = sock.recv(2048)
    return response.decode("utf-8", errors="replace").strip()


def provision_device(
    ssid: str,
    password: str,
    server_ip: str,
    device_ip: str = "192.168.1.1",
    port: int = 30300,
    timeout: float = 5.0,
) -> dict:
    """Provision a strip while this host can reach its TONLY_TAP setup AP."""
    if not ssid or len(ssid) > 64:
        raise ValueError("invalid Wi-Fi SSID")
    if ":" in ssid or "\r" in ssid or "\n" in ssid:
        raise ValueError("SSID contains unsupported characters for MTTL setup protocol")
    if ":" in password or "\r" in password or "\n" in password:
        raise ValueError("Wi-Fi password contains unsupported characters for MTTL setup protocol")
    ipaddress.ip_address(server_ip)
    ipaddress.ip_address(device_ip)

    responses: list[dict] = []
    with socket.create_connection((device_ip, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        for command in (
            f"up:ip:{server_ip}",
            f"up:connect:{ssid}:{password}",
            "up:reboot:0",
        ):
            responses.append({"command": command.split(":", 2)[0:2], "response": _command(sock, command)})
    return {"ok": True, "device_ip": device_ip, "server_ip": server_ip, "responses": responses}
