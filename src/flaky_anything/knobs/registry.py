"""All knobs in ablation order, and `--knobs` selection."""

from collections.abc import Sequence
from typing import Any

from flaky_anything.config import TrialConfig
from flaky_anything.errors import FlakyAnythingError
from flaky_anything.knobs.base import Knob
from flaky_anything.knobs.clock import ClockKnob
from flaky_anything.knobs.order import OrderKnob
from flaky_anything.knobs.seeds import HashSeedKnob, RandomSeedKnob
from flaky_anything.knobs.tz import ZONES, TzKnob

# Order matters: ablation resets knobs in this order (ARCHITECTURE.md §Diagnosis).
KNOBS: tuple[Knob[Any], ...] = (
    OrderKnob(),
    HashSeedKnob(),
    RandomSeedKnob(),
    ClockKnob(ZONES),  # clock edges in every zone the tz knob can pick (D19)
    TzKnob(ZONES),
)
GROUPS = {"seeds": ("hash_seed", "random_seed")}
DEFAULT = "order,seeds,clock,tz"


def select(spec: str = DEFAULT) -> list[Knob[Any]]:
    """Parse `--knobs order,seeds,clock,tz` (groups or knob names) into KNOBS order."""
    names = {k.name for k in KNOBS}
    wanted: set[str] = set()
    for part in filter(None, (p.strip() for p in spec.split(","))):
        if part not in names and part not in GROUPS:
            valid = ", ".join([*GROUPS, *names])
            raise FlakyAnythingError(f"unknown knob {part!r}", hint=f"choose from: {valid}")
        wanted.update(GROUPS.get(part, (part,)))
    if not wanted:
        raise FlakyAnythingError("--knobs is empty", hint=f"e.g. --knobs {DEFAULT}")
    return [k for k in KNOBS if k.name in wanted]


def baseline_config(nodeids: Sequence[str], **fields: Any) -> TrialConfig:
    """Every knob at its baseline: the controlled, boring, deterministic config."""
    cfg = TrialConfig(nodeids=list(nodeids), **fields)
    for knob in KNOBS:
        cfg = knob.apply(cfg, knob.baseline())
    return cfg
