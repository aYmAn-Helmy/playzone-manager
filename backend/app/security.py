from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher, exceptions as argon2_exceptions

PBKDF2_ITERATIONS = 310_000
PASSWORD_HASHER = PasswordHasher()


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    if encoded.startswith("$argon2"):
        try:
            return PASSWORD_HASHER.verify(encoded, password)
        except (argon2_exceptions.VerificationError, argon2_exceptions.InvalidHashError):
            return False
    try:
        algorithm, iterations, salt_b64, digest_b64 = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def needs_password_rehash(encoded: str) -> bool:
    return not encoded.startswith("$argon2") or PASSWORD_HASHER.check_needs_rehash(encoded)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_expiry(hours: int = 12) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)
