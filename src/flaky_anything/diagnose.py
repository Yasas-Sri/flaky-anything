"""Replay + knob ablation + polluter bisection -> Diagnosis (ARCHITECTURE.md §Diagnosis)."""

import sys
from pathlib import Path

from pydantic import BaseModel

from flaky_anything.config import TrialConfig
from flaky_anything.errors import FlakyAnythingError
from flaky_anything.hunt import FAILING, Budget, run_and_store
from flaky_anything.store import Store

REPLAYS = 10
DETERMINISTIC = 0.9  # replay fail rate at/above which the knobs explain the failure


class Replay(BaseModel):
    """`nodeid` under `config_id`, rerun `runs` times; trial ids of the reruns it failed in."""

    config_id: str
    nodeid: str
    trial_ids: list[str]
    failed_trial_ids: list[str]

    @property
    def rate(self) -> float:
        return len(self.failed_trial_ids) / len(self.trial_ids)

    @property
    def deterministic(self) -> bool:
        return self.rate >= DETERMINISTIC


def replay(
    config: TrialConfig,
    nodeid: str,
    project_root: Path,
    store: Store,
    runs: int = REPLAYS,
    jobs: int = 1,
    python: str = sys.executable,
) -> Replay:
    """Rerun `config` `runs` times (each trial stored) and count the failures of `nodeid`.
    A test that did not report is not a failure: we only claim what we saw (hard rule 4)."""
    if runs < 1:
        raise FlakyAnythingError(f"--replays must be >= 1, got {runs}")
    if nodeid not in config.nodeids:
        raise ValueError(f"{nodeid} is not part of config {config.config_id}")
    results = run_and_store([config] * runs, project_root, store, Budget(), jobs, python)
    failed = [
        res.trial_id
        for res in results
        if any(r.nodeid == nodeid and r.outcome in FAILING for r in res.results)
    ]
    return Replay(
        config_id=config.config_id,
        nodeid=nodeid,
        trial_ids=[res.trial_id for res in results],
        failed_trial_ids=failed,
    )
