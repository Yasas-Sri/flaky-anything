"""Hunt: find flaky tests by running them under sampled knob configs (ARCHITECTURE.md §Hunt).

All randomness comes from one `random.Random(hunt_seed)`, so a seed replays the whole hunt.
"""

import random
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from flaky_anything.config import TrialConfig
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


def run_and_store(
    configs: Sequence[TrialConfig],
    project_root: Path,
    store: Store,
    jobs: int = 1,
    python: str = sys.executable,
) -> list[TrialResult]:
    results = run_trials(configs, project_root, jobs=jobs, python=python)
    for res in results:
        store.save_trial(res, signatures_for(res))
    return results


def phase_a(
    nodeids: Sequence[str],
    knobs: Sequence[Knob[Any]],
    rng: random.Random,
    project_root: Path,
    store: Store,
    runs: int = PHASE_A_RUNS,
    jobs: int = 1,
    python: str = sys.executable,
) -> list[TrialResult]:
    """`runs` trials of the whole selection, each under a freshly sampled config. Mandatory:
    order-dependent failures only show up when many tests share one process."""
    base = baseline_config(nodeids)
    configs = [sample_config(base, knobs, rng) for _ in range(runs)]  # drawn before running
    return run_and_store(configs, project_root, store, jobs=jobs, python=python)


PHASE_B_ROUNDS = 20  # per-test budget: rounds a target takes part in before it's called stable
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


def phase_b(
    nodeids: Sequence[str],
    targets: Sequence[str],
    seen: dict[str, Tally],
    knobs: Sequence[Knob[Any]],
    rng: random.Random,
    project_root: Path,
    store: Store,
    rounds: int = PHASE_B_ROUNDS,
    jobs: int = 1,
    python: str = sys.executable,
) -> list[TrialResult]:
    """Run targets in small sampled groups until each is confirmed flaky or `rounds` are spent.
    Updates `seen` in place."""
    target_set = set(targets)
    others = [n for n in nodeids if n not in target_set]
    results: list[TrialResult] = []
    for _ in range(rounds):
        groups = phase_b_round(targets, others, knobs, rng)
        done = {t for t in targets if seen.get(t, Tally()).confirmed_flaky}
        todo = [cfg for members, cfg in groups if not set(members) <= done]
        if not todo:
            break
        batch = run_and_store(todo, project_root, store, jobs=jobs, python=python)
        tally(batch, into=seen)
        results += batch
    return results
