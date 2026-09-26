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

        live_a = client.get("/api/customer/overview", headers=owner_a).json()
        assert len(live_a["active_sessions"]) == 1
        assert live_a["active_sessions"][0]["status"] == "RUNNING"
        assert live_a["active_sessions"][0]["controller_count"] == 2

        change = {
            "event_id": "evt-00000002",
            "sequence": 2,
            "event_type": "CONTROLLERS_CHANGED",
            "session_ref": "local-session-1",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "station_id": 1,
                "station_code": "PS4-01",
                "controller_count": 3,
                "details": {"from": "2", "to": "3"},
            },
        }
        changed = client.post("/api/edge/events", headers=edge_headers, json={"events": [change]})
        assert changed.status_code == 200, changed.text
        changed_overview = client.get("/api/customer/overview", headers=owner_a).json()
        assert changed_overview["active_sessions"][0]["controller_count"] == 3

        invoice = {
            "event_id": "evt-00000003",
            "sequence": 3,
            "event_type": "SESSION_INVOICED",
            "session_ref": "local-session-1",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "invoice_id": 77,
                "invoice_number": "INV-TEST-0001",
                "session_id": 1,
                "station_id": 1,
                "station_code": "PS4-01",
                "amount_piasters": 9000,
                "gameplay_amount_piasters": 9000,
                "base_gameplay_amount_piasters": 6000,
                "multi_amount_piasters": 3000,
                "multi_3_seconds": 1200,
                "multi_3_amount_piasters": 1000,
                "multi_4_seconds": 1200,
                "multi_4_amount_piasters": 2000,
                "products_amount_piasters": 0,
                "discount_piasters": 0,
                "payment_method": "CASH",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        invoiced = client.post("/api/edge/events", headers=edge_headers, json={"events": [invoice]})
        assert invoiced.status_code == 200, invoiced.text

        after_a = client.get("/api/customer/overview", headers=owner_a).json()
        after_b = client.get("/api/customer/overview", headers=owner_b).json()
        assert after_a["received_events"] == 3
        assert after_a["active_sessions"] == []
        assert after_a["sales_summary"]["invoice_count"] == 1
        assert after_a["sales_summary"]["sales_piasters"] == 9000
        assert after_a["sales_summary"]["multi_revenue_piasters"] == 3000
        assert after_a["sales_summary"]["multi_3_seconds"] == 1200
        assert after_a["sales_summary"]["multi_4_seconds"] == 1200
        assert after_b["received_events"] == 0
        assert after_b["sales_summary"]["invoice_count"] == 0

        # Customer user management is strictly tenant-scoped.
        new_user = client.post(
            "/api/customer/users",
            headers=owner_a,
            json={
                "username": "cashier-a",
                "password": "CashierPass-123!",
                "display_name": "Cashier A",
                "role": "CASHIER",
            },
        )
        assert new_user.status_code == 201, new_user.text
        cashier_id = new_user.json()["id"]
        users_a = client.get("/api/customer/users", headers=owner_a)
        assert users_a.status_code == 200
        assert any(x["username"] == "cashier-a" for x in users_a.json()["users"])
        assert client.get("/api/customer/users", headers=owner_b).status_code == 200
        assert not any(x["username"] == "cashier-a" for x in client.get("/api/customer/users", headers=owner_b).json()["users"])

        cashier_login = auth(client, "cashier-a", "CashierPass-123!", a["customer"]["code"])
        assert client.get("/api/customer/overview", headers=cashier_login).status_code == 200
        assert client.get("/api/customer/users", headers=cashier_login).status_code == 403

        # OWNER/MANAGER may queue a remote Edge command; CASHIER and other
        # tenants may not. Edge delivery + ACK is tenant/device scoped.
        command = client.post(
            "/api/customer/commands",
            headers=owner_a,
            json={
                "command_type": "EXTEND_SESSION",
                "payload": {"session_ref": "local-session-1", "seconds": 1800},
            },
        )
        assert command.status_code == 201, command.text
        command_id = command.json()["id"]
        assert client.post(
            "/api/customer/commands",
            headers=cashier_login,
            json={
                "command_type": "POWER_ON",
                "payload": {"station_id": 1},
            },
        ).status_code == 403
        assert client.get("/api/customer/commands", headers=owner_b).json()["commands"] == []

        delivered = client.get("/api/edge/commands", headers=edge_headers)
        assert delivered.status_code == 200, delivered.text
        assert [x["id"] for x in delivered.json()["commands"]] == [command_id]
        assert delivered.json()["commands"][0]["payload"]["seconds"] == 1800

        ack = client.post(
            f"/api/edge/commands/{command_id}/ack",
            headers=edge_headers,
            json={"status": "SUCCESS", "result": {"applied": True}},
        )
        assert ack.status_code == 200, ack.text
        assert ack.json()["status"] == "SUCCESS"
        # Terminal ACK is idempotent and command is no longer redelivered.
        ack_again = client.post(
            f"/api/edge/commands/{command_id}/ack",
            headers=edge_headers,
            json={"status": "SUCCESS", "result": {"applied": True}},
        )
        assert ack_again.status_code == 200
        assert client.get("/api/edge/commands", headers=edge_headers).json()["commands"] == []
        listed = client.get("/api/customer/commands", headers=owner_a).json()["commands"]
        assert listed[0]["id"] == command_id
        assert listed[0]["status"] == "SUCCESS"

        disabled = client.put(
            f"/api/customer/users/{cashier_id}/status",
            headers=owner_a,
            json={"is_active": False},
        )
        assert disabled.status_code == 200
        assert client.get("/api/customer/overview", headers=cashier_login).status_code == 401

        suspended = client.put(
            f"/api/admin/tenants/{a['customer']['id']}/status",
            headers=admin,
            json={"status": "SUSPENDED"},
        )
        assert suspended.status_code == 200
        assert client.get("/api/customer/overview", headers=owner_a).status_code == 403
        assert client.post("/api/edge/heartbeat", headers=edge_headers, json={}).status_code == 403

        reactivated = client.put(
            f"/api/admin/tenants/{a['customer']['id']}/status",
            headers=admin,
            json={"status": "ACTIVE"},
        )
        assert reactivated.status_code == 200
        owner_a = auth(client, "owner-a", "OwnerPass-123!", a["customer"]["code"])

        revoke = client.post(f"/api/admin/edge-devices/{edge['device_id']}/revoke", headers=admin)
        assert revoke.status_code == 200
        assert client.post("/api/edge/heartbeat", headers=edge_headers, json={}).status_code == 401


def test_login_pages_do_not_depend_on_named_element_globals(tmp_path):
    app = load_app(tmp_path)
    with TestClient(app) as client:
        platform = client.get("/platform")
        customer = client.get("/")
        assert platform.status_code == 200
        assert customer.status_code == 200

        platform_html = platform.text
        customer_html = customer.text

        assert "login.classList" not in platform_html
        assert "login.classList" not in customer_html
        assert "document.getElementById('login').classList.add('hidden')" in platform_html
        assert "document.getElementById('login').classList.add('hidden')" in customer_html
        assert "document.getElementById('app').classList.remove('hidden')" in platform_html
        assert "document.getElementById('app').classList.remove('hidden')" in customer_html
