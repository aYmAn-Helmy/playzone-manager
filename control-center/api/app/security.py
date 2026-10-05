from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from fastapi import Header, HTTPException


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_secret(prefix: str, bytes_count: int = 32) -> str:
    return prefix + secrets.token_urlsafe(bytes_count)


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    expected = os.environ.get("CONTROL_CENTER_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(503, "CONTROL_CENTER_ADMIN_TOKEN is not configured")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(401, "Invalid admin token")
