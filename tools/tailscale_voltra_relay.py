#!/usr/bin/env python3
"""LAN-to-Tailnet TCP relay for Voltra smart strips.

The strip firmware can only be provisioned with an IPv4 server address and
always connects to TCP/10086. Run this relay on a machine in the same LAN as
the strips, with Tailscale installed and connected. Provision the strips with
this machine's LAN IPv4 address; the relay forwards raw TCP to PlayZone over
the tailnet.
"""

from __future__ import annotations

import argparse
import logging
import selectors
import socket
import threading
from contextlib import closing

BUFFER_SIZE = 64 * 1024


def configure_socket(sock: socket.socket) -> None:
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)


def bridge(
    client: socket.socket,
    client_addr: tuple[str, int],
    target: str,
    target_port: int,
    timeout: float,
) -> None:
    label = f"{client_addr[0]}:{client_addr[1]}"
    try:
        with closing(client):
            configure_socket(client)
            logging.info("%s -> %s:%s connecting", label, target, target_port)
            with socket.create_connection((target, target_port), timeout=timeout) as upstream:
                configure_socket(upstream)
                upstream.settimeout(None)
                client.settimeout(None)

                selector = selectors.DefaultSelector()
                try:
                    selector.register(client, selectors.EVENT_READ, upstream)
                    selector.register(upstream, selectors.EVENT_READ, client)
                    logging.info("%s connected", label)
                    while True:
                        for key, _ in selector.select(timeout=60):
                            source = key.fileobj
                            destination = key.data
                            data = source.recv(BUFFER_SIZE)
                            if not data:
                                logging.info("%s disconnected", label)
                                return
                            destination.sendall(data)
                finally:
                    selector.close()
    except (OSError, ConnectionError) as exc:
        logging.warning("%s relay error: %s", label, exc)


def serve(
    listen_host: str,
    listen_port: int,
    target: str,
    target_port: int,
    timeout: float,
) -> None:
    family = socket.AF_INET6 if ":" in listen_host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((listen_host, listen_port))
        server.listen(128)
        logging.info(
            "Listening on %s:%s -> %s:%s",
            listen_host,
            listen_port,
            target,
            target_port,
        )
        while True:
            client, addr = server.accept()
            thread = threading.Thread(
                target=bridge,
                args=(client, addr, target, target_port, timeout),
                daemon=True,
            )
            thread.start()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Forward Voltra TCP/10086 from the local LAN to PlayZone over Tailscale."
        )
    )
    parser.add_argument(
        "--target",
        required=True,
        help="PlayZone Tailscale MagicDNS name or 100.x address",
    )
    parser.add_argument("--target-port", type=int, default=10086)
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=10086)
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        serve(
            args.listen_host,
            args.listen_port,
            args.target,
            args.target_port,
            args.connect_timeout,
        )
    except KeyboardInterrupt:
        logging.info("Stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
