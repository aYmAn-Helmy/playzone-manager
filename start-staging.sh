#!/bin/sh
set -eu

mkdir -p /tmp/playzone-data

export PLAYZONE_DB_PATH="${PLAYZONE_DB_PATH:-/tmp/playzone-data/playzone.db}"
export VOLTRA_BASE_URL="http://127.0.0.1:8086"
export VOLTRA_EMBEDDED=1
export VOLTRA_DEMO=1
export VOLTRA_TCP_PORT=10086
export VOLTRA_HTTP_PORT=8086
export VOLTRA_DATA_PATH="${VOLTRA_DATA_PATH:-/tmp/playzone-data/voltra.json}"

# Staging helper only: wait for the embedded Voltra API, then sync six stations
# and map PS4-01..04 to the four outlets on the demo strip.
(
python - <<'PY'
import json
import time
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

cd /app/playzone/backend
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}"
