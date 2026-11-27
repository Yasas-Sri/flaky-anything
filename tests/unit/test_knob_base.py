import random

import pytest
from pydantic import ValidationError

from flaky_anything.config import TrialConfig
from flaky_anything.knobs.base import Knob, replace


class _TzKnob:
    name = "tz"

    def baseline(self) -> str:
        return "UTC"

    def sample(self, rng: random.Random) -> str:
        return rng.choice(["UTC", "Asia/Colombo"])

    def apply(self, config: TrialConfig, value: str) -> TrialConfig:
        return replace(config, tz=value)

    def describe(self, value: str) -> str:
        return f"tz: {value}"

    def plain_pytest_repro(self, value: str) -> str | None:
        return f"TZ={value}"


def test_structural_knob_satisfies_protocol() -> None:
    knob: Knob[str] = _TzKnob()
    assert isinstance(knob, Knob)
    cfg = knob.apply(TrialConfig(nodeids=["t.py::x"]), knob.sample(random.Random(0)))
    assert cfg.tz in {"UTC", "Asia/Colombo"}


def test_incomplete_class_is_not_a_knob() -> None:
    class NoApply:
        name = "x"

        def baseline(self) -> int:
            return 0

    assert not isinstance(NoApply(), Knob)


def test_replace_revalidates() -> None:
    cfg = TrialConfig(nodeids=["t.py::x"])
    assert replace(cfg, random_seed=3).random_seed == 3
    with pytest.raises(ValidationError, match="unknown time zone"):
        replace(cfg, tz="Mars/Olympus")
