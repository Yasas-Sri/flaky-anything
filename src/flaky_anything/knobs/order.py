"""Order knob: collection order (baseline), seeded shuffle (sampled), explicit lists (bisection)."""

import random
from collections.abc import Sequence

from flaky_anything.config import OrderSpec, TrialConfig
from flaky_anything.knobs.base import replace

# Plain pytest runs node ids in argument order; only pytest-randomly would reorder them.
_NO_RANDOMLY = "-p no:randomly"


class OrderKnob:
    name = "order"

    def baseline(self) -> OrderSpec:
        return OrderSpec()

    def sample(self, rng: random.Random) -> OrderSpec:
        return OrderSpec(mode="shuffle", seed=rng.randrange(2**32))

    def apply(self, config: TrialConfig, value: OrderSpec) -> TrialConfig:
        return replace(config, order=value)

    def describe(self, value: OrderSpec) -> str:
        if value.mode == "shuffle":
            return f"order: shuffled (seed {value.seed})"
        return "order: as listed" if value.mode == "explicit" else "order: collection order"

    def plain_pytest_repro(self, value: OrderSpec) -> str | None:
        # A shuffle needs the plugin; diagnosis turns a failing shuffle into an explicit list.
        return None if value.mode == "shuffle" else _NO_RANDOMLY


def explicit(config: TrialConfig, nodeids: Sequence[str]) -> TrialConfig:
    """Run exactly `nodeids`, in that order (polluter bisection, repros)."""
    return replace(config, nodeids=list(nodeids), order=OrderSpec(mode="explicit"))
