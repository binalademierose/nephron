"""
clock.py - the one place that says what time it is.

Every time Nephron stores is UTC. It is written as a plain (naive) datetime with no fractions of a second,
because that is exactly what a MySQL DATETIME column holds. Tests replace now_utc() to travel in time.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def to_local_date(moment_utc, timezone_name):
    """
    The calendar date, where the person lives, of a stored UTC time.
    Without this an assessment done at 7 in the morning in Manila would be shown on the day before.
    """
    return moment_utc.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(timezone_name)).date()


def to_local_datetime(moment_utc, timezone_name):
    """The same conversion, keeping the time of day - for anything shown as 'this happened at HH:MM', not just
    which calendar day it fell on (a notification's timestamp, say)."""
    return moment_utc.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(timezone_name))


def from_local_datetime(naive_local, timezone_name):
    """The reverse of to_local_datetime(): a naive datetime as a person TYPED it (a follow-up appointment's date
    and time, say - always entered in the app's own local timezone), turned into the naive UTC datetime this app
    stores everything as."""
    return naive_local.replace(tzinfo=ZoneInfo(timezone_name)).astimezone(timezone.utc).replace(tzinfo=None)


def local_today(timezone_name):
    return to_local_date(now_utc(), timezone_name)


def timezone_exists(timezone_name):
    try:
        ZoneInfo(timezone_name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False
