import importlib
import os
from datetime import datetime, timezone

from fastapi.testclient import TestClient


def load_app(tmp_path):
    db_path = tmp_path / "cloud.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["PLAYZONE_PLATFORM_ADMIN_USERNAME"] = "platform"
    os.environ["PLAYZONE_PLATFORM_ADMIN_PASSWORD"] = "ChangeMe-123!"

    import app.models
    import app.db
    import app.main

    importlib.reload(app.models)
    importlib.reload(app.db)
    importlib.reload(app.main)
    return app.main.app


def auth(client, username, password, customer_code=None):
    payload = {"username": username, "password": password}
    if customer_code:
        payload["customer_code"] = customer_code
    r = client.post("/api/auth/login", json=payload)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def create_customer(client, admin_headers, name, username):
    r = client.post(
        "/api/admin/tenants",
        headers=admin_headers,
        json={
            "name": name,
            "owner_username": username,
            "owner_password": "OwnerPass-123!",
            "owner_display_name": username.title(),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_tenant_device_and_event_isolation(tmp_path):
    app = load_app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        admin = auth(client, "platform", "ChangeMe-123!")

        a = create_customer(client, admin, "Game Zone", "owner-a")
        b = create_customer(client, admin, "Arena", "owner-b")
        assert a["customer"]["code"] != b["customer"]["code"]

        owner_a = auth(client, "owner-a", "OwnerPass-123!", a["customer"]["code"])
        owner_b = auth(client, "owner-b", "OwnerPass-123!", b["customer"]["code"])

        oa = client.get("/api/customer/overview", headers=owner_a)
        ob = client.get("/api/customer/overview", headers=owner_b)
        assert oa.status_code == 200 and ob.status_code == 200
        assert oa.json()["customer"]["id"] == a["customer"]["id"]
        assert ob.json()["customer"]["id"] == b["customer"]["id"]
        assert client.get("/api/admin/tenants", headers=owner_a).status_code == 403

        code_resp = client.post(
            f"/api/admin/tenants/{a['customer']['id']}/installation-codes",
            headers=admin,
            json={"expires_hours": 24},
        )
        assert code_resp.status_code == 200, code_resp.text
        install_code = code_resp.json()["installation_code"]

        activation = client.post(
            "/api/edge/activate",
            json={
                "installation_code": install_code,
                "device_name": "GameZone-PC",
                "machine_fingerprint": "machine-fingerprint-A-0001",
                "app_version": "0.27",
            },
        )
        assert activation.status_code == 201, activation.text
        edge = activation.json()
        assert edge["customer"]["id"] == a["customer"]["id"]

        # Installation codes are one-time only.
        assert client.post(
            "/api/edge/activate",
            json={
                "installation_code": install_code,
                "device_name": "Other-PC",
                "machine_fingerprint": "machine-fingerprint-A-0002",
            },
        ).status_code == 401

        edge_headers = {
            "Authorization": f"Bearer {edge['device_token']}",
            "X-Device-ID": edge["device_id"],
        }
        assert client.post(
            "/api/edge/heartbeat",
            headers=edge_headers,
            json={"app_version": "saas-edge-0.1"},
        ).status_code == 200

        event = {
            "event_id": "evt-00000001",
            "sequence": 1,
            "event_type": "SESSION_STARTED",
            "session_ref": "local-session-1",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"station_id": 1, "controller_count": 2},
        }
        first = client.post("/api/edge/events", headers=edge_headers, json={"events": [event]})
        assert first.status_code == 200, first.text
        assert first.json()["accepted"] == ["evt-00000001"]

        second = client.post("/api/edge/events", headers=edge_headers, json={"events": [event]})
        assert second.status_code == 200
        assert second.json()["duplicates"] == ["evt-00000001"]

        after_a = client.get("/api/customer/overview", headers=owner_a).json()
        after_b = client.get("/api/customer/overview", headers=owner_b).json()
        assert after_a["received_events"] == 1
        assert after_b["received_events"] == 0

        revoke = client.post(f"/api/admin/edge-devices/{edge['device_id']}/revoke", headers=admin)
        assert revoke.status_code == 200
        assert client.post("/api/edge/heartbeat", headers=edge_headers, json={}).status_code == 401
