"""Budget and adaptive Phase B allocation, with a fake trial runner (no subprocesses)."""

import random
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

import pytest

from flaky_anything import hunt
from flaky_anything.config import TrialConfig
from flaky_anything.errors import FlakyAnythingError
from flaky_anything.hints import Hints
from flaky_anything.hunt import ROUNDS_MAX, ROUNDS_PER_HINT, Budget, Tally, parse_duration
from flaky_anything.knobs.registry import select
from flaky_anything.runner import TrialResult
from flaky_anything.store import Store
from flaky_anything.trial_plugin import NodeResult

STABLE, BROKEN, FLAKY = "t.py::stable", "t.py::broken", "t.py::flaky"


def outcome(nodeid: str, cfg: TrialConfig) -> str:
    if nodeid == BROKEN:
        return "failed"
    if nodeid == FLAKY:
        return "failed" if (cfg.random_seed or 0) % 3 == 0 else "passed"
    return "passed"


@pytest.fixture
def fake_runs(monkeypatch: pytest.MonkeyPatch) -> list[TrialConfig]:
    ran: list[TrialConfig] = []

    def run_trials(configs: Sequence[TrialConfig], *_: object, **__: object) -> list[TrialResult]:
        ran.extend(configs)
        return [
            TrialResult(
                trial_id=f"t{len(ran)}-{i}",
                config=c,
                started_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
                duration=0.1,
                status="ok",
                results=[
                    NodeResult(nodeid=n, outcome=outcome(n, c), phase="call", duration=0.0)
                    for n in c.nodeids
                ],
            )
            for i, c in enumerate(configs)
        ]

    monkeypatch.setattr(hunt, "run_trials", run_trials)
    return ran


def phase_b(
    target: str, score: int, tmp_path: Path, budget: Budget | None = None
) -> dict[str, Tally]:
    seen: dict[str, Tally] = {}
    hints = {target: Hints(indirect=frozenset(f"k{i}" for i in range(score)))}
    with Store(tmp_path) as store:
        hunt.phase_b(
            [target], [target], seen, hints, select(), random.Random(0), tmp_path, store, budget
        )
    return seen


@pytest.mark.parametrize("score", [1, 2])
def test_quiet_target_stops_after_rounds_per_hint_point(
    score: int, fake_runs: list[TrialConfig], tmp_path: Path
) -> None:
    seen = phase_b(STABLE, score, tmp_path)
    assert len(fake_runs) == ROUNDS_PER_HINT * score
    assert seen[STABLE] == Tally(passed=[f"t{i}-0" for i in range(1, len(fake_runs) + 1)])


def test_suspicious_target_gets_the_max_and_stays_unconfirmed_if_it_never_passes(
    fake_runs: list[TrialConfig], tmp_path: Path
) -> None:
    seen = phase_b(BROKEN, 1, tmp_path)
    assert len(fake_runs) == ROUNDS_MAX
    assert not seen[BROKEN].confirmed_flaky


def test_flaky_target_stops_once_confirmed(fake_runs: list[TrialConfig], tmp_path: Path) -> None:
    seen = phase_b(FLAKY, 1, tmp_path)
    assert seen[FLAKY].confirmed_flaky
    assert len(fake_runs) == len(seen[FLAKY].passed) + len(seen[FLAKY].failed) < ROUNDS_PER_HINT


def test_max_trials_cuts_the_seeded_schedule_to_an_exact_prefix(
    fake_runs: list[TrialConfig], tmp_path: Path
) -> None:
    phase_b(BROKEN, 1, tmp_path)
    full = list(fake_runs)
    fake_runs.clear()
    budget = Budget(max_trials=7)
    phase_b(BROKEN, 1, tmp_path / "b", budget)
    assert fake_runs == full[:7]
    assert budget.used == 7
    assert budget.allowance(1) == 0


def test_wall_clock_budget_stops_between_chunks() -> None:
    now = [0.0]
    budget = Budget(seconds=600, clock=lambda: now[0])
    assert budget.allowance(4) == 4
    now[0] = 599.9
    assert budget.allowance(4) == 4
    now[0] = 600.0
    assert budget.allowance(4) == 0


@pytest.mark.parametrize(
    ("text", "seconds"), [("90", 90), ("90s", 90), ("10m", 600), ("1h", 3600), ("1h30m", 5400)]
)
def test_parse_duration(text: str, seconds: float) -> None:
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "ten", "10x", "m"])
def test_bad_duration_is_actionable(text: str) -> None:
    with pytest.raises(FlakyAnythingError) as e:
        parse_duration(text)
    assert e.value.hint is not None
