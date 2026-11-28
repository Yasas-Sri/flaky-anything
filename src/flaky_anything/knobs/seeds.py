"""Seed knobs: `hash_seed` (PYTHONHASHSEED, set before interpreter start) and `random_seed`
(applied per test by the trial plugin, see `trial_plugin.per_test_seed`)."""

import random

from flaky_anything.config import TrialConfig
from flaky_anything.knobs.base import replace

SEED_SPACE = 2**32  # PYTHONHASHSEED accepts [0, 2**32 - 1]; same range for random_seed


class HashSeedKnob:
    name = "hash_seed"

    def baseline(self) -> int:
        return 0

    def sample(self, rng: random.Random, config: TrialConfig) -> int:
        return rng.randrange(SEED_SPACE)

    def apply(self, config: TrialConfig, value: int) -> TrialConfig:
        return replace(config, hash_seed=value)

    def describe(self, value: int) -> str:
        return f"hash seed: PYTHONHASHSEED={value}"

    def plain_pytest_repro(self, value: int) -> str | None:
        return f"PYTHONHASHSEED={value}"


class RandomSeedKnob:
    name = "random_seed"

    def baseline(self) -> int:
        return 0

    def sample(self, rng: random.Random, config: TrialConfig) -> int:
        return rng.randrange(SEED_SPACE)

    def apply(self, config: TrialConfig, value: int) -> TrialConfig:
        return replace(config, random_seed=value)

    def describe(self, value: int) -> str:
        return f"random seed: {value} (random.seed per test)"

    def plain_pytest_repro(self, value: int) -> str | None:
        return None  # per-test seeding needs the plugin
