import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from flaky_anything import hunt as hunt_mod
from flaky_anything.cli import app
from flaky_anything.hunt import HuntReport, SignatureCount, TestFinding

REPORT = HuntReport(
    seed=3,
    knobs=["order", "tz"],
    tests_selected=5,
    trials=42,
    budget_spent=True,
    flaky=[
        TestFinding(
            nodeid="tests/test_x.py::test_flaky",
            verdict="flaky",
            passed=7,
            failed=3,
            failure_rate=0.3,
            rate_low=0.107789,
            rate_high=0.603222,
            signatures=[SignatureCount(id="85c6de6ec6e31a5b", exc_type="ValueError", count=3)],
            failing_config_ids=["d3d4088c8a26055c", "0123456789abcdef"],
        )
    ],
    broken=[],
)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    def fake_hunt(root: Path, paths: list[str], **kw: Any) -> HuntReport:
        seen.append({"root": root, "paths": paths, **kw})
        return REPORT

    monkeypatch.setattr(hunt_mod, "hunt", fake_hunt)
    (tmp_path / "pyproject.toml").write_text("")
    monkeypatch.chdir(tmp_path)
    return seen


def test_table_shows_findings_with_rates_signature_and_next_step(
    calls: list[dict[str, Any]],
) -> None:
    result = CliRunner().invoke(app, ["hunt"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    out = result.output
    for text in (
        "tests/test_x.py::test_flaky",
        "flaky",
        "3/10",
        "30% (11%-60%)",
        "ValueError 85c6de6e",
        "d3d4088c8a26055c +1",
        "42 trials",
        "Budget spent",
        "Next: flaky-anything diagnose tests/test_x.py::test_flaky",
    ):
        assert text in out


def test_json_is_the_report(calls: list[dict[str, Any]]) -> None:
    result = CliRunner().invoke(app, ["hunt", "--json"])
    assert result.exit_code == 0
    assert HuntReport.model_validate(json.loads(result.stdout)) == REPORT


def test_options_reach_the_hunt(calls: list[dict[str, Any]], tmp_path: Path) -> None:
    args = [
        "hunt",
        "tests",
        "--seed",
        "9",
        "--jobs",
        "4",
        "--knobs",
        "order,tz",
        "--budget",
        "2m",
        "--max-trials",
        "30",
        "--python",
        "/x/python",
        "--from-junit",
        "a.xml",
        "--from-junit",
        "b.xml",
    ]
    assert CliRunner().invoke(app, args).exit_code == 0
    (call,) = calls
    assert call["root"] == tmp_path.resolve()
    assert call["paths"] == ["tests"]
    assert (call["seed"], call["jobs"], call["knobs"], call["python"]) == (
        9,
        4,
        "order,tz",
        "/x/python",
    )
    assert (call["budget"].max_trials, call["budget"].seconds) == (30, 120.0)
    assert call["junit"] == [Path("a.xml"), Path("b.xml")]
