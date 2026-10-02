from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.getenv("PLAYZONE_DB_PATH", DATA_DIR / "playzone.db")).expanduser().resolve()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
BACKUP_DIR = DB_PATH.parent / "backups"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def configure_sqlite(connection, _record):
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def migrate_existing_database() -> None:
    """Add columns and indexes without replacing historical SQLite data."""
    columns = {
        "users": {"display_name": "VARCHAR(100)", "must_change_password": "BOOLEAN NOT NULL DEFAULT 0"},
        "invoices": {
            "gameplay_amount_piasters": "INTEGER NOT NULL DEFAULT 0",
            "base_gameplay_amount_piasters": "INTEGER NOT NULL DEFAULT 0",
            "multi_amount_piasters": "INTEGER NOT NULL DEFAULT 0",
            "multi_3_seconds": "INTEGER NOT NULL DEFAULT 0",
            "multi_3_amount_piasters": "INTEGER NOT NULL DEFAULT 0",
            "multi_4_seconds": "INTEGER NOT NULL DEFAULT 0",
            "multi_4_amount_piasters": "INTEGER NOT NULL DEFAULT 0",
            "products_amount_piasters": "INTEGER NOT NULL DEFAULT 0",
            "discount_piasters": "INTEGER NOT NULL DEFAULT 0",
            "payment_method": "VARCHAR(20) NOT NULL DEFAULT 'CASH'",
            "shift_id": "INTEGER REFERENCES shifts(id)",
        },
        "shifts": {
            "closed_by_user_id": "INTEGER REFERENCES users(id)",
        },
        "cash_movements": {
            "approval_status": "VARCHAR(20) NOT NULL DEFAULT 'APPROVED'",
            "decided_by_user_id": "INTEGER REFERENCES users(id)",
            "decided_at": "DATETIME",
        },
        "play_sessions": {
            "power_start_status": "VARCHAR(30)",
            "power_start_message": "VARCHAR(500)",
            "power_start_checked_at": "DATETIME",
            "session_type": "VARCHAR(20) NOT NULL DEFAULT 'OPEN'",
            "timed_total_seconds": "INTEGER",
            "timed_remaining_seconds": "INTEGER",
            "timed_expired_at": "DATETIME",
            "controller_count": "INTEGER NOT NULL DEFAULT 2",
            "weighted_billable_seconds_x100": "INTEGER NOT NULL DEFAULT 0",
            "pricing_checkpoint_billable_seconds": "INTEGER NOT NULL DEFAULT 0",
            "multi_3_billable_seconds": "INTEGER NOT NULL DEFAULT 0",
            "multi_4_billable_seconds": "INTEGER NOT NULL DEFAULT 0",
        },
    }
    with engine.begin() as connection:
        for table, additions in columns.items():
            existing = {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}
            needs_admin_reset = table == "users" and "must_change_password" not in existing
            for name, definition in additions.items():
                if name not in existing:
                    connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
            if needs_admin_reset and "role" in existing:
                connection.exec_driver_sql("UPDATE users SET must_change_password=1 WHERE role='ADMIN'")
        connection.execute(text("UPDATE invoices SET gameplay_amount_piasters = amount_piasters WHERE gameplay_amount_piasters = 0 AND products_amount_piasters = 0"))
        # Historical invoices predate the explicit Multi split. Keep their old
        # total intact and classify it as base gameplay rather than inventing a
        # controller breakdown that was never persisted.
        connection.execute(text("UPDATE invoices SET base_gameplay_amount_piasters = gameplay_amount_piasters WHERE base_gameplay_amount_piasters = 0 AND multi_amount_piasters = 0"))
        # EXPIRED timed sessions still occupy the station until the cashier
        # selects payment and finalizes the invoice. Rebuild the partial index
        # so a second session cannot be started on the same station meanwhile.
        connection.exec_driver_sql("DROP INDEX IF EXISTS uq_active_station")
        connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_active_station ON play_sessions(station_id) WHERE status IN ('RUNNING', 'PAUSED', 'EXPIRED')")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_invoices_created_at ON invoices(created_at)")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_play_sessions_status_type ON play_sessions(status, session_type)")
        if connection.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE type='table' AND name='shifts'").first():
            connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_open_employee_shift ON shifts(employee_id) WHERE status='OPEN'")
            open_count = int(connection.exec_driver_sql("SELECT COUNT(*) FROM shifts WHERE status='OPEN'").scalar_one() or 0)
            if open_count <= 1:
                # One physical cash drawer = one OPEN shift globally. This database
                # constraint closes the race where two employees submit OPEN at once.
                connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_single_open_cash_drawer ON shifts(status) WHERE status='OPEN'")
        if connection.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cash_movements'").first():
            connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_cash_movements_shift_approval ON cash_movements(shift_id, approval_status)")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
