"""Hunt: find flaky tests by running them under sampled knob configs (ARCHITECTURE.md §Hunt).

All randomness comes from one `random.Random(hunt_seed)`, so a seed replays the whole hunt.
"""

import random
import re
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from flaky_anything.config import TrialConfig
from flaky_anything.errors import FlakyAnythingError
from flaky_anything.hints import Hints
from flaky_anything.knobs.base import Knob
from flaky_anything.knobs.registry import baseline_config
from flaky_anything.runner import TrialResult, run_trials
from flaky_anything.signatures import signatures_for
from flaky_anything.store import Store

PHASE_A_RUNS = 8
FAILING = ("failed", "timeout", "error")  # a hang or crash of one test is a failing outcome


def sample_config(base: TrialConfig, knobs: Iterable[Knob[Any]], rng: random.Random) -> TrialConfig:
    """`base` (all knobs at baseline) with every enabled knob sampled, in registry order; each
    knob sees the config so far (the clock samples edges in the already-sampled tz)."""
    cfg = base
    for knob in knobs:
        cfg = knob.apply(cfg, knob.sample(rng, cfg))
    return cfg


class Tally(BaseModel):
    """Trial ids in which one node id passed / failed. Skips are not observations."""

    passed: list[str] = []
    failed: list[str] = []

    @property
    def confirmed_flaky(self) -> bool:
        return bool(self.passed and self.failed)


def tally(results: Iterable[TrialResult], into: dict[str, Tally] | None = None) -> dict[str, Tally]:
    out = into if into is not None else {}
    for res in results:
        for r in res.results:
            t = out.setdefault(r.nodeid, Tally())
            if r.outcome == "passed":
                t.passed.append(res.trial_id)
            elif r.outcome in FAILING:
                t.failed.append(res.trial_id)
    return out


def parse_duration(text: str) -> float:
    """`90`, `90s`, `10m`, `1h`, `1h30m` -> seconds."""
    parts = re.fullmatch(r"\s*(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s?)?\s*", text)
    if not text.strip() or parts is None:
        raise FlakyAnythingError(f"bad duration {text!r}", hint="use e.g. 90s, 10m or 1h30m")
    h, m, sec = (int(g or 0) for g in parts.groups())
    return float(h * 3600 + m * 60 + sec)


@dataclass
class Budget:
    """Stop after `max_trials` trials and/or `seconds` of wall clock, whichever comes first.
    Wall clock makes how far a hunt gets machine-dependent, but what runs is always a prefix of
    the seeded schedule; `max_trials` alone makes a hunt exactly reproducible (D29)."""

    max_trials: int | None = None
    seconds: float | None = None
    clock: Callable[[], float] = time.monotonic
    used: int = 0
    _start: float = field(init=False)

    def __post_init__(self) -> None:
        self._start = self.clock()

    def allowance(self, wanted: int) -> int:
        """How many of `wanted` trials may start now (0 = budget spent)."""
        if self.seconds is not None and self.clock() - self._start >= self.seconds:
            return 0
        if self.max_trials is None:
            return wanted
        return max(0, min(wanted, self.max_trials - self.used))


def run_and_store(
    configs: Sequence[TrialConfig],
    project_root: Path,
    store: Store,
    budget: Budget,
    jobs: int = 1,
    python: str = sys.executable,
) -> list[TrialResult]:
    """Run configs in order, `jobs` at a time, until done or the budget is spent."""
    results: list[TrialResult] = []
    for i in range(0, len(configs), jobs):
        chunk = configs[i : i + jobs][: budget.allowance(jobs)]
        if not chunk:
            break
        batch = run_trials(chunk, project_root, jobs=jobs, python=python)
        budget.used += len(batch)
        for res in batch:
            store.save_trial(res, signatures_for(res))
        results += batch
    return results


