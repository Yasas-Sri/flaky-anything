from datetime import date, datetime, timezone

from corpuslib import billing, scheduling


def test_next_month_invoice():
    """T1: production bug in billing.next_month on month ends and in December."""
    today = date.today()
    assert billing.next_month(today).month == today.month % 12 + 1


def test_report_is_for_today():
    """T2: 'today' read before and after slow work; differs if midnight passes."""
    start = date.today()
    assert scheduling.build_daily_report()["date"] == start


def test_day_has_24_hours():
    """T3: assumes every local day has 24 hours (false on DST days)."""
    assert scheduling.hours_in_today() == 24


def test_business_hours_utc_assumption():
    """T4: code treats naive local time as UTC; fails when TZ is not UTC."""
    assert scheduling.utc_hour() == datetime.now(timezone.utc).hour
