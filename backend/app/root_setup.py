from __future__ import annotations

import argparse
import secrets
import sys

from sqlalchemy import select

from .activation import PASSWORDLESS_PRIVILEGED_KEY, set_setting
from .db import Base, SessionLocal, engine, migrate_existing_database
from .models import AuthToken, SystemSetting, User
from .security import hash_password

ROOT_PASSWORD_INITIALIZED_KEY = "root_password_initialized"


def _prepare() -> None:
    Base.metadata.create_all(engine)
    migrate_existing_database()


def is_initialized() -> bool:
    _prepare()
    with SessionLocal() as db:
        row = db.get(SystemSetting, ROOT_PASSWORD_INITIALIZED_KEY)
        root = db.scalar(select(User).where(User.username == "root", User.role == "ROOT"))
        return bool(root and row and row.value == "1")


def set_root_password(password: str) -> None:
    password = password.rstrip("\r\n")
    if len(password) < 12:
        raise ValueError("ROOT password must be at least 12 characters.")
    if len(password) > 200:
        raise ValueError("ROOT password must be at most 200 characters.")

    _prepare()
    with SessionLocal() as db:
        root = db.scalar(select(User).where(User.username == "root"))
        if root is None:
            root = User(
                username="root",
                display_name="System Root",
                password_hash=hash_password(secrets.token_urlsafe(32)),
                role="ROOT",
                must_change_password=True,
            )
            db.add(root)
            db.flush()
        root.role = "ROOT"
        root.is_active = True
        root.password_hash = hash_password(password)
        root.must_change_password = False
        # Defense in depth: v0.31 disables the old development bypass globally,
        # and main.py also refuses to apply it to ROOT even if re-enabled later.
        set_setting(db, PASSWORDLESS_PRIVILEGED_KEY, "0")
        set_setting(db, ROOT_PASSWORD_INITIALIZED_KEY, "1")
        for token in list(db.scalars(select(AuthToken).where(AuthToken.user_id == root.id))):
            db.delete(token)
        db.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="ZoneXplay ROOT password setup")
    parser.add_argument("command", choices=("status", "set"))
    args = parser.parse_args()

    if args.command == "status":
        if is_initialized():
            print("ROOT_PASSWORD_INITIALIZED")
            return 0
        print("ROOT_PASSWORD_SETUP_REQUIRED")
        return 3

    password = sys.stdin.readline()
    if not password:
        print("No password received on stdin.", file=sys.stderr)
        return 2
    try:
        set_root_password(password)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print("ROOT_PASSWORD_CONFIGURED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
