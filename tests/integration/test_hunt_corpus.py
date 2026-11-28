"""hunt() on a copy of the corpus: the M4 acceptance check, minus the CLI."""

import shutil
import sys
from pathlib import Path

from flaky_anything.hunt import hunt

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

CORPUS = Path(__file__).parents[1] / "corpus"
GT = tomllib.loads((CORPUS / "ground_truth.toml").read_text())


def test_hunt_finds_every_controlled_case_and_no_stable_test(tmp_path: Path) -> None:
    root = tmp_path / "project"
    shutil.copytree(CORPUS / "project", root)
    report = hunt(root, seed=0, jobs=4)
    flaky = {f.nodeid for f in report.flaky}
    controlled = {c["nodeid"] for c in GT["cases"].values() if c["category"] != "uncontrolled"}
    assert controlled <= flaky  # U1 (os.urandom) is left out: not ours to decide
    assert not (flaky | {f.nodeid for f in report.broken}) & set(GT["stable"]["nodeids"])
    assert report.tests_selected == 19
    assert not report.budget_spent
    assert all(f.signatures and f.failing_config_ids for f in report.flaky)
