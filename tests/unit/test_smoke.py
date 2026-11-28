import pytest
from typer.testing import CliRunner

from flaky_anything import __version__
from flaky_anything.cli import app


def test_version_command_prints_package_version() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() == __version__


@pytest.mark.parametrize("cmd", ["diagnose", "repro", "fix", "verify", "report"])
def test_stub_commands_exit_2(cmd: str) -> None:
    result = CliRunner().invoke(app, [cmd])
    assert result.exit_code == 2
    assert "not implemented" in result.output


def test_help_lists_all_commands() -> None:
    result = CliRunner().invoke(app, ["--help"])
    for cmd in ["hunt", "diagnose", "repro", "fix", "verify", "report", "version"]:
        assert cmd in result.output
