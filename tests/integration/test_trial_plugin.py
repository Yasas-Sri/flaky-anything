"""trial_plugin, exercised in real pytest subprocesses against a generated project."""

import json
import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from flaky_anything.config import ClockSpec, OrderSpec, TrialConfig
from flaky_anything.trial_plugin import PluginOutput, per_test_seed, read_plugin_output

TEST_FILE = """
import json, os, random
from datetime import date
import pytest

def _obs(name):
    rec = {"name": name, "rand": random.random(), "today": date.today().isoformat()}
    with open(os.environ["OBS"], "a") as f:
        f.write(json.dumps(rec) + "\\n")

def test_one(): _obs("one")
def test_two(): _obs("two")
def test_three(): _obs("three")
def test_fails(): assert 1 == 2

@pytest.fixture
def broken():
    raise RuntimeError("boom")

def test_setup_error(broken): pass
def test_skipped(): pytest.skip("nope")
"""

F = "test_a.py"
ONE, TWO, THREE = f"{F}::test_one", f"{F}::test_two", f"{F}::test_three"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / F).write_text(TEST_FILE)
    return tmp_path


def run(
    project: Path, cfg: TrialConfig, env_override: dict[str, str] | None = None
) -> tuple[subprocess.CompletedProcess[str], PluginOutput | None, list[dict[str, str]]]:
    trial, result, obs = project / "trial.json", project / "result.json", project / "obs.jsonl"
    for f in (result, obs):
        f.unlink(missing_ok=True)
    trial.write_text(cfg.canonical_json())
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHASHSEED", "TZ")}
    env.pop("PYTEST_ADDOPTS", None)
    if cfg.hash_seed is not None:
        env["PYTHONHASHSEED"] = str(cfg.hash_seed)
    if cfg.tz is not None:
        env["TZ"] = cfg.tz
    env.update(
        FLAKY_ANYTHING_TRIAL=str(trial),
        FLAKY_ANYTHING_RESULT=str(result),
        OBS=str(obs),
        PYTHONDONTWRITEBYTECODE="1",
    )
    env.update(env_override or {})
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "flaky_anything.trial_plugin"]
    cmd += ["-p", "no:randomly", "-p", "no:cacheprovider", *cfg.nodeids]
    proc = subprocess.run(cmd, cwd=project, env=env, capture_output=True, text=True, timeout=60)
    out = read_plugin_output(result) if result.exists() else None
    records = [json.loads(line) for line in obs.read_text().splitlines()] if obs.exists() else []
    return proc, out, records


def names(records: list[dict[str, str]]) -> list[str]:
    return [r["name"] for r in records]


def test_explicit_order_overrides_project_reordering(project: Path) -> None:
    # pytest already runs node ids in arg order; explicit mode matters when the project
    # (conftest, ordering plugins) reorders items. The trial plugin must have the last word.
    (project / "conftest.py").write_text(
        "def pytest_collection_modifyitems(items):\n    items.reverse()\n"
    )
    nodeids = [THREE, ONE, TWO]
    collection = run(project, TrialConfig(nodeids=nodeids))[2]
    explicit = run(project, TrialConfig(nodeids=nodeids, order=OrderSpec(mode="explicit")))[2]
    assert names(collection) == ["two", "one", "three"]
    assert names(explicit) == ["three", "one", "two"]


def test_shuffle_is_deterministic_per_seed(project: Path) -> None:
    def order(seed: int) -> list[str]:
        cfg = TrialConfig(nodeids=[ONE, TWO, THREE], order=OrderSpec(mode="shuffle", seed=seed))
        return names(run(project, cfg)[2])

    assert order(1) == order(1)
    assert len({tuple(order(s)) for s in range(4)}) > 1


def test_random_is_seeded_per_test_independent_of_other_tests(project: Path) -> None:
    expected = random.Random(per_test_seed(5, ONE)).random()
    alone = run(project, TrialConfig(nodeids=[ONE], random_seed=5))[2]
    with_others = run(project, TrialConfig(nodeids=[TWO, ONE, THREE], random_seed=5))[2]
    assert [r["rand"] for r in alone if r["name"] == "one"] == [expected]
    assert [r["rand"] for r in with_others if r["name"] == "one"] == [expected]


def test_clock_travel_respects_tz(project: Path) -> None:
    # 03:00 UTC on Jan 1 is still Dec 31 in New York: proves TZ isn't overridden (D11).
    instant = datetime(2027, 1, 1, 3, tzinfo=timezone.utc)
    cfg = TrialConfig(nodeids=[ONE], clock=ClockSpec(instant=instant), tz="America/New_York")
    assert [r["today"] for r in run(project, cfg)[2]] == ["2026-12-31"]


def test_results_record_outcome_phase_and_longrepr(project: Path) -> None:
    cfg = TrialConfig(nodeids=[F], hash_seed=0)
    proc, out, _ = run(project, cfg)
    assert proc.returncode == 1
    assert out is not None
    assert out.config_id == cfg.config_id
    assert out.exitstatus == 1
    by_id = {r.nodeid: r for r in out.results}
    assert (by_id[ONE].outcome, by_id[ONE].phase) == ("passed", "call")
    assert (by_id[f"{F}::test_fails"].outcome, by_id[f"{F}::test_fails"].phase) == (
        "failed",
        "call",
    )
    assert "assert 1 == 2" in (by_id[f"{F}::test_fails"].longrepr or "")
    setup_err = by_id[f"{F}::test_setup_error"]
    assert (setup_err.outcome, setup_err.phase) == ("failed", "setup")
    assert "boom" in (setup_err.longrepr or "")
    assert by_id[f"{F}::test_skipped"].outcome == "skipped"


def test_collection_errors_are_recorded(project: Path) -> None:
    (project / "test_bad.py").write_text("def test_x(:\n")
    _, out, _ = run(project, TrialConfig(nodeids=["test_bad.py"]))
    assert out is not None
    assert out.results == []
    assert any("test_bad.py" in e for e in out.collection_errors)


def test_hash_seed_mismatch_is_refused(project: Path) -> None:
    proc, out, _ = run(project, TrialConfig(nodeids=[ONE], hash_seed=7), {"PYTHONHASHSEED": "8"})
    assert proc.returncode == 4  # pytest usage error
    assert "PYTHONHASHSEED" in proc.stderr
    assert out is None


def test_tz_mismatch_is_refused(project: Path) -> None:
    proc, _, _ = run(project, TrialConfig(nodeids=[ONE], tz="Asia/Kolkata"), {"TZ": "UTC"})
    assert proc.returncode == 4
    assert "TZ" in proc.stderr


def test_missing_trial_env_is_refused(project: Path) -> None:
    proc, _, _ = run(project, TrialConfig(nodeids=[ONE]), {"FLAKY_ANYTHING_TRIAL": ""})
    assert proc.returncode == 4
    assert "FLAKY_ANYTHING_TRIAL" in proc.stderr
