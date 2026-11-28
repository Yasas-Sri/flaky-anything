import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from flaky_anything.errors import FlakyAnythingError
from flaky_anything.selection import History, collect, junit_history

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

CORPUS = Path(__file__).parents[1] / "corpus"


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("sel") / "project"
    shutil.copytree(CORPUS / "project", root)
    return root


def test_collects_every_corpus_test_from_testpaths(project: Path) -> None:
    gt = tomllib.loads((CORPUS / "ground_truth.toml").read_text())
    nodeids = collect(project)
    assert len(nodeids) == len(set(nodeids)) == 19
    assert {c["nodeid"] for c in gt["cases"].values()} | set(gt["stable"]["nodeids"]) <= set(
        nodeids
    )


def test_collects_given_files_and_node_ids_in_order(project: Path) -> None:
    ids = collect(project, ["tests/test_seeds.py", "tests/test_order.py::test_configure"])
    assert ids == [
        "tests/test_seeds.py::test_sample_has_no_duplicates_bug",
        "tests/test_seeds.py::test_tags_render_in_order",
        "tests/test_seeds.py::test_uses_os_urandom",
        "tests/test_order.py::test_configure",
    ]


def test_collection_error_is_actionable(tmp_path: Path) -> None:
    (tmp_path / "test_broken.py").write_text("import no_such_module_xyz\n")
    with pytest.raises(FlakyAnythingError, match="no_such_module_xyz") as e:
        collect(tmp_path)
    assert e.value.hint is not None


def test_no_tests_is_actionable(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(FlakyAnythingError, match="collected no tests"):
        collect(tmp_path, ["empty"])


def test_real_pytest_junit_maps_back_to_node_ids(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "test_m.py").write_text(
        "import pytest\n"
        "class TestC:\n"
        "    @pytest.mark.parametrize('v', ['a::b/c', 2])\n"
        "    def test_p(self, v): assert v != 2\n"
        "def test_f(): pass\n"
    )
    xml = tmp_path / "ci.xml"
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}"]
    subprocess.run(cmd, cwd=tmp_path, capture_output=True, timeout=120)
    nodeids = collect(tmp_path)
    assert junit_history([xml], nodeids) == {
        "pkg/test_m.py::TestC::test_p[2]": History(passed=0, failed=1),
        "pkg/test_m.py::TestC::test_p[a::b/c]": History(passed=1, failed=0),
        "pkg/test_m.py::test_f": History(passed=1, failed=0),
    }
