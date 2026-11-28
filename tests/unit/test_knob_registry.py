from datetime import datetime, timezone

import pytest

from flaky_anything.config import ClockSpec, OrderSpec, TrialConfig
from flaky_anything.errors import FlakyAnythingError
from flaky_anything.knobs.registry import KNOBS, baseline_config, select


def names(spec: str) -> list[str]:
    return [k.name for k in select(spec)]


def test_default_is_all_knobs_in_ablation_order() -> None:
    assert names("order,seeds,clock,tz") == ["order", "hash_seed", "random_seed", "clock", "tz"]
    assert select() == list(KNOBS)


def test_selection_keeps_canonical_order_dedupes_and_expands_groups() -> None:
    assert names(" tz , order ") == ["order", "tz"]
    assert names("random_seed,seeds,clock,clock") == ["hash_seed", "random_seed", "clock"]


@pytest.mark.parametrize("spec", ["order,network", "", " , "])
def test_bad_selection_is_actionable(spec: str) -> None:
    with pytest.raises(FlakyAnythingError) as e:
        select(spec)
    assert e.value.hint is not None


def test_baseline_config_matches_architecture_baseline() -> None:
    assert baseline_config(["t.py::a"], timeout_s=30) == TrialConfig(
        nodeids=["t.py::a"],
        order=OrderSpec(mode="collection"),
        hash_seed=0,
        random_seed=0,
        clock=ClockSpec(instant=datetime(2027, 6, 16, 10, tzinfo=timezone.utc), tick=True),
        tz="UTC",
        timeout_s=30,
    )
