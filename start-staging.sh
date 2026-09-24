#!/bin/sh
set -eu

mkdir -p /tmp/playzone-data

export PLAYZONE_DB_PATH="${PLAYZONE_DB_PATH:-/tmp/playzone-data/playzone.db}"
export VOLTRA_BASE_URL="http://127.0.0.1:8086"
export VOLTRA_EMBEDDED=1
export VOLTRA_DEMO="${VOLTRA_DEMO:-1}"
export VOLTRA_TCP_PORT=10086
export VOLTRA_HTTP_PORT=8086
export VOLTRA_DATA_PATH="${VOLTRA_DATA_PATH:-/tmp/playzone-data/voltra.json}"

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
