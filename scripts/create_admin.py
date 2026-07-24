#!/usr/bin/env python3
"""scripts/create_admin.py — create a seed admin user (is_admin=1), bypassing the invite gate.

The FIRST admin can't self-signup: /api/signup ALWAYS requires an invite, and there's no inviter yet.
This standalone script seeds one directly. It writes to whatever DATABASE_URL points at (SQLite by
default, or Postgres when DATABASE_URL is set) through app.orm_session(), so the same command works in
both worlds. The password is read with getpass — never passed as an argument, so it never lands in
shell history or the process list.

    python3.13 scripts/create_admin.py                    # prompts for email + password
    python3.13 scripts/create_admin.py --email a@b.com    # prompts for the password only
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # repo root importable

from sqlalchemy import select

import app
from auth import hash_password
from models import User


def create_admin(email, password, display_name=None):
    """Insert an is_admin=1 user and return its id. Raises ValueError if the email is empty, the
    password is empty, or the email is already taken. Plain ORM insert via app.orm_session(), so it is
    dialect-agnostic (SQLite or Postgres) and honors the test harness's DB redirect when called in tests."""
    email = (email or "").strip().lower()
    if not email:
        raise ValueError("an email is required")
    if not password:
        raise ValueError("a password is required")
    with app.orm_session() as s:
        if s.execute(select(User.id).where(User.email == email)).first() is not None:
            raise ValueError(f"a user with email {email!r} already exists")
        user = User(
            email=email, password_hash=hash_password(password),
            display_name=(display_name or None), is_admin=1, created_at=app.now_utc(),
        )
        s.add(user)
        s.commit()
        return user.id


def main():
    ap = argparse.ArgumentParser(description="Create a seed admin user (is_admin=1).")
    ap.add_argument("--email", help="admin email (prompted if omitted)")
    ap.add_argument("--display-name", help="optional display name")
    args = ap.parse_args()

    email = (args.email or input("Admin email: ")).strip().lower()
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirm password: "):
        print("passwords don't match", file=sys.stderr)
        sys.exit(1)
    try:
        uid = create_admin(email, password, args.display_name)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"created admin {email} (id={uid})")


if __name__ == "__main__":
    main()
