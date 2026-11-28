"""The Knob protocol (ARCHITECTURE.md §Knobs)."""

import random
from typing import Any, Protocol, TypeVar, runtime_checkable

from flaky_anything.config import TrialConfig

V = TypeVar("V")


@runtime_checkable
class Knob(Protocol[V]):
    """One hidden input. Values must round-trip through TrialConfig (hard rule 3)."""

    name: str

    def baseline(self) -> V:
        """The controlled, boring value; deterministic (ablation resets to it)."""
        ...

    def sample(self, rng: random.Random, config: TrialConfig) -> V:
        """A perturbed value; all randomness from `rng` so hunts are reproducible. `config` is
        the trial being sampled, with knobs earlier in registry order already set (D28)."""
        ...

    def apply(self, config: TrialConfig, value: V) -> TrialConfig:
        """A copy of `config` with this knob set to `value`."""
        ...

    def describe(self, value: V) -> str:
        """Human-readable, e.g. "clock: 2027-01-31 23:59:59.5 UTC (month end)"."""
        ...

    def plain_pytest_repro(self, value: V) -> str | None:
        """Env/args reproducing `value` without our plugin, or None if it needs the plugin."""
        ...


def replace(config: TrialConfig, **changes: Any) -> TrialConfig:
    """Like `model_copy(update=...)` but re-validated: a knob can't build an invalid config."""
    return TrialConfig.model_validate({**config.model_dump(), **changes})
