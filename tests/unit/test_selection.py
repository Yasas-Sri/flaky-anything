from pathlib import Path

import pytest

from flaky_anything.errors import FlakyAnythingError
from flaky_anything.selection import History, junit_history, junit_key

COLLECTED = [
    "tests/test_a.py::test_flaky",
    "tests/test_a.py::test_broken",
    "tests/test_a.py::test_stable",
    "tests/sub/test_b.py::TestC::test_y[a::b/c]",
    "tests/test_a.py::test_skipped",
]


def report(tmp_path: Path, name: str, cases: dict[str, str]) -> Path:
    """A pytest-style JUnit report; cases maps node id -> passed|failure|error|skipped."""
    body = ""
    for nodeid, outcome in cases.items():
        classname, test = junit_key(nodeid)
        inner = "" if outcome == "passed" else f'<{outcome} message="x">trace</{outcome}>'
        body += f'<testcase classname="{classname}" name="{test}" time="0.1">{inner}</testcase>'
    path = tmp_path / name
    path.write_text(f'<?xml version="1.0"?><testsuites><testsuite name="pytest">{body}'
                    "</testsuite></testsuites>")  # fmt: skip
    return path


def test_junit_key_mirrors_pytest() -> None:
    assert junit_key("tests/test_a.py::test_x") == ("tests.test_a", "test_x")
    assert junit_key("tests/sub/test_b.py::TestC::test_y[a::b/c]") == (
        "tests.sub.test_b.TestC",
        "test_y[a::b/c]",
    )


def test_mixed_outcomes_rank_first(tmp_path: Path) -> None:
    flaky, broken, stable, param, skipped = COLLECTED
    runs = [
        {flaky: "passed", broken: "failure", stable: "passed", param: "passed", skipped: "skipped"},
        {flaky: "failure", broken: "failure", stable: "passed", param: "error"},
        {flaky: "passed", broken: "failure", stable: "passed", param: "passed"},
        {"tests/test_gone.py::test_old": "failure"},  # no longer collected: dropped
    ]
    files = [report(tmp_path, f"r{i}.xml", r) for i, r in enumerate(runs)]
    history = junit_history(files, COLLECTED)
    assert list(history.items()) == [
        (flaky, History(passed=2, failed=1)),
        (param, History(passed=2, failed=1)),
        (broken, History(passed=0, failed=3)),
        (stable, History(passed=3, failed=0)),
    ]
    assert history[flaky].mixed
    assert not history[broken].mixed


def test_unreadable_junit_is_actionable(tmp_path: Path) -> None:
    bad = tmp_path / "bad.xml"
    bad.write_text("<testsuites><testcase")
    with pytest.raises(FlakyAnythingError, match=r"bad\.xml"):
        junit_history([bad], COLLECTED)
    with pytest.raises(FlakyAnythingError, match=r"missing\.xml"):
        junit_history([tmp_path / "missing.xml"], COLLECTED)
