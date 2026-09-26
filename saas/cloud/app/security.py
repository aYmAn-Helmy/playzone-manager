from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher, exceptions as argon2_exceptions

PASSWORD_HASHER = PasswordHasher()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(encoded, password)
    except (argon2_exceptions.VerificationError, argon2_exceptions.InvalidHashError):
        return False


def new_secret(bytes_count: int = 32) -> str:
    return secrets.token_urlsafe(bytes_count)


def secret_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def secure_equals_hash(raw: str, expected_hash: str) -> bool:
    return hmac.compare_digest(secret_hash(raw), expected_hash)


def future(hours: int) -> datetime:
    return utcnow() + timedelta(hours=hours)


def not_expired(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value > utcnow()
