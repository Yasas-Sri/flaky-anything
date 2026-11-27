import subprocess
import sys
from pathlib import Path

import pytest

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
    proc = subprocess.run([str(SCRIPT), "hunt"], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2
    assert "not implemented" in proc.stderr
