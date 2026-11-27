import random

from flaky_anything.config import OrderSpec, TrialConfig
from flaky_anything.knobs.base import Knob
from flaky_anything.knobs.order import OrderKnob, explicit

CFG = TrialConfig(nodeids=["t.py::a", "t.py::b"])
knob = OrderKnob()


def test_is_a_knob() -> None:
    k: Knob[OrderSpec] = knob
    assert isinstance(k, Knob)


def test_sampling_is_deterministic_per_rng_seed_and_varies() -> None:
    assert knob.sample(random.Random(7)) == knob.sample(random.Random(7))
    samples = [knob.sample(random.Random(s)) for s in range(20)]
    assert all(v.mode == "shuffle" for v in samples)
    assert len({v.seed for v in samples}) == 20


def test_apply_round_trips_through_stored_json() -> None:
    for value in (knob.baseline(), knob.sample(random.Random(0)), OrderSpec(mode="explicit")):
        cfg = knob.apply(CFG, value)
        assert TrialConfig.model_validate_json(cfg.canonical_json()).order == value
        assert cfg.nodeids == CFG.nodeids


def test_baseline_is_collection_and_resets_a_shuffle() -> None:
    shuffled = knob.apply(CFG, knob.sample(random.Random(0)))
    assert knob.apply(shuffled, knob.baseline()) == CFG


def test_describe_and_plain_repro() -> None:
    assert knob.describe(knob.baseline()) == "order: collection order"
    assert knob.describe(OrderSpec(mode="shuffle", seed=5)) == "order: shuffled (seed 5)"
    assert knob.describe(OrderSpec(mode="explicit")) == "order: as listed"
    assert knob.plain_pytest_repro(OrderSpec(mode="shuffle", seed=5)) is None
    assert knob.plain_pytest_repro(OrderSpec(mode="explicit")) == "-p no:randomly"


def test_explicit_sets_nodeids_and_mode() -> None:
    cfg = explicit(CFG.model_copy(update={"random_seed": 3}), ["t.py::b", "t.py::a"])
    assert cfg.nodeids == ["t.py::b", "t.py::a"]
    assert cfg.order == OrderSpec(mode="explicit")
    assert cfg.random_seed == 3  # other knobs untouched
