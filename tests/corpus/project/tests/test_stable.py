from datetime import date, datetime, timezone

from corpuslib import billing, cache, ids, scheduling, tags


def test_c1():
    """C1: cache round trip that cleans up after itself."""
    try:
        cache.put("c1", 42)
        assert cache.get("c1") == 42
    finally:
        cache.clear()


def test_c2():
    """C2: next_month on a safe, explicit mid-month date."""
    assert billing.next_month(date(2027, 3, 15)) == date(2027, 4, 15)


def test_c3():
    """C3: uses 'today' correctly, by injection."""
    assert billing.days_until_due(date(2027, 1, 20), today=date(2027, 1, 10)) == 10


def test_c4():
    """C4: business hours on an aware datetime; independent of TZ and clock."""
    assert scheduling.is_business_hours(datetime(2027, 6, 1, 10, tzinfo=timezone.utc))


def test_c5():
    """C5: renders a set deterministically by sorting."""
    assert tags.render_sorted(tags.tags_for("release")) == "alpha, beta"


def test_c6():
    """C6: random sampling, but only asserts a seed-independent property."""
    picked = ids.sample_distinct(["ann", "bob", "cy", "dee", "eve"], 2)
    assert len(set(picked)) == 2
