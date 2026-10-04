from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class DeviceCredentials:
    device_id: str
    device_token: str


class CloudError(RuntimeError):
    pass


class PlayZoneCloudClient:
    def __init__(
        self,
        base_url: str,
        credentials: DeviceCredentials | None = None,
        *,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.credentials = credentials
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def activate(
        self,
        installation_code: str,
        device_name: str,
        machine_fingerprint: str,
        app_version: str,
    ) -> tuple[DeviceCredentials, dict[str, Any]]:
        response = self._client.post(
            "/api/edge/activate",
            json={
                "installation_code": installation_code,
                "device_name": device_name,
                "machine_fingerprint": machine_fingerprint,
                "app_version": app_version,
            },
        )
        self._raise(response)
        body = response.json()
        creds = DeviceCredentials(body["device_id"], body["device_token"])
        self.credentials = creds
        return creds, body

    def _headers(self) -> dict[str, str]:
        if not self.credentials:
            raise CloudError("edge device is not activated")
        return {
            "Authorization": f"Bearer {self.credentials.device_token}",
            "X-Device-ID": self.credentials.device_id,
        }

    def heartbeat(self, app_version: str) -> dict[str, Any]:
        response = self._client.post(
            "/api/edge/heartbeat",
            headers=self._headers(),
            json={"app_version": app_version},
        )
        self._raise(response)
        return response.json()

    def config(self) -> dict[str, Any]:
        response = self._client.get("/api/edge/config", headers=self._headers())
        self._raise(response)
        return response.json()

    def push_events(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        response = self._client.post(
            "/api/edge/events",
            headers=self._headers(),
            json={"events": events},
        )
        self._raise(response)
        return response.json()

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            detail = response.json().get("detail") or response.text
        except Exception:
            detail = response.text
        raise CloudError(f"cloud HTTP {response.status_code}: {detail}")
