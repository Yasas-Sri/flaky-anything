"""Hunt: find flaky tests by running them under sampled knob configs (ARCHITECTURE.md §Hunt).

All randomness comes from one `random.Random(hunt_seed)`, so a seed replays the whole hunt.
"""

import random
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from flaky_anything.config import TrialConfig
from flaky_anything.knobs.base import Knob
from flaky_anything.knobs.registry import baseline_config
from flaky_anything.runner import TrialResult, run_trials
from flaky_anything.signatures import signatures_for
from flaky_anything.store import Store

PHASE_A_RUNS = 8
FAILING = ("failed", "timeout", "error")  # a hang or crash of one test is a failing outcome


def sample_config(base: TrialConfig, knobs: Iterable[Knob[Any]], rng: random.Random) -> TrialConfig:
    """`base` (all knobs at baseline) with every enabled knob sampled, in registry order."""
    cfg = base
    for knob in knobs:
        cfg = knob.apply(cfg, knob.sample(rng))
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
