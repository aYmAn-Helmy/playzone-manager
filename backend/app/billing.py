from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from .models import PlaySession


def normalize_utc(value: datetime) -> datetime:
    # SQLite may return naive datetimes even when timezone=True. Treat persisted naive values as UTC.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def seconds_between(start: datetime, end: datetime) -> int:
    start = normalize_utc(start)
    end = normalize_utc(end)
    return max(0, int((end - start).total_seconds()))


def segment_billable_seconds(*, duration_seconds: int, first_segment: bool, grace_seconds: int) -> int:
    if first_segment:
        return max(0, duration_seconds - grace_seconds)
    return max(0, duration_seconds)


def live_billable_seconds(session: PlaySession, now: datetime) -> int:
    total = session.billable_seconds_accrued
    if session.status == "RUNNING" and session.current_segment_started_at is not None:
        duration = seconds_between(session.current_segment_started_at, now)
        total += segment_billable_seconds(
            duration_seconds=duration,
            first_segment=session.first_segment,
            grace_seconds=session.grace_seconds,
        )
    return total


def amount_piasters(hourly_rate_piasters: int, billable_seconds: int) -> int:
    amount = (Decimal(hourly_rate_piasters) * Decimal(billable_seconds)) / Decimal(3600)
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def weighted_amount_piasters(hourly_rate_piasters: int, weighted_billable_seconds_x100: int) -> int:
    amount = (
        Decimal(hourly_rate_piasters)
        * Decimal(weighted_billable_seconds_x100)
        / (Decimal(3600) * Decimal(100))
    )
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
