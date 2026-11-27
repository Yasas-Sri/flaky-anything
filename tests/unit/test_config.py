from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from flaky_anything.config import ClockSpec, OrderSpec, TrialConfig

NODES = ["tests/test_a.py::test_x", "tests/test_a.py::test_y"]


def full_config() -> TrialConfig:
    return TrialConfig(
        nodeids=NODES,
        order=OrderSpec(mode="shuffle", seed=3),
        hash_seed=7,
        random_seed=11,
        clock=ClockSpec(instant=datetime(2027, 1, 31, 23, 59, 59, 500000, tzinfo=timezone.utc)),
        tz="America/New_York",
        timeout_s=30,
    )


def test_config_id_is_pinned() -> None:
    # Golden value: if this changes, every stored config_id changes. Only update on purpose.
    assert full_config().config_id == "d3d4088c8a26055c"


def test_json_round_trip_preserves_config_and_id() -> None:
    cfg = full_config()
    again = TrialConfig.model_validate_json(cfg.canonical_json())
    assert again == cfg
    assert again.config_id == cfg.config_id


def test_same_instant_in_other_offset_has_same_id() -> None:
    plus14 = timezone(timedelta(hours=14))
    a = TrialConfig(nodeids=NODES, clock=ClockSpec(instant=datetime(2027, 1, 1, tzinfo=plus14)))
    b = TrialConfig(
        nodeids=NODES, clock=ClockSpec(instant=datetime(2026, 12, 31, 10, tzinfo=timezone.utc))
    )
    assert a.config_id == b.config_id


@pytest.mark.parametrize(
    "change",
    [
        {"nodeids": list(reversed(NODES))},
        {"order": OrderSpec(mode="shuffle", seed=4)},
        {"hash_seed": 8},
        {"random_seed": None},
        {"clock": ClockSpec(instant=None)},
        {"tz": "UTC"},
        {"timeout_s": 31},
    ],
)
def test_every_field_affects_config_id(change: dict[str, object]) -> None:
    changed = TrialConfig.model_validate({**full_config().model_dump(), **change})
    assert changed.config_id != full_config().config_id


@pytest.mark.parametrize(
    "bad",
    [
        {"nodeids": []},
        {"nodeids": NODES, "order": {"mode": "shuffle"}},
        {"nodeids": NODES, "order": {"mode": "explicit", "seed": 1}},
        {"nodeids": NODES, "clock": {"instant": "2027-01-31T23:59:59"}},  # naive
        {"nodeids": NODES, "tz": "Mars/Olympus_Mons"},
        {"nodeids": NODES, "hash_seed": -1},
        {"nodeids": NODES, "hash_seed": 2**32},
        {"nodeids": NODES, "timeout_s": 0},
        {"nodeids": NODES, "surprise": 1},
    ],
)
def test_invalid_configs_are_rejected(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TrialConfig.model_validate(bad)


def test_configs_are_immutable() -> None:
    with pytest.raises(ValidationError):
        full_config().hash_seed = 1  # type: ignore[misc]
