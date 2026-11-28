import random
from datetime import datetime, timezone

from flaky_anything.config import TrialConfig
from flaky_anything.hints import Hints
from flaky_anything.hunt import Tally, phase_b_round, phase_b_targets, sample_config, tally
from flaky_anything.knobs.registry import baseline_config, select
from flaky_anything.runner import TrialResult
from flaky_anything.trial_plugin import NodeResult

BASE = baseline_config(["t.py::a", "t.py::b"])


def test_sampling_is_deterministic_per_seed_and_varies() -> None:
    knobs = select()

    def draw(seed: int) -> list[TrialConfig]:
        rng = random.Random(seed)  # one generator per hunt, shared by every draw
        return [sample_config(BASE, knobs, rng) for _ in range(3)]

    assert draw(0) == draw(0)
    assert draw(0) != draw(1)
    assert len({c.config_id for c in draw(0)}) == 3


def test_disabled_knobs_stay_at_baseline() -> None:
    cfg = sample_config(BASE, select("tz"), random.Random(0))
    assert cfg.model_copy(update={"tz": "UTC"}) == BASE
    assert cfg.nodeids == BASE.nodeids


def result(trial_id: str, **outcomes: str) -> TrialResult:
    return TrialResult(
        trial_id=trial_id,
        config=BASE,
        started_at=datetime(2027, 6, 16, tzinfo=timezone.utc),
        duration=1.0,
        status="ok",
        results=[
            NodeResult(nodeid=f"t.py::{n}", outcome=o, phase="call", duration=0.1)
            for n, o in outcomes.items()
        ],
    )


def test_tally_counts_passes_and_failing_outcomes_per_nodeid() -> None:
    t = tally([result("t1", a="passed", b="failed"), result("t2", a="timeout", b="skipped")])
    assert t == {
        "t.py::a": Tally(passed=["t1"], failed=["t2"]),
        "t.py::b": Tally(passed=[], failed=["t1"]),
    }
    assert t["t.py::a"].confirmed_flaky
    assert not t["t.py::b"].confirmed_flaky  # always failing so far: broken, not flaky


def test_tally_accumulates_into_existing() -> None:
    t = tally([result("t1", a="passed")])
    tally([result("t2", a="error")], into=t)
    assert t["t.py::a"] == Tally(passed=["t1"], failed=["t2"])


def test_phase_b_targets_failed_first_then_by_hint_score_skipping_confirmed() -> None:
    ids = [f"t.py::{n}" for n in "abcde"]
    seen = {
        "t.py::a": Tally(passed=["x"], failed=["y"]),  # confirmed: no more work
        "t.py::b": Tally(failed=["y"]),
        "t.py::c": Tally(passed=["x"]),
    }
    hints = {
        "t.py::c": Hints(direct=frozenset({"clock"})),
        "t.py::d": Hints(indirect=frozenset({"random"})),
        "t.py::a": Hints(direct=frozenset({"clock"})),
    }
    assert phase_b_targets(ids, seen, hints) == ["t.py::b", "t.py::c", "t.py::d"]  # e: no signal


def test_phase_b_round_puts_every_target_in_one_group_deterministically() -> None:
    targets = [f"t.py::t{i}" for i in range(10)]
    others = [f"t.py::o{i}" for i in range(5)]
    rnd = lambda: phase_b_round(targets, others, select(), random.Random(3))  # noqa: E731
    groups = rnd()
    assert groups == rnd()
    members = [m for g, _ in groups for m in g]
    assert sorted(members) == sorted(targets)
    assert [len(g) for g, _ in groups] == [4, 4, 2]
    for g, cfg in groups:
        fillers = set(cfg.nodeids) - set(g)
        assert set(g) <= set(cfg.nodeids)
        assert len(fillers) == 2
        assert fillers <= set(others)
    assert len({cfg.config_id for _, cfg in groups}) == 3
