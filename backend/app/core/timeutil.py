"""Time rules: store UTC, think in the user's timezone.

Times without a timezone coming from the user are assumed to be in TRINETRA_TIMEZONE.
Times read back from SQLite come out naive and are UTC (because we stored UTC).
"""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import get_settings


def user_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().trinetra_timezone)


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=user_tz())
    return dt.astimezone(timezone.utc)


def from_db(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def local(dt: datetime) -> datetime:
    return from_db(dt).astimezone(user_tz())


def now_local() -> datetime:
    return datetime.now(user_tz())


def day_bounds_utc(day: datetime | None = None) -> tuple[datetime, datetime]:
    """Start and end of the user's local day, in UTC."""
    tz = user_tz()
    d = (day or now_local()).astimezone(tz).date()
    start = datetime.combine(d, time.min, tz)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)
