import sys
from pathlib import Path

import pytest

from flaky_anything.errors import FlakyAnythingError
from flaky_anything.selection import default_python, find_root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for d in ("tests", "sub/proj/tests"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "tests" / "test_a.py").write_text("")
    (tmp_path / "sub" / "proj" / "pytest.ini").write_text("")
    (tmp_path / "sub" / "proj" / "tests" / "test_b.py").write_text("")
    return tmp_path


def test_no_paths_is_cwd_project(repo: Path) -> None:
    assert find_root([], cwd=repo) == (repo, [])


def test_project_dir_argument_becomes_root_with_its_testpaths(repo: Path) -> None:
    assert find_root(["sub/proj"], cwd=repo) == (repo / "sub/proj", [])


def test_files_and_node_ids_are_made_relative_to_their_root(repo: Path) -> None:
    ids = ["sub/proj/tests/test_b.py::test_x[a::b]", "sub/proj/tests"]
    assert find_root(ids, cwd=repo) == (
        repo / "sub/proj",
        ["tests/test_b.py::test_x[a::b]", "tests"],
    )
    assert find_root(["tests/test_a.py"], cwd=repo) == (repo, ["tests/test_a.py"])


def test_paths_in_different_projects_are_refused(repo: Path) -> None:
    with pytest.raises(FlakyAnythingError, match="outside the project root"):
        find_root(["sub/proj", "tests/test_a.py"], cwd=repo)


def test_default_python_prefers_the_project_venv(repo: Path) -> None:
    assert default_python(repo) == sys.executable
    venv = repo / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("")
    assert default_python(repo) == str(venv / "python")
