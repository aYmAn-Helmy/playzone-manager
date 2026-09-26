from pathlib import Path
import importlib.util


def load_patcher():
    path = Path(__file__).resolve().parents[1] / "integration" / "apply_to_v027.py"
    spec = importlib.util.spec_from_file_location("apply_to_v027", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_patch_main_text_adds_edge_hooks():
    mod = load_patcher()
    source = '''from .embedded_voltra import start_embedded_voltra, stop_embedded_voltra
app = FastAPI(title="PlayZone Manager API", version="0.27.0")

def on_startup():
    seed_data()
    start_embedded_voltra()
    start_timed_session_monitor()

def on_shutdown():
    stop_timed_session_monitor()
    stop_embedded_voltra()

def root_ready_user(user: User = Depends(ready_user)) -> User:
    if user.role != "ROOT":
        raise HTTPException(403, "Root role required")
    return user

def _background_power_on(session_id: int, station_id: int) -> None:
    with SessionLocal() as db:
        station = db.get(Station, station_id)
        session = db.get(PlaySession, session_id)
        power = _auto_power_on_after_session_start(db, station)
        try:
            session.power_start_checked_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            db.rollback()
            raise

def _background_power_off(station_id: int) -> None:
    with SessionLocal() as db:
        station = db.get(Station, station_id)
        if station is None:
            return
        _auto_power_off_after_session_end(db, station)
'''
    patched = mod.patch_main_text(source)
    assert "from .edge_runtime import (" in patched
    assert "start_edge_runtime()" in patched
    assert "stop_edge_runtime()" in patched
    assert '/api/root/edge/status' in patched
    assert '/api/root/edge/activate' in patched
    assert '/api/root/edge/sync' in patched
    assert "edge_record_power_event(station.id, True, power, session.id)" in patched
    assert "edge_record_power_event(station.id, False, power, None)" in patched

    # Applying the string patch twice should be safe/idempotent.
    assert mod.patch_main_text(patched) == patched
