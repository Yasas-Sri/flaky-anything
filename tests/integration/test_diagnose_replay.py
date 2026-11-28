"""replay() against a generated project, in real subprocesses."""

from pathlib import Path

import pytest

from flaky_anything.diagnose import replay
from flaky_anything.errors import FlakyAnythingError
from flaky_anything.knobs.registry import baseline_config
from flaky_anything.store import Store

# test_tz fails whenever the local zone is not UTC: our tz knob controls it.
# test_alternating fails on every other run (a counter file): no knob controls it, and it is
# deterministic, so this test never flakes.
TEST_FILE = """
from datetime import datetime, timedelta
from pathlib import Path

def test_tz():
    assert datetime(2027, 6, 16).astimezone().utcoffset() == timedelta(0)

def test_alternating():
    counter = Path(__file__).with_name("counter")
    n = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(n + 1))
    assert n % 2 == 0
"""
TZ, ALT = "test_p.py::test_tz", "test_p.py::test_alternating"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "test_p.py").write_text(TEST_FILE)
    return tmp_path


def test_knob_controlled_failure_replays_deterministically(project: Path) -> None:
    cfg = baseline_config([TZ]).model_copy(update={"tz": "Asia/Kolkata"})
    with Store(project) as store:
        rep = replay(cfg, TZ, project, store, runs=4, jobs=2)
        assert (len(rep.trial_ids), len(rep.failed_trial_ids)) == (4, 4)
        assert rep.deterministic
        assert store.failing_config_ids(TZ) == [cfg.config_id]  # every replay is stored
        passing = replay(baseline_config([TZ]), TZ, project, store, runs=2)
    assert passing.rate == 0
    assert not passing.deterministic


def test_failure_outside_our_knobs_is_not_deterministic(project: Path) -> None:
    with Store(project) as store:
        rep = replay(baseline_config([ALT]), ALT, project, store, runs=10)
    assert rep.rate == 0.5  # runs 2, 4, ... fail
    assert not rep.deterministic


def test_bad_input_is_refused(project: Path) -> None:
    with Store(project) as store:
        with pytest.raises(FlakyAnythingError, match="--replays"):
            replay(baseline_config([TZ]), TZ, project, store, runs=0)
        with pytest.raises(ValueError, match="not part of"):
            replay(baseline_config([TZ]), ALT, project, store)
