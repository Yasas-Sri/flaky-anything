"""Pytest plugin loaded INSIDE a trial subprocess: `-p flaky_anything.trial_plugin`.

Reads the TrialConfig from $FLAKY_ANYTHING_TRIAL, applies order / seeds / clock, and appends
JSON lines to $FLAKY_ANYTHING_RESULT as tests start and finish, so a killed (timed-out) trial still
tells us which tests completed and which one hung (D15). PYTHONHASHSEED and TZ must be set by the
caller before interpreter start; the plugin only verifies them (a mismatch would mislabel results).
"""

import hashlib
import json
import os
import random
import re
import sys
from collections.abc import Generator
from pathlib import Path
from typing import Literal

import pytest
import time_machine
from pydantic import BaseModel

from flaky_anything.config import TrialConfig

TRIAL_ENV = "FLAKY_ANYTHING_TRIAL"
RESULT_ENV = "FLAKY_ANYTHING_RESULT"


class NodeResult(BaseModel):
    nodeid: str
    outcome: Literal["passed", "failed", "skipped", "timeout", "error"]  # last two: runner only
    phase: Literal["setup", "call", "teardown"]  # where it failed/skipped; "call" if passed
    duration: float
    longrepr: str | None = None


class PluginOutput(BaseModel):
    """Parsed result file. config_id/exitstatus are None if the session never finished."""

    config_id: str | None = None
    exitstatus: int | None = None
    results: list[NodeResult] = []
    collection_errors: list[str] = []
    running: str | None = None  # started but never finished (hung or crashed)


def read_plugin_output(path: Path) -> PluginOutput:
    out = PluginOutput()
    for line in path.read_text().splitlines():
        event = json.loads(line)
        if "start" in event:
            out.running = event["start"]
        elif "result" in event:
            out.results.append(NodeResult.model_validate(event["result"]))
            out.running = None
        elif "collection_error" in event:
            out.collection_errors.append(event["collection_error"])
        elif "end" in event:
            out.config_id, out.exitstatus = event["end"]["config_id"], event["end"]["exitstatus"]
    return out


def _emit(event: dict[str, object]) -> None:
    path = os.environ.get(RESULT_ENV)
    if path:
        with open(path, "a") as f:
            f.write(json.dumps(event) + "\n")


# pytest's assertion rewriting prints `os.environ` in full: the user's whole environment (secrets
# included) plus per-trial paths that would make every failure a new signature (D31).
_ENV_REPR = re.compile(r"environ\(\{.*?(?:\}\)|$)", re.MULTILINE)


def redact_env(text: str) -> str:
    return _ENV_REPR.sub("environ({...})", text)


def per_test_seed(random_seed: int, nodeid: str) -> int:
    """Per-test seed: stable across processes and independent of which other tests run."""
    digest = hashlib.sha256(f"{random_seed}:{nodeid}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _position(item_nodeid: str, index: dict[str, int]) -> int:
    """Index of the arg that selected this item (exact id, or a file/class prefix of it)."""
    if item_nodeid in index:
        return index[item_nodeid]
    hits = [i for n, i in index.items() if item_nodeid.startswith(n + "::")]
    return min(hits, default=len(index))


class _Trial:
    def __init__(self, cfg: TrialConfig) -> None:
        self.cfg = cfg
        self.results: dict[str, NodeResult] = {}

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        order = self.cfg.order
        if order.mode == "explicit":
            index = {n: i for i, n in enumerate(self.cfg.nodeids)}
            items.sort(key=lambda it: _position(it.nodeid, index))  # stable within one arg
        elif order.mode == "shuffle":
            random.Random(order.seed).shuffle(items)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item: pytest.Item) -> Generator[None, None, None]:
        # Each test starts at the configured instant (setup through teardown), so an edge like
        # 23:59:59.5 is hit by every test regardless of how long earlier tests took (D11, D14).
        instant = self.cfg.clock.instant
        if instant is None:
            yield
            return
        # A timestamp, never an aware datetime: that would override TZ (D11).
        with time_machine.travel(instant.timestamp(), tick=self.cfg.clock.tick):
            yield

    def pytest_runtest_setup(self, item: pytest.Item) -> None:
        if self.cfg.random_seed is None:
            return
        seed = per_test_seed(self.cfg.random_seed, item.nodeid)
        random.seed(seed)
        # ponytail: only seeds numpy if already imported; lazy imports inside a test stay unseeded
        np = sys.modules.get("numpy")
        if np is not None:
            np.random.seed(seed % 2**32)

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.failed:
            _emit({"collection_error": f"{report.nodeid}: {report.longreprtext}"})

    def pytest_runtest_logstart(self, nodeid: str) -> None:
        _emit({"start": nodeid})

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        r = self.results.setdefault(
            report.nodeid,
            NodeResult(nodeid=report.nodeid, outcome="passed", phase="call", duration=0.0),
        )
        r.duration += report.duration
        if report.failed and r.outcome != "failed":
            r.outcome, r.phase, r.longrepr = "failed", report.when, redact_env(report.longreprtext)
        elif report.skipped and r.outcome == "passed":
            r.outcome, r.phase = "skipped", report.when

    def pytest_runtest_logfinish(self, nodeid: str) -> None:
        r = self.results.pop(nodeid, None)
        if r is not None:
            _emit({"result": r.model_dump()})

    def pytest_sessionfinish(self, exitstatus: int) -> None:
        _emit({"end": {"config_id": self.cfg.config_id, "exitstatus": int(exitstatus)}})


def _check_env(cfg: TrialConfig) -> None:
    want_hash = None if cfg.hash_seed is None else str(cfg.hash_seed)
    if os.environ.get("PYTHONHASHSEED") != want_hash:
        raise pytest.UsageError(
            f"flaky-anything: config has hash_seed={cfg.hash_seed} but PYTHONHASHSEED="
            f"{os.environ.get('PYTHONHASHSEED')!r}; it must be set before Python starts"
        )
    if cfg.tz is not None and os.environ.get("TZ") != cfg.tz:
        raise pytest.UsageError(
            f"flaky-anything: config has tz={cfg.tz!r} but TZ={os.environ.get('TZ')!r}"
        )


def pytest_configure(config: pytest.Config) -> None:
    path = os.environ.get(TRIAL_ENV)
    if not path:
        raise pytest.UsageError(f"flaky-anything trial plugin loaded but ${TRIAL_ENV} is not set")
    cfg = TrialConfig.model_validate_json(Path(path).read_text())
    _check_env(cfg)
    config.pluginmanager.register(_Trial(cfg), "flaky_anything_trial")
