#!/bin/sh
set -eu

mkdir -p /tmp/playzone-data /tmp/voltra-data

export PLAYZONE_DB_PATH="${PLAYZONE_DB_PATH:-/tmp/playzone-data/playzone.db}"
export VOLTRA_BASE_URL="http://127.0.0.1:8086"
export VOLTRA_DEMO=1
export VOLTRA_DATA_DIR="/tmp/voltra-data"

(
  cd /app/voltra
  PORT=8086 VOLTRA_DEMO=1 VOLTRA_DATA_DIR="$VOLTRA_DATA_DIR" python -m voltra_local.app
) &
VOLTRA_PID=$!

python - <<'PY'
import json
import time
import urllib.error
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
        return json.loads(response.read().decode())

for _ in range(60):
    try:
        request("GET", "/health")
        break
    except Exception:
        time.sleep(0.25)
else:
    raise SystemExit("Voltra demo did not start")

devices = [{"id": str(i), "name": f"PS4-{i:02d}"} for i in range(1, 7)]
request("POST", "/voltra/api/ps4/sync", {"devices": devices, "prune": False})

# Online staging only: the bundled Voltra demo exposes one four-outlet strip.
# Map PS4-01..04 to those demo outlets so Start/End can be tested end-to-end.
demo_mac = "D8AA59D28888"
for station_id, outlet in zip(range(1, 5), range(1, 5)):
    for _ in range(20):
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

cd /app/playzone/backend
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
