from __future__ import annotations

from dataclasses import dataclass

import httpx

from .cloud import CloudError, PlayZoneCloudClient
from .store import EdgeStore


@dataclass(frozen=True)
class SyncResult:
    online: bool
    sent: int = 0
    acknowledged: int = 0
    pending: int = 0
    error: str | None = None


class SyncEngine:
    def __init__(self, store: EdgeStore, cloud: PlayZoneCloudClient, batch_size: int = 500):
        self.store = store
        self.cloud = cloud
        self.batch_size = batch_size

    def sync_once(self) -> SyncResult:
        events = self.store.pending(self.batch_size)
        if not events:
            try:
                self.cloud.heartbeat("saas-edge-0.1")
                return SyncResult(online=True, pending=0)
            except (CloudError, httpx.HTTPError) as exc:
                return SyncResult(online=False, pending=0, error=str(exc))

        try:
            result = self.cloud.push_events([item.to_wire() for item in events])
        except (CloudError, httpx.HTTPError) as exc:
            return SyncResult(online=False, sent=0, acknowledged=0, pending=self.store.pending_count(), error=str(exc))

        acknowledged_ids = list(dict.fromkeys((result.get("accepted") or []) + (result.get("duplicates") or [])))
        acknowledged = self.store.acknowledge(acknowledged_ids)
        return SyncResult(
            online=True,
            sent=len(events),
            acknowledged=acknowledged,
            pending=self.store.pending_count(),
        )
