from __future__ import annotations

import argparse
import getpass
import secrets
import sys
from sqlalchemy import select

from .db import Base, SessionLocal, engine
from .models import User
from .security import hash_password
from .main import seed_data


def main():
    parser = argparse.ArgumentParser(description="Create the first PlayZone admin account")
    parser.add_argument("--username", default="admin")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--password-stdin", action="store_true", help="Read initial password from standard input")
    source.add_argument("--generate-password", action="store_true", help="Generate and display a one-time password")
    args = parser.parse_args()

    Base.metadata.create_all(engine)
    seed_data()
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.username == args.username))
        if existing:
            # Development builds seed admin/root and allow them to sign in without
            # passwords. Treat bootstrap as idempotent so old setup instructions
            # do not fail on an already initialized local database.
            print(f"User {args.username!r} already exists; no bootstrap action required.")
            return

        password = (sys.stdin.readline().rstrip("\r\n") if args.password_stdin else
                    secrets.token_urlsafe(24) if args.generate_password else getpass.getpass("Initial admin password: "))
        if len(password) < 12:
            raise SystemExit("Initial admin password must contain at least 12 characters")
        db.add(User(username=args.username, display_name=args.username, password_hash=hash_password(password),
                    role="ADMIN", must_change_password=True))
        db.commit()
    print(f"Admin user {args.username!r} created.")
    if args.generate_password:
        print(f"One-time password: {password}")


if __name__ == "__main__":
    main()