def phase_a(
    nodeids: Sequence[str],
    knobs: Sequence[Knob[Any]],
    rng: random.Random,
    project_root: Path,
    store: Store,
    runs: int = PHASE_A_RUNS,
    budget: Budget | None = None,
    jobs: int = 1,
    python: str = sys.executable,
) -> list[TrialResult]:
    """`runs` trials of the whole selection, each under a freshly sampled config. Mandatory:
    order-dependent failures only show up when many tests share one process."""
    base = baseline_config(nodeids)
    configs = [sample_config(base, knobs, rng) for _ in range(runs)]  # drawn before running
    return run_and_store(configs, project_root, store, budget or Budget(), jobs, python)


# Adaptive per-test budget, in Phase B rounds a target takes part in: a target that has failed
# (suspicious) gets up to ROUNDS_MAX to also pass; one that hasn't stops after ROUNDS_PER_HINT
# per hint point (D29).
ROUNDS_MAX = 40
ROUNDS_PER_HINT = 10
GROUP_TARGETS = 4
GROUP_FILLERS = 2  # random other tests per group, so targets meet varied neighbours/polluters


def phase_b_targets(
    nodeids: Sequence[str], seen: Mapping[str, Tally], hints: Mapping[str, Hints]
) -> list[str]:
    """Unconfirmed tests worth targeting: failed in Phase A first, then by hint score.
    A test with neither a failure nor a hint is not targeted."""
    empty, no_hints = Tally(), Hints()
    candidates = [
        n
        for n in nodeids
        if not seen.get(n, empty).confirmed_flaky
        and (seen.get(n, empty).failed or hints.get(n, no_hints).score > 0)
    ]
    return sorted(
        candidates,
        key=lambda n: (not seen.get(n, empty).failed, -hints.get(n, no_hints).score),
    )


def phase_b_round(
    targets: Sequence[str],
    others: Sequence[str],
    knobs: Sequence[Knob[Any]],
    rng: random.Random,
) -> list[tuple[list[str], TrialConfig]]:
    """One round: every target in exactly one group, each group under its own sampled config.
    Drawn whether or not earlier trials confirmed anything, so outcomes outside our knobs
    (e.g. os.urandom) can't change which configs the rest of a seeded hunt gets (D28)."""
    shuffled = list(targets)
    rng.shuffle(shuffled)
    groups = []
    for i in range(0, len(shuffled), GROUP_TARGETS):
        members = shuffled[i : i + GROUP_TARGETS]
        fillers = rng.sample(list(others), min(GROUP_FILLERS, len(others)))
        groups.append((members, sample_config(baseline_config(members + fillers), knobs, rng)))
    return groups


def round_cap(tally: Tally, hints: Hints) -> int:
    if tally.failed:
        return ROUNDS_MAX
    return min(ROUNDS_MAX, ROUNDS_PER_HINT * max(hints.score, 1))


def phase_b(
    nodeids: Sequence[str],
    targets: Sequence[str],
    seen: dict[str, Tally],
    hints: Mapping[str, Hints],
    knobs: Sequence[Knob[Any]],
    rng: random.Random,
    project_root: Path,
    store: Store,
    budget: Budget | None = None,
    max_rounds: int = ROUNDS_MAX,
    jobs: int = 1,
    python: str = sys.executable,
) -> list[TrialResult]:
    """Run targets in small sampled groups until each is confirmed flaky or has spent its
    adaptive round cap (`round_cap`), or the budget runs out. Updates `seen` in place."""
    budget = budget or Budget()
    target_set = set(targets)
    others = [n for n in nodeids if n not in target_set]
    took_part = dict.fromkeys(targets, 0)
    results: list[TrialResult] = []
    for _ in range(max_rounds):
        groups = phase_b_round(targets, others, knobs, rng)  # drawn in full every round (D28)
        open_ = {
            t
            for t in targets
            if not seen.get(t, Tally()).confirmed_flaky
            and took_part[t] < round_cap(seen.get(t, Tally()), hints.get(t, Hints()))
        }
        todo = [(members, cfg) for members, cfg in groups if open_ & set(members)]
        if not todo:
            break
        batch = run_and_store([c for _, c in todo], project_root, store, budget, jobs, python)
        for members, _ in todo[: len(batch)]:
            for m in members:
                took_part[m] += 1
        tally(batch, into=seen)
        results += batch
        if len(batch) < len(todo):  # budget spent mid-round
            break
    return results
