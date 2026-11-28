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
from typing import Any, Literal

from pydantic import BaseModel

from flaky_anything.config import TrialConfig
from flaky_anything.errors import FlakyAnythingError
from flaky_anything.hints import Hints, hints_for
from flaky_anything.knobs.base import Knob
from flaky_anything.knobs.registry import DEFAULT, baseline_config, select
from flaky_anything.runner import TrialResult, run_trials
from flaky_anything.selection import History, collect, junit_history
from flaky_anything.signatures import signatures_for
from flaky_anything.stats import wilson_interval
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
    hit: bool = False  # some wanted trial was refused: the hunt stopped early
    _start: float = field(init=False)

    def __post_init__(self) -> None:
        self._start = self.clock()

    def allowance(self, wanted: int) -> int:
        """How many of `wanted` trials may start now (0 = budget spent)."""
        allowed = wanted
        if self.seconds is not None and self.clock() - self._start >= self.seconds:
            allowed = 0
        elif self.max_trials is not None:
            allowed = max(0, min(wanted, self.max_trials - self.used))
        self.hit |= allowed < wanted
        return allowed


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
    nodeids: Sequence[str],
    seen: Mapping[str, Tally],
    hints: Mapping[str, Hints],
    history: Mapping[str, History] | None = None,
) -> list[str]:
    """Unconfirmed tests worth targeting: mixed outcomes in CI first, then failed in Phase A,
    then by hint score. A test with no CI failure, no failure and no hint is not targeted."""
    empty, no_hints, no_ci, ci = Tally(), Hints(), History(0, 0), history or {}
    candidates = [
        n
        for n in nodeids
        if not seen.get(n, empty).confirmed_flaky
        and (
            seen.get(n, empty).failed or hints.get(n, no_hints).score > 0 or ci.get(n, no_ci).failed
        )
    ]
    return sorted(
        candidates,
        key=lambda n: (
            not ci.get(n, no_ci).mixed,
            not seen.get(n, empty).failed,
            -hints.get(n, no_hints).score,
        ),
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


def round_cap(tally: Tally, hints: Hints, ci: History | None = None) -> int:
    if tally.failed or (ci is not None and ci.failed):  # failed here or in CI: suspicious
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
    history: Mapping[str, History] | None = None,
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
            and took_part[t]
            < round_cap(seen.get(t, Tally()), hints.get(t, Hints()), (history or {}).get(t))
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


class SignatureCount(BaseModel):
    id: str
    exc_type: str
    count: int


class TestFinding(BaseModel):
    """One test that failed during the hunt. Rates are over the sampled configs it ran under
    (targeted sampling, not a natural CI rate)."""

    __test__ = False  # not a pytest test class

    nodeid: str
    verdict: Literal["flaky", "broken"]  # broken = failed in every trial it ran in
    passed: int
    failed: int
    failure_rate: float
    rate_low: float  # Wilson 95% (stats.wilson_interval)
    rate_high: float
    signatures: list[SignatureCount]
    failing_config_ids: list[str]


class HuntReport(BaseModel):
    seed: int
    knobs: list[str]
    tests_selected: int
    trials: int
    budget_spent: bool  # stopped by --budget/--max-trials: unconfirmed tests may be flaky
    flaky: list[TestFinding]
    broken: list[TestFinding]


def finding(nodeid: str, t: Tally, results: Mapping[str, TrialResult], store: Store) -> TestFinding:
    sigs: dict[str, SignatureCount] = {}
    for trial_id in t.failed:
        sig = store.signature_of(trial_id, nodeid)
        if sig is not None:
            sigs.setdefault(sig.id, SignatureCount(id=sig.id, exc_type=sig.exc_type, count=0))
            sigs[sig.id].count += 1
    n = len(t.passed) + len(t.failed)
    low, high = wilson_interval(len(t.failed), n)
    return TestFinding(
        nodeid=nodeid,
        verdict="flaky" if t.confirmed_flaky else "broken",
        passed=len(t.passed),
        failed=len(t.failed),
        failure_rate=len(t.failed) / n,
        rate_low=low,
        rate_high=high,
        signatures=sorted(sigs.values(), key=lambda s: -s.count),
        failing_config_ids=list(dict.fromkeys(results[i].config.config_id for i in t.failed)),
    )


def hunt(
    project_root: Path,
    paths: Sequence[str] = (),
    junit: Sequence[Path] = (),
    knobs: str = DEFAULT,
    seed: int = 0,
    budget: Budget | None = None,
    jobs: int = 1,
    python: str = sys.executable,
) -> HuntReport:
    """Select → hints → Phase A → Phase B → report. Everything random comes from `seed`."""
    budget = budget or Budget()
    enabled = select(knobs)
    rng = random.Random(seed)
    nodeids = collect(project_root, paths, python)
    history = junit_history(junit, nodeids) if junit else {}
    hints = hints_for(project_root, nodeids)
    with Store(project_root) as store:
        results = phase_a(
            nodeids, enabled, rng, project_root, store, budget=budget, jobs=jobs, python=python
        )
        seen = tally(results)
        targets = phase_b_targets(nodeids, seen, hints, history)
        results += phase_b(
            nodeids,
            targets,
            seen,
            hints,
            enabled,
            rng,
            project_root,
            store,
            budget,
            history=history,
            jobs=jobs,
            python=python,
        )
        by_id = {r.trial_id: r for r in results}
        found = [finding(n, seen[n], by_id, store) for n in nodeids if n in seen and seen[n].failed]
    return HuntReport(
        seed=seed,
        knobs=[k.name for k in enabled],
        tests_selected=len(nodeids),
        trials=len(results),
        budget_spent=budget.hit,
        flaky=[f for f in found if f.verdict == "flaky"],
        broken=[f for f in found if f.verdict == "broken"],
    )
