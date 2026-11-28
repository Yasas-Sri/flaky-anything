"""Same seed → same hunt, whatever `--jobs` is (PLAN M4). U1 is left out: os.urandom decides
its outcomes, and an outcome changes which Phase B groups still need running (D32)."""

import shutil
from pathlib import Path

from flaky_anything.hunt import Budget, hunt
from flaky_anything.selection import collect

CORPUS = Path(__file__).parents[1] / "corpus" / "project"
U1 = "tests/test_seeds.py::test_uses_os_urandom"


def test_same_seed_gives_the_same_report_at_any_jobs(tmp_path: Path) -> None:
    reports = []
    for jobs in (1, 4):
        root = tmp_path / f"jobs{jobs}" / "project"
        shutil.copytree(CORPUS, root)
        nodeids = [n for n in collect(root) if n != U1]
        reports.append(hunt(root, nodeids, seed=3, budget=Budget(max_trials=40), jobs=jobs))
    assert reports[0] == reports[1]
    assert reports[0].trials == 40  # the budget bound
    assert reports[0].flaky  # and it found things
