"""Phase A + B on a copy of the corpus: every knob-controlled case gets confirmed flaky."""

import random
import shutil
import sys
from pathlib import Path

from flaky_anything.hints import hints_for
from flaky_anything.hunt import phase_a, phase_b, phase_b_targets, tally
from flaky_anything.knobs.registry import select
from flaky_anything.selection import collect
from flaky_anything.store import Store

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

CORPUS = Path(__file__).parents[1] / "corpus"
GT = tomllib.loads((CORPUS / "ground_truth.toml").read_text())


def test_phase_b_confirms_every_controlled_case_and_no_stable_test(tmp_path: Path) -> None:
    root = tmp_path / "project"
    shutil.copytree(CORPUS / "project", root)
    nodeids = collect(root)
    knobs, rng = select(), random.Random(0)
    with Store(root) as store:
        seen = tally(phase_a(nodeids, knobs, rng, root, store, jobs=4))
        targets = phase_b_targets(nodeids, seen, hints_for(root, nodeids))
        phase_b(nodeids, targets, seen, knobs, rng, root, store, rounds=10, jobs=4)

    confirmed = {n for n, t in seen.items() if t.confirmed_flaky}
    # U1 (os.urandom) is excluded: whether it fails in a given trial is not ours to decide.
    controlled = {c["nodeid"] for c in GT["cases"].values() if c["category"] != "uncontrolled"}
    assert controlled <= confirmed
    assert not {n for n, t in seen.items() if t.failed} & set(GT["stable"]["nodeids"])
