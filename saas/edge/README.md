# PlayZone Manager Edge Core

Local/offline foundation for the future Windows Edge Agent.

This milestone provides:

- A durable SQLite **pending event queue** with WAL mode.
- Monotonic per-device event sequence numbers that survive process restarts.
- Cloud activation/client primitives using the separate Edge device identity.
- Batch sync where accepted **and duplicate** events are acknowledged locally, making retries idempotent.
- Non-destructive offline behavior: network/cloud failures leave every event queued locally.

The next integration step is to call `EdgeStore.enqueue(...)` from the existing PlayZone v0.27 session/Voltra runtime for events such as `SESSION_STARTED`, `CONTROLLERS_CHANGED`, `SESSION_EXPIRED`, `SESSION_INVOICED`, `POWER_ON` and `POWER_OFF`, then run `SyncEngine.sync_once()` from the Windows Edge service.

The Edge SQLite database is runtime/cache state only. PostgreSQL Cloud remains the long-term business database.
