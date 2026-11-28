import random
from collections import Counter
from datetime import datetime, timedelta, timezone

from flaky_anything.config import ClockSpec, TrialConfig
from flaky_anything.knobs.base import Knob
from flaky_anything.knobs.clock import (
    BASELINE_INSTANT,
    ClockKnob,
    dst_transitions,
    edge_class,
    edges,
)

CFG = TrialConfig(nodeids=["t.py::a"])
ZONES = ("UTC", "America/New_York", "Asia/Kolkata")
knob = ClockKnob(ZONES)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def test_is_a_knob_with_ticking_mid_month_baseline() -> None:
    k: Knob[ClockSpec] = knob
    assert isinstance(k, Knob)
    assert knob.baseline() == ClockSpec(instant=BASELINE_INSTANT, tick=True)
    assert edge_class(BASELINE_INSTANT, "UTC") == "ordinary"
    assert BASELINE_INSTANT.weekday() == 2  # Wednesday


def test_utc_edges_by_class() -> None:
    e = edges("UTC")
    assert "dst" not in e
    assert len(e["month_start"]) == 24
    assert len(e["year_end"]) == 2
    assert len(e["month_end"]) == 22
    assert e["leap_day"] == (utc(2028, 2, 28, 23, 59, 59, 500_000),)
    assert utc(2027, 1, 31, 23, 59, 59, 500_000) in e["month_end"]  # corpus T1 trigger
    assert utc(2027, 2, 28, 23, 59, 59, 500_000) in e["month_end"]
    assert utc(2028, 2, 29, 23, 59, 59, 500_000) in e["month_end"]
    assert utc(2027, 6, 15, 23, 59, 59, 500_000) in e["midnight"]  # corpus T2 trigger
    assert utc(2027, 1, 1) in e["month_start"]


def test_edges_are_local_to_the_zone() -> None:
    assert utc(2027, 1, 31, 18, 29, 59, 500_000) in edges("Asia/Kolkata")["month_end"]
    assert utc(2027, 1, 31, 23, 59, 59, 500_000) not in edges("Asia/Kolkata")["month_end"]


def test_dst_transitions_are_exact() -> None:
    assert dst_transitions("America/New_York") == (
        utc(2027, 3, 14, 7),
        utc(2027, 11, 7, 6),
        utc(2028, 3, 12, 7),
        utc(2028, 11, 5, 6),
    )
    assert dst_transitions("UTC") == dst_transitions("Asia/Kolkata") == ()
    assert len(dst_transitions("Australia/Lord_Howe")) == 4  # 30-minute shifts count too
    spring = utc(2027, 3, 14, 7)
    assert {spring - timedelta(seconds=1), spring + timedelta(seconds=1)} <= set(
        edges("America/New_York")["dst"]
    )
    assert edge_class(utc(2027, 3, 14, 16), "America/New_York") == "ordinary"  # T3 noon


def in_tz(tz: str | None) -> TrialConfig:
    return CFG.model_copy(update={"tz": tz})


def test_sampling_is_deterministic_and_mixes_edges_with_random() -> None:
    ny = in_tz("America/New_York")
    assert knob.sample(random.Random(5), ny) == knob.sample(random.Random(5), ny)
    samples = [knob.sample(random.Random(s), ny) for s in range(400)]
    assert all(v.tick and v.instant is not None for v in samples)
    lo, hi = utc(2027, 1, 1), utc(2029, 1, 1) + timedelta(days=1)  # NY year ends are after UTC's
    assert all(lo <= v.instant < hi for v in samples if v.instant)
    classes = Counter(edge_class(v.instant, "America/New_York") for v in samples if v.instant)
    assert 0.5 < 1 - classes["ordinary"] / 400 < 0.7  # ~60% edges
    assert {"month_end", "year_end", "leap_day", "midnight", "dst", "month_start"} <= set(classes)
    # DST weighted 3 against 5 other classes: 3/8 of edges, ~0.225 of all samples
    assert 0.17 < classes["dst"] / 400 < 0.28


def test_edges_are_sampled_in_the_trials_zone() -> None:
    for tz in ("Asia/Kolkata", "Australia/Lord_Howe"):
        local = {t for group in edges(tz).values() for t in group}
        samples = [knob.sample(random.Random(s), in_tz(tz)).instant for s in range(100)]
        hits = [i for i in samples if i in local]
        assert 50 <= len(hits) <= 70  # every edge sample is an edge *of that zone*
    utc_edges = {t for group in edges("UTC").values() for t in group}
    samples = [knob.sample(random.Random(s), in_tz(None)).instant for s in range(50)]
    assert any(i in utc_edges for i in samples)  # tz=None (inherit) samples UTC edges


def test_apply_round_trips_and_describe() -> None:
    for value in (
        knob.baseline(),
        *(knob.sample(random.Random(s), in_tz(ZONES[s % 3])) for s in range(20)),
    ):
        cfg = knob.apply(CFG, value)
        assert TrialConfig.model_validate_json(cfg.canonical_json()).clock == value
    t1 = ClockSpec(instant=utc(2027, 1, 31, 23, 59, 59, 500_000))
    assert knob.describe(t1) == "clock: 2027-01-31 23:59:59.5 UTC (month end in UTC)"
    assert knob.describe(knob.baseline()) == "clock: 2027-06-16 10:00:00 UTC"
    assert knob.describe(ClockSpec()) == "clock: real"
    frozen = ClockSpec(instant=utc(2027, 3, 14, 6, 59, 59), tick=False)
    assert (
        knob.describe(frozen) == "clock: 2027-03-14 06:59:59 UTC (dst in America/New_York), frozen"
    )
    assert knob.plain_pytest_repro(t1) is None
