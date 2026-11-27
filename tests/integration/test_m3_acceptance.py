"""M3 acceptance: every corpus case fails when its trigger is applied through the knob API.

Cases are added here as their knobs land; each runs once under baseline (must pass) and once
under its trigger (must fail), as real trials of a copy of the corpus.
"""

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from flaky_anything.config import ClockSpec, TrialConfig
from flaky_anything.knobs.order import explicit
from flaky_anything.runner import run_trial

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

CORPUS = Path(__file__).parents[1] / "corpus"
GT: dict[str, Any] = tomllib.loads((CORPUS / "ground_truth.toml").read_text())["cases"]
BASELINE = dict(
    hash_seed=0,
    random_seed=0,
    tz="UTC",
    clock=ClockSpec(instant=datetime(2027, 6, 16, 10, tzinfo=timezone.utc)),
)
ORDER_CASES = [k for k, v in GT.items() if v["necessary_knobs"] == ["order"]]


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
    base = TrialConfig(nodeids=[victim], **BASELINE)
    # Baseline: the helper runs first for a brittle test, after the victim for a polluted one.
    passing = [helper, victim] if "state_setter" in GT[case] else [victim, helper]
    assert outcome(explicit(base, passing), project, victim) == "passed"
    assert outcome(explicit(base, GT[case]["trigger"]["order"]), project, victim) == "failed"
