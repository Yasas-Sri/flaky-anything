"""Random ids and sampling."""

import random
import secrets


def pick_two(pool: list[str]) -> tuple[str, str]:
    """Two reviewers. BUG: may pick the same one twice."""
    return random.choice(pool), random.choice(pool)


def sample_distinct(pool: list[str], k: int) -> list[str]:
    return random.sample(pool, k)


def backoff_jitter_ms() -> int:
    """BUG: can return 0. Uses os.urandom via secrets, so no seed controls it."""
    return secrets.randbelow(5)
