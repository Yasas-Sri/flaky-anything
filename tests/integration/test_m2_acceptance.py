"""M2 acceptance: a real corpus order pair through run_trial, persisted and re-loaded via Store."""

import shutil
from pathlib import Path

from flaky_anything.config import OrderSpec, TrialConfig
from flaky_anything.runner import run_trial
from flaky_anything.signatures import signatures_for
from flaky_anything.store import Store

CORPUS = Path(__file__).parents[1] / "corpus" / "project"
POLLUTER = "tests/test_order.py::test_warm_cache"
VICTIM = "tests/test_order.py::test_lookup_empty_cache"


def _cfg(nodeids: list[str]) -> TrialConfig:
    return TrialConfig(
        nodeids=nodeids, order=OrderSpec(mode="explicit"), hash_seed=0, random_seed=0, tz="UTC"
    )


def test_corpus_order_pair_fails_one_way_passes_reversed_and_round_trips(tmp_path: Path) -> None:
    root = tmp_path / "project"  # a copy: the repo's corpus never gets a .flaky-anything/ dir
    shutil.copytree(CORPUS, root)

    failing = run_trial(_cfg([POLLUTER, VICTIM]), root)
    reversed_ = run_trial(_cfg([VICTIM, POLLUTER]), root)
    outcome = {r.nodeid: r.outcome for r in failing.results}
    assert failing.status == "ok"
    assert outcome == {POLLUTER: "passed", VICTIM: "failed"}
    assert reversed_.status == "ok"
    assert {r.outcome for r in reversed_.results} == {"passed"}
    assert [r.nodeid for r in reversed_.results] == [VICTIM, POLLUTER]

    with Store(root) as store:
        for res in (failing, reversed_):
            store.save_trial(res, signatures_for(res))
    with Store(root) as store:  # fresh connection: really re-loaded from disk
        assert store.load_trial(failing.trial_id) == failing
        assert store.load_trial(reversed_.trial_id) == reversed_
        sig = store.signature_of(failing.trial_id, VICTIM)
    assert sig is not None
    assert sig.exc_type == "AssertionError"
