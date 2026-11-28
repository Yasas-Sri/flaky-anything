"""hunt() end to end with a fake trial runner and fixed selection (no subprocesses)."""

from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

import pytest

from flaky_anything import hunt
from flaky_anything.config import TrialConfig
from flaky_anything.hints import Hints
from flaky_anything.hunt import Budget, HuntReport, Tally, phase_b_targets, round_cap
from flaky_anything.runner import TrialResult
from flaky_anything.selection import History
from flaky_anything.stats import wilson_interval
from flaky_anything.trial_plugin import NodeResult

FLAKY, BROKEN, STABLE, CI_ONLY = (f"t.py::{n}" for n in ("flaky", "broken", "stable", "ci_only"))
LONGREPR = (
    "    def test():\n>       assert x\nE       AssertionError: boom\n\nt.py:3: AssertionError"
)


def outcome(nodeid: str, cfg: TrialConfig) -> str:
    if nodeid == BROKEN:
        return "failed"
    if nodeid == FLAKY and (cfg.random_seed or 0) % 2 == 0:
        return "failed"
    return "passed"


@pytest.fixture
def ran(monkeypatch: pytest.MonkeyPatch) -> list[TrialConfig]:
    ran: list[TrialConfig] = []

    def run_trials(configs: Sequence[TrialConfig], *_: object, **__: object) -> list[TrialResult]:
        out = []
        for c in configs:
            ran.append(c)
            results = []
            for n in c.nodeids:
                o = outcome(n, c)
                longrepr = LONGREPR if o == "failed" else None
                results.append(
                    NodeResult(nodeid=n, outcome=o, phase="call", duration=0.0, longrepr=longrepr)
                )
            out.append(
                TrialResult(
                    trial_id=f"trial{len(ran)}",
                    config=c,
                    started_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
                    duration=0.1,
                    status="ok",
                    results=results,
                )
            )
        return out

    monkeypatch.setattr(hunt, "run_trials", run_trials)
    monkeypatch.setattr(hunt, "collect", lambda *_: [FLAKY, BROKEN, STABLE, CI_ONLY])
    return ran


def report(tmp_path: Path, **kw: object) -> HuntReport:
    return hunt.hunt(tmp_path, seed=7, **kw)  # type: ignore[arg-type]


def test_report_lists_flaky_and_broken_with_stats_and_signatures(
    ran: list[TrialConfig], tmp_path: Path
) -> None:
    r = report(tmp_path)
    assert [f.nodeid for f in r.flaky] == [FLAKY]
    assert [f.nodeid for f in r.broken] == [BROKEN]
    assert r.tests_selected == 4
    assert r.trials == len(ran)
    assert not r.budget_spent
    f = r.flaky[0]
    assert f.verdict == "flaky"
    assert f.failure_rate == f.failed / (f.passed + f.failed)
    assert (f.rate_low, f.rate_high) == wilson_interval(f.failed, f.passed + f.failed)
    assert len(f.signatures) == 1
    assert f.signatures[0].exc_type == "AssertionError"
    assert f.signatures[0].count == f.failed
    failing = {c.config_id for c in ran if FLAKY in c.nodeids and outcome(FLAKY, c) == "failed"}
    assert set(f.failing_config_ids) == failing
    assert len(f.failing_config_ids) == len(failing)  # deduplicated
    assert r.broken[0].passed == 0


def test_same_seed_same_report(ran: list[TrialConfig], tmp_path: Path) -> None:
    first = report(tmp_path / "a")
    configs = list(ran)
    ran.clear()
    assert report(tmp_path / "b") == first
    assert ran == configs


def test_budget_hit_is_reported(ran: list[TrialConfig], tmp_path: Path) -> None:
    r = report(tmp_path, budget=Budget(max_trials=3))
    assert r.trials == len(ran) == 3
    assert r.budget_spent


def test_ci_history_targets_unhinted_tests_first_and_marks_them_suspicious() -> None:
    ids = [FLAKY, BROKEN, STABLE, CI_ONLY]
    seen = {BROKEN: Tally(failed=["t1"]), STABLE: Tally(passed=["t1"])}
    history = {CI_ONLY: History(passed=3, failed=1)}
    assert phase_b_targets(ids, seen, {}) == [BROKEN]  # CI_ONLY: no hint, never failed here
    assert phase_b_targets(ids, seen, {}, history) == [CI_ONLY, BROKEN]  # CI-mixed first
    assert round_cap(Tally(), Hints(), history[CI_ONLY]) == hunt.ROUNDS_MAX
    assert round_cap(Tally(), Hints(), History(passed=5, failed=0)) == hunt.ROUNDS_PER_HINT
