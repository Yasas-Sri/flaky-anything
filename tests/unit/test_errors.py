import pytest

from flaky_anything import cli
from flaky_anything.errors import FlakyAnythingError


def _raise() -> None:
    raise FlakyAnythingError("not a git repo", hint="run `git init` first")


def test_run_renders_error_and_hint_and_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "app", _raise)
    with pytest.raises(SystemExit) as exc:
        cli.run()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "error: not a git repo" in err
    assert "hint: run `git init` first" in err
    assert "Traceback" not in err


def test_hint_is_optional(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom() -> None:
        raise FlakyAnythingError("bad")

    monkeypatch.setattr(cli, "app", boom)
    with pytest.raises(SystemExit):
        cli.run()
    assert "hint" not in capsys.readouterr().err
