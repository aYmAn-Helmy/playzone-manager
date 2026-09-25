#!/bin/sh
set -eu

mkdir -p /tmp/playzone-data

export PLAYZONE_DB_PATH="${PLAYZONE_DB_PATH:-/tmp/playzone-data/playzone.db}"
export VOLTRA_BASE_URL="http://127.0.0.1:8086"
export VOLTRA_EMBEDDED=1
export VOLTRA_DEMO="${VOLTRA_DEMO:-1}"
export VOLTRA_TCP_PORT="${VOLTRA_TCP_PORT:-10086}"
export VOLTRA_HTTP_PORT="${VOLTRA_HTTP_PORT:-8086}"
export VOLTRA_DATA_PATH="${VOLTRA_DATA_PATH:-/tmp/playzone-data/voltra.json}"

start_tailscale() {
    if [ -z "${TS_AUTHKEY:-}" ]; then
        echo "Tailscale disabled: TS_AUTHKEY is not set."
        return 0
    fi

    ts_state_dir="${TS_STATE_DIR:-/tmp/tailscale}"
    ts_socket="${TS_SOCKET:-/tmp/tailscale/tailscaled.sock}"
    ts_hostname="${TS_HOSTNAME:-playzone-railway}"
    mkdir -p "$ts_state_dir" "$(dirname "$ts_socket")"

    echo "Starting Tailscale in userspace mode as $ts_hostname..."
    tailscaled \
        --tun=userspace-networking \
        --socket="$ts_socket" \
        --state="$ts_state_dir/tailscaled.state" \
        >"$ts_state_dir/tailscaled.log" 2>&1 &

    i=0
    while [ "$i" -lt 30 ]; do
        if tailscale --socket="$ts_socket" up \
            --auth-key="$TS_AUTHKEY" \
            --hostname="$ts_hostname" \
            --accept-dns=false >/dev/null 2>&1; then
            break
        fi
        i=$((i + 1))
        sleep 1
    done

    if [ "$i" -ge 30 ]; then
        echo "WARNING: Tailscale did not authenticate; PlayZone will continue without the private Voltra tunnel."
        return 0
    fi

    ts_ip="$(tailscale --socket="$ts_socket" ip -4 2>/dev/null || true)"
    echo "Tailscale connected. Userspace networking will forward inbound tailnet TCP/$VOLTRA_TCP_PORT to localhost:$VOLTRA_TCP_PORT."
    if [ -n "$ts_ip" ]; then
        echo "Private Voltra endpoint: $ts_ip:$VOLTRA_TCP_PORT"
    fi
}

# Tailscale is intentionally non-blocking. Billing/session operation remains
# available even if the private Voltra transport cannot be established.
start_tailscale &

# Staging/demo helper: wait for embedded Voltra, sync six stations, adopt the
# demo strip, then map PS4-01..04 to the demo outlets. This never targets real
# hardware because the demo MAC is fixed and only exists when VOLTRA_DEMO=1.
if [ "$VOLTRA_DEMO" = "1" ]; then
(
python - <<'PY'
import json
import time
import urllib.parse
import urllib.request

base = "http://127.0.0.1:8086"

def request(method, path, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        base + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3) as response:
        raw = response.read().decode()
        return json.loads(raw) if raw else {}

for _ in range(120):
    try:
        request("GET", "/health")
        break
    except Exception:
        time.sleep(0.25)
else:
    raise SystemExit("Embedded Voltra did not start")

devices = [{"id": str(i), "name": f"PS4-{i:02d}"} for i in range(1, 7)]
request("POST", "/voltra/api/ps4/sync", {"devices": devices, "prune": False})

demo_mac = "D8AA59D28888"
encoded_mac = urllib.parse.quote(demo_mac, safe="")
for _ in range(40):
    try:
        request("POST", f"/voltra/api/strips/{encoded_mac}/adopt", {"name": "Railway Demo Strip"})
        break
    except Exception:
        time.sleep(0.25)

for station_id, outlet in zip(range(1, 5), range(1, 5)):
    for _ in range(30):
        try:
            request(
                "PUT",
                f"/voltra/api/ps4/{station_id}/power-mapping",
                {"mac": demo_mac, "outlet": outlet},
            )
            break
        except Exception:
            time.sleep(0.25)
PY
) &
fi

cd /app/playzone/backend
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
