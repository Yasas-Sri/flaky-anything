import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

pytestmark = pytest.mark.e2e

# The installed console script, next to the interpreter running this test.
SCRIPT = Path(sys.executable).parent / "flaky-anything"


def test_installed_console_script_lists_commands() -> None:
    out = subprocess.run(
        [str(SCRIPT), "--help"], capture_output=True, text=True, check=True, timeout=60
    ).stdout
    for cmd in ["hunt", "diagnose", "repro", "fix", "verify", "report", "version"]:
        assert cmd in out


def test_installed_console_script_stub_exits_2() -> None:
    proc = subprocess.run([str(SCRIPT), "diagnose"], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2
    assert "not implemented" in proc.stderr


def test_hunt_on_the_corpus_finds_every_controlled_case_and_no_stable_test(
    tmp_path: Path,
) -> None:
    """M4 acceptance via the installed CLI (with --jobs 4 for speed; /check runs it literally)."""
    corpus = Path(__file__).parents[1] / "corpus"
    root = tmp_path / "project"
    shutil.copytree(corpus / "project", root)
    cmd = [str(SCRIPT), "hunt", str(root), "--seed", "0", "--budget", "5m", "--jobs", "4", "--json"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    gt = tomllib.loads((corpus / "ground_truth.toml").read_text())
    flaky = {f["nodeid"] for f in report["flaky"]}
    found = flaky | {f["nodeid"] for f in report["broken"]}
    controlled = {c["nodeid"] for c in gt["cases"].values() if c["category"] != "uncontrolled"}
    assert controlled <= flaky  # U1 (os.urandom) left out: not ours to decide
    assert not found & set(gt["stable"]["nodeids"])
