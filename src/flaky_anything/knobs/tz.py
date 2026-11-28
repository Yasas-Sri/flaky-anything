"""Time zone knob: TZ is set before interpreter start (runner), so it needs no plugin."""

import random

from flaky_anything.config import TrialConfig
from flaky_anything.knobs.base import replace

# Far offsets, half/quarter hours, both DST hemispheres, 30-min DST (Lord Howe), +14/-11.
ZONES = (
    "UTC",
    "America/New_York",
    "Europe/London",
    "Asia/Kolkata",
    "Asia/Colombo",
    "America/St_Johns",
    "Australia/Lord_Howe",
    "Pacific/Kiritimati",
    "Pacific/Pago_Pago",
)


class TzKnob:
    name = "tz"

    def __init__(self, zones: tuple[str, ...] = ZONES) -> None:
        self.zones = zones

    def baseline(self) -> str:
        return "UTC"

    def sample(self, rng: random.Random) -> str:
        return rng.choice(self.zones)

    def apply(self, config: TrialConfig, value: str) -> TrialConfig:
        return replace(config, tz=value)

    def describe(self, value: str) -> str:
        return f"tz: {value}"

    def plain_pytest_repro(self, value: str) -> str | None:
        return f"TZ={value}"
