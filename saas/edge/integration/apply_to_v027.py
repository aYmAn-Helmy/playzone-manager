from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def patch_main_text(s: str) -> str:
    if 'version="0.27.0"' not in s and "version='0.27.0'" not in s:
        raise RuntimeError("Expected PlayZone Manager v0.27 main.py")

    import_anchor = "from .embedded_voltra import start_embedded_voltra, stop_embedded_voltra\n"
    import_block = import_anchor + """from .edge_runtime import (
    activate as edge_activate,
    record_power_event as edge_record_power_event,
    start_edge_runtime,
    status as edge_status,
    stop_edge_runtime,
    sync_once as edge_sync_once,
)
"""
    if "from .edge_runtime import (" not in s:
        if import_anchor not in s:
            raise RuntimeError("Could not locate embedded Voltra import")
        s = s.replace(import_anchor, import_block, 1)

    startup_old = """def on_startup():
    seed_data()
    start_embedded_voltra()
    start_timed_session_monitor()
"""
    startup_new = """def on_startup():
    seed_data()
    start_embedded_voltra()
    start_timed_session_monitor()
    start_edge_runtime()
"""
    if "    start_edge_runtime()" not in s:
        if startup_old not in s:
            raise RuntimeError("Could not locate startup hook")
        s = s.replace(startup_old, startup_new, 1)

    shutdown_old = """def on_shutdown():
    stop_timed_session_monitor()
    stop_embedded_voltra()
"""
    shutdown_new = """def on_shutdown():
    stop_edge_runtime()
    stop_timed_session_monitor()
    stop_embedded_voltra()
"""
    if "    stop_edge_runtime()" not in s:
        if shutdown_old not in s:
            raise RuntimeError("Could not locate shutdown hook")
        s = s.replace(shutdown_old, shutdown_new, 1)

    root_anchor = """def root_ready_user(user: User = Depends(ready_user)) -> User:
    if user.role != "ROOT":
        raise HTTPException(403, "Root role required")
    return user


"""
    root_routes = root_anchor + """@app.get("/api/root/edge/status")
def api_edge_status(_: User = Depends(root_ready_user)):
    return edge_status()


@app.post("/api/root/edge/activate")
def api_edge_activate(payload: dict, actor: User = Depends(root_ready_user), db: Session = Depends(get_db)):
    cloud_url = str(payload.get("cloud_url") or "").strip()
    installation_code = str(payload.get("installation_code") or "").strip()
    if not cloud_url or not installation_code:
        raise HTTPException(422, "cloud_url and installation_code are required")
    try:
        result = edge_activate(cloud_url, installation_code)
    except Exception as exc:
        raise HTTPException(409, str(exc)) from exc
    audit(db, actor, "EDGE_ACTIVATED", "system", None, f"cloud={cloud_url};device={result.get('device_id') or ''}")
    db.commit()
    return result


@app.post("/api/root/edge/sync")
def api_edge_sync(_: User = Depends(root_ready_user)):
    return edge_sync_once()


"""
    if "/api/root/edge/status" not in s:
        if root_anchor not in s:
            raise RuntimeError("Could not locate ROOT dependency hook")
        s = s.replace(root_anchor, root_routes, 1)

    power_on_old = """            session.power_start_checked_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            db.rollback()
            raise
"""
    power_on_new = """            session.power_start_checked_at = datetime.now(timezone.utc)
            db.commit()
            edge_record_power_event(station.id, True, power, session.id)
        except Exception:
            db.rollback()
            raise
"""
    if "edge_record_power_event(station.id, True" not in s:
        if power_on_old not in s:
            raise RuntimeError("Could not locate background power-on commit")
        s = s.replace(power_on_old, power_on_new, 1)

    power_off_old = """        if station is None:
            return
        _auto_power_off_after_session_end(db, station)
"""
    power_off_new = """        if station is None:
            return
        power = _auto_power_off_after_session_end(db, station)
        edge_record_power_event(station.id, False, power, None)
"""
    if "edge_record_power_event(station.id, False" not in s:
        if power_off_old not in s:
            raise RuntimeError("Could not locate background power-off call")
        s = s.replace(power_off_old, power_off_new, 1)

    return s


def apply(target: Path) -> None:
    target = target.resolve()
    main_path = target / "backend" / "app" / "main.py"
    if not main_path.exists():
        raise RuntimeError(f"Missing {main_path}")

    runtime_source = Path(__file__).with_name("v027_edge_runtime.py")
    if not runtime_source.exists():
        raise RuntimeError(f"Missing {runtime_source}")

    current = main_path.read_text(encoding="utf-8")
    patched = patch_main_text(current)
    main_path.write_text(patched, encoding="utf-8")
    shutil.copy2(runtime_source, target / "backend" / "app" / "edge_runtime.py")
    print(f"Edge runtime integrated into {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Integrate PlayZone SaaS Edge bridge into a v0.27 portable tree")
    parser.add_argument("target", help="Path to PlayZone-Portable-Bootstrap-v0.27 directory")
    args = parser.parse_args()
    apply(Path(args.target))


if __name__ == "__main__":
    main()
