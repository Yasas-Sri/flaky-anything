"""Run one trial = one fresh pytest subprocess under a TrialConfig (ARCHITECTURE.md §The trial)."""

import os
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from flaky_anything.config import TrialConfig
from flaky_anything.errors import FlakyAnythingError
from flaky_anything.trial_plugin import RESULT_ENV, TRIAL_ENV, NodeResult, read_plugin_output

STATE_DIR = ".flaky-anything"
# Plugins that rerun, reorder or cache would change what a trial means; the config is the truth.
PYTEST_ARGS = ["-p", "flaky_anything.trial_plugin", "-p", "no:randomly", "-p", "no:rerunfailures"]
PYTEST_ARGS += ["-p", "no:flaky", "-p", "no:cacheprovider", "-q"]
# Fixed traceback style: failure signatures parse it; overrides a project's --tb in addopts.
PYTEST_ARGS += ["--tb=long"]
# Env that would alter the run without being recorded in the config (hard rule 3).
SCRUBBED_ENV = ("PYTHONHASHSEED", "TZ", "PYTEST_ADDOPTS", "PYTEST_PLUGINS")
STDERR_TAIL = 4000


class TrialResult(BaseModel):
    trial_id: str
    config: TrialConfig
    started_at: datetime
    duration: float
    status: Literal["ok", "timeout", "error"]
    results: list[NodeResult]
    collection_errors: list[str] = []
    stderr_tail: str = ""


def build_env(cfg: TrialConfig, trial_path: Path, result_path: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in SCRUBBED_ENV}
    if cfg.hash_seed is not None:
        env["PYTHONHASHSEED"] = str(cfg.hash_seed)
    tz = cfg.tz if cfg.tz is not None else os.environ.get("TZ")  # None = inherit
    if tz is not None:
        env["TZ"] = tz
    env[TRIAL_ENV] = str(trial_path)
    env[RESULT_ENV] = str(result_path)
    return env


def plugin_missing(stderr: str) -> bool:
    return "flaky_anything" in stderr and (
        "No module named" in stderr or "Error importing plugin" in stderr
    )


def _kill_group(proc: "subprocess.Popen[str]") -> None:
    if os.name == "posix":
        os.killpg(proc.pid, signal.SIGKILL)  # the test may have spawned children
    else:
        proc.kill()  # ponytail: Windows kills only the root; use a job object if that bites


def run_trial(config: TrialConfig, project_root: Path, python: str = sys.executable) -> TrialResult:
    state = project_root / STATE_DIR
    (state / "trials").mkdir(parents=True, exist_ok=True)
    (state / "results").mkdir(parents=True, exist_ok=True)
    trial_id = uuid.uuid4().hex[:16]
    trial_path = state / "trials" / f"{config.config_id}.json"
    result_path = state / "results" / f"{trial_id}.jsonl"
    # Atomic: parallel trials of the same config must never read a half-written file.
    tmp = trial_path.with_name(f".{trial_id}.tmp")
    tmp.write_text(config.canonical_json())
    os.replace(tmp, trial_path)

    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()
    proc = subprocess.Popen(
        [python, "-m", "pytest", *PYTEST_ARGS, *config.nodeids],
        cwd=project_root,
        env=build_env(config, trial_path, result_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=config.timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_group(proc)
        stdout, stderr = proc.communicate()
    duration = time.monotonic() - t0

    out = read_plugin_output(result_path) if result_path.exists() else None
    if out is None and not timed_out and plugin_missing(stderr):
        raise FlakyAnythingError(
            f"the trial plugin is not importable by {python}",
            hint="install flaky-anything in the project's environment (e.g. `uv add --dev "
            "flaky-anything`) or pass --python pointing at an interpreter that has it",
        )

    results = list(out.results) if out else []
    status: Literal["ok", "timeout", "error"]
    if timed_out:
        status = "timeout"
    elif out is None or out.exitstatus not in (0, 1):  # crash, usage/collection error, no tests
        status = "error"
    else:
        status = "ok"
    if status != "ok" and out and out.running:  # the test that hung or took the process down
        results.append(
            NodeResult(nodeid=out.running, outcome=status, phase="call", duration=duration)
        )
    tail = (stdout + stderr)[-STDERR_TAIL:] if status != "ok" else ""
    return TrialResult(
        trial_id=trial_id,
        config=config,
        started_at=started_at,
        duration=duration,
        status=status,
        results=results,
        collection_errors=out.collection_errors if out else [],
        stderr_tail=tail,
    )


def run_trials(
    configs: Sequence[TrialConfig],
    project_root: Path,
    jobs: int = 1,
    python: str = sys.executable,
) -> list[TrialResult]:
    """Run trials, `jobs` at a time; results in input order. Default 1: parallel trials of one
    project can interfere through shared files/ports/DBs (D5). Threads suffice: each trial is
    its own subprocess, the thread just waits on it (D16)."""
    if jobs < 1:
        raise FlakyAnythingError(f"--jobs must be >= 1, got {jobs}")
    if jobs == 1:
        return [run_trial(c, project_root, python) for c in configs]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(lambda c: run_trial(c, project_root, python), configs))
