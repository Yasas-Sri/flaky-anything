import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from flaky_anything.config import ClockSpec, OrderSpec, TrialConfig
from flaky_anything.errors import FlakyAnythingError
from flaky_anything.runner import STATE_DIR, TrialResult
from flaky_anything.store import Signature, Store
from flaky_anything.trial_plugin import NodeResult

SIG = Signature(
    id="sig1",
    exc_type="AssertionError",
    normalized_frames="t.py:test_b",
    sample_longrepr="E 1 == 2",
)


def make_result(trial_id: str = "t1") -> TrialResult:
    cfg = TrialConfig(
        nodeids=["t.py::test_a", "t.py::test_b"],
        order=OrderSpec(mode="shuffle", seed=2),
        hash_seed=4,
        clock=ClockSpec(instant=datetime(2027, 1, 31, 23, 59, 59, tzinfo=timezone.utc)),
        tz="Asia/Colombo",
    )
    return TrialResult(
        trial_id=trial_id,
        config=cfg,
        started_at=datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc),  # fixed, not now()
        duration=1.25,
        status="timeout",
        stderr_tail="killed",
        collection_errors=["t2.py: SyntaxError"],
        results=[
            NodeResult(
                nodeid="t.py::test_b",
                outcome="failed",
                phase="call",
                duration=0.5,
                longrepr="E 1 == 2",
            ),
            NodeResult(nodeid="t.py::test_a", outcome="timeout", phase="call", duration=0.7),
        ],
    )


def test_trial_round_trips_across_reopen(tmp_path: Path) -> None:
    with Store(tmp_path) as store:
        store.save_trial(make_result(), {"t.py::test_b": SIG})
    with Store(tmp_path) as store:
        assert store.load_trial("t1") == make_result()
        assert store.signature_of("t1", "t.py::test_b") == SIG
        assert store.signature_of("t1", "t.py::test_a") is None


def test_signatures_are_deduplicated(tmp_path: Path) -> None:
    with Store(tmp_path) as store:
        store.save_trial(make_result("t1"), {"t.py::test_b": SIG})
        store.save_trial(make_result("t2"), {"t.py::test_b": SIG})
        assert store.conn.execute("SELECT COUNT(*) FROM signatures").fetchone() == (1,)
        assert store.signature_of("t2", "t.py::test_b") == SIG


def test_duplicate_trial_id_is_rejected_atomically(tmp_path: Path) -> None:
    with Store(tmp_path) as store:
        store.save_trial(make_result())
        with pytest.raises(sqlite3.IntegrityError):
            store.save_trial(make_result())
        assert store.conn.execute("SELECT COUNT(*) FROM outcomes").fetchone() == (2,)


def test_unknown_trial_is_actionable_error(tmp_path: Path) -> None:
    with Store(tmp_path) as store, pytest.raises(FlakyAnythingError):
        store.load_trial("nope")


def test_schema_version_mismatch_is_actionable_error(tmp_path: Path) -> None:
    db = tmp_path / STATE_DIR / "runs.db"
    db.parent.mkdir()
    sqlite3.connect(db).execute("PRAGMA user_version = 99").connection.close()
    with pytest.raises(FlakyAnythingError) as exc:
        Store(tmp_path)
    assert "delete" in (exc.value.hint or "")


def test_config_by_id_and_failing_config_ids(tmp_path: Path) -> None:
    first = make_result("t1")
    other = first.model_copy(
        update={"trial_id": "t2", "config": first.config.model_copy(update={"hash_seed": 9})}
    )
    again = first.model_copy(update={"trial_id": "t3"})  # same config as t1, failed again
    with Store(tmp_path) as store:
        for res in (first, other, again):
            store.save_trial(res, {"t.py::test_b": SIG})
        assert store.config(first.config.config_id) == first.config
        ids = [first.config.config_id, other.config.config_id]
        assert store.failing_config_ids("t.py::test_b") == ids  # oldest first, no repeats
        assert store.failing_config_ids("t.py::test_a") == ids  # a timeout is a failure
        assert store.failing_config_ids("t.py::nope") == []
        with pytest.raises(FlakyAnythingError, match="no config"):
            store.config("0" * 16)
