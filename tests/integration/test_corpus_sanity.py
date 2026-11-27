"""The corpus behaves as documented when triggers are applied by hand (M1 acceptance).

Independent of flaky_anything: env vars, explicit node-id order and time-machine only.
Every check is RUNS fresh subprocesses with a fully pinned config, so it's deterministic.
U1 is excluded: it is random by design (os.urandom) and nothing here can pin it.
"""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import cache
from pathlib import Path
from typing import Any

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

RUNS = 20
CORPUS = Path(__file__).parents[1] / "corpus"
PROJECT = CORPUS / "project"
GT = tomllib.loads((CORPUS / "ground_truth.toml").read_text())
CASES = {k: v for k, v in GT["cases"].items() if v["category"] != "uncontrolled"}

# Baseline per ARCHITECTURE.md. random_seed is a raw random.seed() value here (the tool's
# per-test derivation doesn't exist yet): 1 passes S1, 0 fails it, on every Python >= 3.10.
BASELINE: dict[str, Any] = {
    "hash_seed": 0,
    "random_seed": 1,
    "clock": "2027-06-16T10:00:00+00:00",
    "tz": "UTC",
}
FAILING_RANDOM_SEED = 0


def run(nodeids: list[str], cfg: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items()}
    for leak in ("CORPUS_MODE", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
        env.pop(leak, None)
    env.update(
        PYTHONHASHSEED=str(cfg["hash_seed"]),
        TZ=cfg["tz"],
        SANITY_RANDOM_SEED=str(cfg["random_seed"]),
        SANITY_CLOCK=str(cfg["clock"]),
        PYTHONPATH=str(Path(__file__).parent),
        PYTHONDONTWRITEBYTECODE="1",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",  # only the plugins named below; faster, isolated
    )
    plugins = ["-p", "sanity_plugin", "-p", "no:cacheprovider", "-p", "no:randomly"]
    cmd = [sys.executable, "-m", "pytest", "-q", "-rf", *plugins, *nodeids]
    return subprocess.run(cmd, cwd=PROJECT, env=env, capture_output=True, text=True, timeout=120)


def run_many(nodeids: list[str], cfg: dict[str, Any]) -> list[subprocess.CompletedProcess[str]]:
    with ThreadPoolExecutor(max_workers=min(RUNS, os.cpu_count() or 1)) as pool:
        return list(pool.map(lambda _: run(nodeids, cfg), range(RUNS)))


def victim_failed(p: subprocess.CompletedProcess[str], nodeid: str) -> bool:
    # rc 1 = tests failed (not a usage/collection error), and it is the victim that failed.
    return p.returncode == 1 and f"FAILED {nodeid}" in p.stdout


@cache
def failing_hash_seed(nodeid: str) -> int:
    """S2's failing PYTHONHASHSEED depends on the interpreter (D9): search for one."""
    for seed in range(1, 50):
        if victim_failed(run([nodeid], {**BASELINE, "hash_seed": seed}), nodeid):
            return seed
    raise AssertionError(f"no failing PYTHONHASHSEED in 1..49 for {nodeid}")


def trigger_config(case: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    trigger = case.get("trigger", {})
    cfg = {**BASELINE, **{k: v for k, v in trigger.items() if k != "order"}}
    if "random_seed" in case["necessary_knobs"]:
        cfg["random_seed"] = FAILING_RANDOM_SEED
    if "hash_seed" in case["necessary_knobs"]:
        cfg["hash_seed"] = failing_hash_seed(case["nodeid"])
    return trigger.get("order", [case["nodeid"]]), cfg


def test_baseline_whole_suite_passes() -> None:
    u1 = [c["nodeid"] for c in GT["cases"].values() if c["category"] == "uncontrolled"]
    deselect = [arg for nodeid in u1 for arg in ("--deselect", nodeid)]
    results = run_many(deselect, BASELINE)
    bad = [p.stdout[-2000:] for p in results if p.returncode != 0]
    assert not bad, f"{len(bad)}/{RUNS} baseline runs failed:\n{bad[0]}"
    assert all("passed" in p.stdout for p in results)


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_case_fails_every_time_under_its_trigger(case_id: str) -> None:
    case = CASES[case_id]
    nodeids, cfg = trigger_config(case)
    results = run_many(nodeids, cfg)
    passed = [p for p in results if not victim_failed(p, case["nodeid"])]
    assert not passed, f"{case_id}: {len(passed)}/{RUNS} runs did not fail:\n{passed[0].stdout}"


@pytest.mark.parametrize(
    ("case_id", "dropped"),
    [
        (k, knob)
        for k, c in sorted(CASES.items())
        if len(t := c.get("trigger", {})) > 1
        for knob in t
    ],
)
def test_each_knob_of_a_combined_trigger_is_necessary(case_id: str, dropped: str) -> None:
    case = CASES[case_id]
    nodeids, cfg = trigger_config(case)
    cfg[dropped] = BASELINE[dropped]
    results = run_many(nodeids, cfg)
    bad = [p for p in results if p.returncode != 0]
    assert not bad, f"{case_id} without {dropped}: {len(bad)}/{RUNS} failed:\n{bad[0].stdout}"
