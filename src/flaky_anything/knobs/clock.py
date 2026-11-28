"""Clock knob: fixed, ticking instants biased towards the calendar edges where time bugs live.

Edges are local to a zone (a "month end" in Asia/Kolkata is 18:29:59.5 UTC) and cover fixed
reference years, never "now", so a hunt replays exactly. The edge class of an instant is a pure
function of (instant, tz), so diagnosis recomputes it from the stored config (hard rule 3).
"""

import random
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from flaky_anything.config import ClockSpec, TrialConfig
from flaky_anything.knobs.base import replace

YEARS = (2027, 2028)  # 2028 is a leap year
BASELINE_INSTANT = datetime(2027, 6, 16, 10, tzinfo=timezone.utc)  # a Wednesday mid-month
EDGE_SHARE = 0.6
DST_WEIGHT = 3  # DST edges are scarce (some zones, 8 instants) and a classic real bug (D28)
DAY_END = time(23, 59, 59, 500_000)  # a ticking clock crosses midnight half a second later
ONE_S = timedelta(seconds=1)
_START = datetime(YEARS[0], 1, 1, tzinfo=timezone.utc)
_STOP = datetime(YEARS[-1] + 1, 1, 1, tzinfo=timezone.utc)


@lru_cache
def dst_transitions(tz: str) -> tuple[datetime, ...]:
    """First instant (whole second, UTC) of each UTC-offset change in YEARS."""
    zone = ZoneInfo(tz)

    def offset(ts: int) -> timedelta | None:
        return datetime.fromtimestamp(ts, zone).utcoffset()

    out = []
    # ponytail: hourly scan assumes <= 1 offset change per hour, true for every tzdb zone
    for lo in range(int(_START.timestamp()), int(_STOP.timestamp()), 3600):
        hi = lo + 3600
        if offset(lo) == offset(hi):
            continue
        while hi - lo > 1:  # bisect to the second
            mid = (lo + hi) // 2
            lo, hi = (mid, hi) if offset(mid) == offset(lo) else (lo, mid)
        out.append(datetime.fromtimestamp(hi, timezone.utc))
    return tuple(out)


def edge_class(instant: datetime, tz: str) -> str:
    """month_start | month_end | year_end | leap_day | midnight | dst | ordinary, in `tz`."""
    if any(abs(instant - t) <= ONE_S for t in dst_transitions(tz)):
        return "dst"
    local = instant.astimezone(ZoneInfo(tz))
    if local.time() == DAY_END:
        tomorrow = local.date() + timedelta(days=1)
        if tomorrow.year != local.year:
            return "year_end"
        if tomorrow.month != local.month:
            return "month_end"
        return "leap_day" if (tomorrow.month, tomorrow.day) == (2, 29) else "midnight"
    if local.time() == time(0):
        return "month_start" if local.day == 1 else "midnight"
    return "ordinary"


@lru_cache
def edges(tz: str) -> dict[str, tuple[datetime, ...]]:
    """Edge instants (UTC) in YEARS for `tz`, grouped by edge class."""
    zone = ZoneInfo(tz)
    found: dict[str, list[datetime]] = {}
    day = date(YEARS[0], 1, 1)
    while day.year <= YEARS[-1]:
        moments = [datetime.combine(day, DAY_END, zone)]
        if day.day == 1:
            moments.append(datetime.combine(day, time(0), zone))
        for m in moments:
            instant = m.astimezone(timezone.utc)
            found.setdefault(edge_class(instant, tz), []).append(instant)
        day += timedelta(days=1)
    for t in dst_transitions(tz):
        found.setdefault("dst", []).extend([t - ONE_S, t + ONE_S])
    found.pop("ordinary", None)  # a day end swallowed by a DST gap, if any
    return {cls: tuple(v) for cls, v in sorted(found.items())}


def _fmt(instant: datetime) -> str:
    s = instant.strftime("%Y-%m-%d %H:%M:%S")
    return s + f".{instant.microsecond:06d}".rstrip("0") if instant.microsecond else s


class ClockKnob:
    name = "clock"

    def __init__(self, zones: Sequence[str] = ("UTC",)) -> None:
        self.zones = tuple(zones)  # zones `describe` labels edges in (the tz knob's values)

    def baseline(self) -> ClockSpec:
        return ClockSpec(instant=BASELINE_INSTANT)

    def sample(self, rng: random.Random, config: TrialConfig) -> ClockSpec:
        # An edge only matters in the zone the trial runs in; tz=None inherits ours: use UTC.
        tz = config.tz or "UTC"
        if rng.random() < EDGE_SHARE:
            groups = edges(tz)
            classes = sorted(groups)
            weights = [DST_WEIGHT if c == "dst" else 1 for c in classes]
            instant = rng.choice(groups[rng.choices(classes, weights)[0]])
        else:
            span_us = (_STOP - _START) // timedelta(microseconds=1)
            instant = _START + timedelta(microseconds=rng.randrange(span_us))
        return ClockSpec(instant=instant)  # tick=True: frozen time can hang code that waits

    def apply(self, config: TrialConfig, value: ClockSpec) -> TrialConfig:
        return replace(config, clock=value)

    def describe(self, value: ClockSpec) -> str:
        if value.instant is None:
            return "clock: real"
        text = f"clock: {_fmt(value.instant)} UTC"
        for tz in self.zones:
            cls = edge_class(value.instant, tz)
            if cls != "ordinary":
                text += f" ({cls.replace('_', ' ')} in {tz})"
                break
        return text if value.tick else text + ", frozen"

    def plain_pytest_repro(self, value: ClockSpec) -> str | None:
        return None  # time travel needs the plugin
