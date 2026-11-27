"""run_trial against a generated project, in real subprocesses."""

from pathlib import Path

import pytest

from flaky_anything.config import TrialConfig
from flaky_anything.errors import FlakyAnythingError
from flaky_anything.runner import (
    STATE_DIR,
    TrialResult,
    plugin_missing,
    run_trial,
    run_trials,
)

TEST_FILE = """
import os, time

def test_ok(): pass
def test_fails(): assert 1 == 2
def test_env():
    assert os.environ.get("PYTHONHASHSEED") == os.environ.get("EXPECT_HASH")
    assert os.environ.get("TZ") == os.environ.get("EXPECT_TZ")
    assert "PYTEST_ADDOPTS" not in os.environ
def test_hang(): time.sleep(600)  # target-project hang; our side only waits timeout_s
def test_after_hang(): pass
def test_crash(): os._exit(3)

def test_barrier():
    # Passes only if BARRIER_N trials are running at the same time (deterministic concurrency
    # check: no timing assumptions on our side; the target polls, we just wait).
    d = os.environ["BARRIER_DIR"]
    open(os.path.join(d, str(os.getpid())), "w").close()
    deadline = time.monotonic() + 60
    while len(os.listdir(d)) < int(os.environ["BARRIER_N"]):
        assert time.monotonic() < deadline, "trials did not run concurrently"
        time.sleep(0.01)
"""
F = "test_p.py"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / F).write_text(TEST_FILE)
    return tmp_path


def outcomes(res: TrialResult) -> dict[str, str]:
    return {r.nodeid.split("::")[1]: r.outcome for r in res.results}


def test_normal_trial_records_outcomes_and_config(project: Path) -> None:
    cfg = TrialConfig(nodeids=[f"{F}::test_ok", f"{F}::test_fails"])
    res = run_trial(cfg, project)
    assert res.status == "ok"
    assert outcomes(res) == {"test_ok": "passed", "test_fails": "failed"}
    assert res.config == cfg
    saved = project / STATE_DIR / "trials" / f"{cfg.config_id}.json"
    assert TrialConfig.model_validate_json(saved.read_text()) == cfg


def test_env_is_set_from_config_and_scrubbed(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTEST_ADDOPTS", "-p randomly")
    monkeypatch.setenv("EXPECT_HASH", "7")
    monkeypatch.setenv("EXPECT_TZ", "Asia/Colombo")
    cfg = TrialConfig(nodeids=[f"{F}::test_env"], hash_seed=7, tz="Asia/Colombo")
    assert outcomes(run_trial(cfg, project)) == {"test_env": "passed"}


def test_hash_seed_none_unsets_inherited_pythonhashseed(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHONHASHSEED", "3")
    monkeypatch.delenv("EXPECT_HASH", raising=False)
    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.delenv("EXPECT_TZ", raising=False)
    cfg = TrialConfig(nodeids=[f"{F}::test_env"])
    assert outcomes(run_trial(cfg, project)) == {"test_env": "passed"}


def test_hanging_test_is_killed_and_only_it_is_timeout(project: Path) -> None:
    nodeids = [f"{F}::test_ok", f"{F}::test_hang", f"{F}::test_after_hang"]
    res = run_trial(TrialConfig(nodeids=nodeids, timeout_s=5), project)
    assert res.status == "timeout"
    assert outcomes(res) == {"test_ok": "passed", "test_hang": "timeout"}  # after_hang never ran
    assert res.duration < 60


def test_crash_is_error_with_output_tail(project: Path) -> None:
    res = run_trial(TrialConfig(nodeids=[f"{F}::test_ok", f"{F}::test_crash"]), project)
    assert res.status == "error"
    assert outcomes(res) == {"test_ok": "passed", "test_crash": "error"}


def test_unknown_nodeid_is_error(project: Path) -> None:
    res = run_trial(TrialConfig(nodeids=[f"{F}::test_nope"]), project)
    assert res.status == "error"
    assert "test_nope" in res.stderr_tail


def test_missing_plugin_raises_actionable_error(tmp_path: Path) -> None:
    # Stand-in interpreter that fails the way pytest does when the plugin isn't installed.
    fake = tmp_path / "python"
    fake.write_text(
        '#!/bin/sh\necho "ImportError: Error importing plugin '
        '\\"flaky_anything.trial_plugin\\": No module named \'flaky_anything\'" >&2\nexit 4\n'
    )
    fake.chmod(0o755)
    with pytest.raises(FlakyAnythingError) as exc:
        run_trial(TrialConfig(nodeids=["t.py::x"]), tmp_path, python=str(fake))
    assert "--python" in (exc.value.hint or "")


def test_plugin_missing_detection() -> None:
    assert plugin_missing("No module named 'flaky_anything'")
    assert not plugin_missing("No module named 'requests'")


def test_run_trials_keeps_input_order(project: Path) -> None:
    configs = [TrialConfig(nodeids=[f"{F}::{t}"]) for t in ("test_fails", "test_ok", "test_fails")]
    results = run_trials(configs, project)
    assert [r.config for r in results] == configs
    assert [r.results[0].outcome for r in results] == ["failed", "passed", "failed"]


def test_run_trials_jobs_run_concurrently(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    barrier = tmp_path / "barrier"
    barrier.mkdir()
    monkeypatch.setenv("BARRIER_DIR", str(barrier))
    monkeypatch.setenv("BARRIER_N", "4")
    configs = [TrialConfig(nodeids=[f"{F}::test_barrier"], random_seed=i) for i in range(4)]
    results = run_trials(configs, project, jobs=4)
    assert [r.results[0].outcome for r in results] == ["passed"] * 4


def test_parallel_trials_of_the_same_config_do_not_collide(project: Path) -> None:
    cfg = TrialConfig(nodeids=[f"{F}::test_ok"])
    results = run_trials([cfg] * 8, project, jobs=8)
    assert [r.status for r in results] == ["ok"] * 8
    assert len({r.trial_id for r in results}) == 8


def test_run_trials_rejects_zero_jobs(project: Path) -> None:
    with pytest.raises(FlakyAnythingError):
        run_trials([], project, jobs=0)
