"""Phase A on a copy of the corpus: whole-selection runs under sampled configs."""

import random
import shutil
import sys
from pathlib import Path

from flaky_anything.hunt import phase_a, tally
from flaky_anything.knobs.registry import select
from flaky_anything.selection import collect
from flaky_anything.store import Store

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

CORPUS = Path(__file__).parents[1] / "corpus"
GT = tomllib.loads((CORPUS / "ground_truth.toml").read_text())
U1 = GT["cases"]["U1"]["nodeid"]  # os.urandom: its outcome is outside our knobs


def test_phase_a_runs_whole_selection_under_sampled_configs_and_stores_them(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    shutil.copytree(CORPUS / "project", root)
    nodeids = collect(root)
    with Store(root) as store:
        results = phase_a(nodeids, select(), random.Random(0), root, store, runs=8, jobs=4)
        assert [store.load_trial(r.trial_id) for r in results] == results

    assert len({r.config.config_id for r in results}) == 8
    assert all(r.status == "ok" and len(r.results) == len(nodeids) for r in results)
    assert all(r.config.order.mode == "shuffle" for r in results)

    seen = tally(results)
    failed = {n for n, t in seen.items() if t.failed}
    flaky_cases = {c["nodeid"] for c in GT["cases"].values()}
    assert failed <= flaky_cases  # stable controls never fail, whatever the config
    assert failed - {U1}  # and the knobs do make real cases fail (deterministic for a seed)
