import random

import pytest

from flaky_anything.config import TrialConfig
from flaky_anything.knobs.base import Knob
from flaky_anything.knobs.seeds import HashSeedKnob, RandomSeedKnob

CFG = TrialConfig(nodeids=["t.py::a"])


@pytest.mark.parametrize("knob", [HashSeedKnob(), RandomSeedKnob()], ids=lambda k: k.name)
def test_seed_knob_contract(knob: Knob[int]) -> None:
    assert isinstance(knob, Knob)
    assert knob.sample(random.Random(3)) == knob.sample(random.Random(3))
    samples = {knob.sample(random.Random(s)) for s in range(20)}
    assert len(samples) == 20
    for value in (knob.baseline(), *samples):
        cfg = knob.apply(CFG, value)  # re-validated: hash_seed must fit PYTHONHASHSEED
        assert getattr(TrialConfig.model_validate_json(cfg.canonical_json()), knob.name) == value
    assert knob.baseline() == 0


def test_hash_seed_repro_is_plain_env() -> None:
    k = HashSeedKnob()
    assert k.describe(7) == "hash seed: PYTHONHASHSEED=7"
    assert k.plain_pytest_repro(7) == "PYTHONHASHSEED=7"


def test_random_seed_needs_plugin() -> None:
    k = RandomSeedKnob()
    assert k.describe(7) == "random seed: 7 (random.seed per test)"
    assert k.plain_pytest_repro(7) is None
