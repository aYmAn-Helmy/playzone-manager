from __future__ import annotations

import base64
import hashlib
import hmac
import json
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


def issue_signed_token(subject: str, purpose: str, secret: str, hours: int) -> str:
    """Issue an HMAC-signed stateless token.

    Used for the platform admin so Railway container replacement does not
    invalidate the admin session while staging still uses ephemeral SQLite.
    """
    if not secret:
        raise ValueError("signing secret is required")
    payload = {
        "sub": subject,
        "purpose": purpose,
        "exp": int(future(hours).timestamp()),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    signature = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    sig = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"pzs1.{body}.{sig}"


def verify_signed_token(token: str, purpose: str, secret: str) -> dict | None:
    if not secret or not token.startswith("pzs1."):
        return None
    try:
        prefix, body, sig = token.split(".", 2)
        if prefix != "pzs1":
            return None
        expected = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
        supplied = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
        if not hmac.compare_digest(expected, supplied):
            return None
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("purpose") != purpose:
            return None
        if int(payload.get("exp", 0)) <= int(utcnow().timestamp()):
            return None
        if not str(payload.get("sub") or "").strip():
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
