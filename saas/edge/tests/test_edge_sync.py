from __future__ import annotations

import json

import httpx

from playzone_edge.cloud import DeviceCredentials, PlayZoneCloudClient
from playzone_edge.store import EdgeStore
from playzone_edge.sync import SyncEngine


def test_offline_queue_survives_and_syncs_in_order(tmp_path):
    store = EdgeStore(tmp_path / "edge.db")
    a = store.enqueue("SESSION_STARTED", "session-1", {"station_id": 1})
    b = store.enqueue("CONTROLLERS_CHANGED", "session-1", {"from": 2, "to": 3})
    c = store.enqueue("SESSION_EXPIRED", "session-1", {})
    assert [x.sequence for x in (a, b, c)] == [1, 2, 3]

    def offline(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("internet down")

    offline_client = PlayZoneCloudClient(
        "https://cloud.invalid",
        DeviceCredentials("EDG-1", "secret"),
        transport=httpx.MockTransport(offline),
    )
    offline_result = SyncEngine(store, offline_client).sync_once()
    assert not offline_result.online
    assert store.pending_count() == 3
    offline_client.close()

    received = []

    def online(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Device-ID"] == "EDG-1"
        assert request.headers["Authorization"] == "Bearer secret"
        if request.url.path == "/api/edge/events":
            body = json.loads(request.content)
            received.extend(body["events"])
            return httpx.Response(
                200,
                json={
                    "accepted": [body["events"][0]["event_id"], body["events"][1]["event_id"]],
                    "duplicates": [body["events"][2]["event_id"]],
                },
            )
        raise AssertionError(request.url.path)

    online_client = PlayZoneCloudClient(
        "https://cloud.test",
        DeviceCredentials("EDG-1", "secret"),
        transport=httpx.MockTransport(online),
    )
    result = SyncEngine(store, online_client).sync_once()
    assert result.online
    assert result.sent == 3
    assert result.acknowledged == 3
    assert result.pending == 0
    assert [x["sequence"] for x in received] == [1, 2, 3]
    assert [x["event_type"] for x in received] == [
        "SESSION_STARTED",
        "CONTROLLERS_CHANGED",
        "SESSION_EXPIRED",
    ]
    online_client.close()


def test_sequence_continues_after_restart(tmp_path):
    path = tmp_path / "edge.db"
    first = EdgeStore(path)
    e1 = first.enqueue("SESSION_STARTED")
    del first
    second = EdgeStore(path)
    e2 = second.enqueue("SESSION_PAUSED")
    assert e1.sequence == 1
    assert e2.sequence == 2
