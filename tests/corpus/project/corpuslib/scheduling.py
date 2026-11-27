"""Scheduling helpers that touch the clock and the local time zone."""

import time
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime


def hours_in_today() -> float:
    """Length of the local calendar day (23 or 25 on DST days)."""
    today = date.today()
    start = datetime.combine(today, dtime.min).timestamp()
    end = datetime.combine(today + timedelta(days=1), dtime.min).timestamp()
    return (end - start) / 3600


def build_daily_report() -> dict[str, object]:
    time.sleep(0.6)  # simulates slow report generation (real wall time on purpose)
    return {"date": date.today(), "rows": 3}


def utc_hour() -> int:
    """Current UTC hour. BUG: naive local time, assumes the server runs in UTC."""
    return datetime.now().hour


def is_business_hours(at: datetime) -> bool:
    return 9 <= at.astimezone(timezone.utc).hour < 17
