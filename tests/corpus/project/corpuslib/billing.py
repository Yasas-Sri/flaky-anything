"""Billing dates."""

from datetime import date


def next_month(d: date) -> date:
    """Same day next month. BUG: fails on the 29th-31st and in December."""
    return d.replace(month=d.month + 1)


def days_until_due(due: date, today: date | None = None) -> int:
    today = today or date.today()
    return (due - today).days
