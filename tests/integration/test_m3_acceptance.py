"""M3 acceptance: every corpus case fails when its trigger is applied through the knob API.

Cases are added here as their knobs land; each runs once under baseline (must pass) and once
under its trigger (must fail), as real trials of a copy of the corpus.
"""

import random
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from flaky_anything.config import ClockSpec, TrialConfig
from flaky_anything.knobs.base import Knob
from flaky_anything.knobs.clock import ClockKnob, edges
from flaky_anything.knobs.order import explicit
from flaky_anything.knobs.registry import baseline_config
from flaky_anything.knobs.seeds import HashSeedKnob, RandomSeedKnob
from flaky_anything.knobs.tz import ZONES, TzKnob
from flaky_anything.runner import run_trial

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

CORPUS = Path(__file__).parents[1] / "corpus"
GT: dict[str, Any] = tomllib.loads((CORPUS / "ground_truth.toml").read_text())["cases"]
ORDER_CASES = [k for k, v in GT.items() if v["necessary_knobs"] == ["order"]]
SEED_KNOBS: dict[str, Knob[int]] = {k.name: k for k in (HashSeedKnob(), RandomSeedKnob())}
SEED_CASES = [k for k, v in GT.items() if v["necessary_knobs"] in ([n] for n in SEED_KNOBS)]
CLOCK_CASES = [k for k, v in GT.items() if v["necessary_knobs"] == ["clock"]]
TZ_CASES = [k for k, v in GT.items() if "tz" in v["necessary_knobs"]]  # T4 alone, T3 with clock


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("m3") / "project"
    shutil.copytree(CORPUS / "project", root)
    return root


def outcome(cfg: TrialConfig, project: Path, nodeid: str) -> str:
    res = run_trial(cfg, project)
    assert res.status == "ok", res.stderr_tail
    return {r.nodeid: r.outcome for r in res.results}[nodeid]


@pytest.mark.parametrize("case", ORDER_CASES)
def test_order_trigger_fails_via_knob(case: str, project: Path) -> None:
    victim = GT[case]["nodeid"]
    helper = GT[case].get("polluter") or GT[case]["state_setter"]
    base = baseline_config([victim])
    # Baseline: the helper runs first for a brittle test, after the victim for a polluted one.
    passing = [helper, victim] if "state_setter" in GT[case] else [victim, helper]
    assert outcome(explicit(base, passing), project, victim) == "passed"
    assert outcome(explicit(base, GT[case]["trigger"]["order"]), project, victim) == "failed"


@pytest.mark.parametrize("case", SEED_CASES)
def test_seed_trigger_fails_via_knob(case: str, project: Path) -> None:
    # No pinned trigger value (seed outcomes depend on the Python version, D9): the trigger is
    # "some value the knob samples". Deterministic: each outcome is fixed by its seed value.
    victim = GT[case]["nodeid"]
    knob = SEED_KNOBS[GT[case]["necessary_knobs"][0]]
    base = baseline_config([victim])
    assert outcome(base, project, victim) == "passed"
    for i in range(20):
        value = knob.sample(random.Random(i))
        if outcome(knob.apply(base, value), project, victim) == "failed":
            return
    pytest.fail(f"no sampled {knob.name} in 20 made {case} fail")


@pytest.mark.parametrize("case", CLOCK_CASES)
def test_clock_trigger_fails_via_knob(case: str, project: Path) -> None:
    victim, trigger = GT[case]["nodeid"], GT[case]["trigger"]["clock"]
    assert trigger in [t for group in edges("UTC").values() for t in group]  # the knob samples it
    knob = ClockKnob()
    base = baseline_config([victim])
    assert outcome(knob.apply(base, knob.baseline()), project, victim) == "passed"
    assert outcome(knob.apply(base, ClockSpec(instant=trigger)), project, victim) == "failed"


@pytest.mark.parametrize("case", TZ_CASES)
def test_tz_trigger_fails_via_knobs_and_needs_each_one(case: str, project: Path) -> None:
    gt = GT[case]
    victim, tz = gt["nodeid"], gt["trigger"]["tz"]
    assert tz in ZONES
    base = baseline_config([victim])
    tz_knob, clock_knob = TzKnob(), ClockKnob(ZONES)
    knobs: dict[str, Any] = {"tz": (tz_knob, tz)}
    if "clock" in gt["necessary_knobs"]:
        knobs["clock"] = (clock_knob, ClockSpec(instant=gt["trigger"]["clock"]))
    triggered = base
    for knob, value in knobs.values():
        triggered = knob.apply(triggered, value)
    assert outcome(base, project, victim) == "passed"
    assert outcome(triggered, project, victim) == "failed"
    for name, (knob, _) in knobs.items():  # resetting any one necessary knob makes it pass
        assert outcome(knob.apply(triggered, knob.baseline()), project, victim) == "passed", name
