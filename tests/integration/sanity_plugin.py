"""Loaded with `-p sanity_plugin` inside corpus subprocesses by test_corpus_sanity.py.

Applies the clock and random seed manually (no flaky_anything code involved):
  SANITY_CLOCK        ISO instant; time travel (ticking) starts right before each test body
  SANITY_RANDOM_SEED  int; random.seed(n) before each test
"""

import os
import random
from collections.abc import Iterator
from datetime import datetime

import pytest
import time_machine


def pytest_runtest_setup(item: pytest.Item) -> None:
    if "SANITY_RANDOM_SEED" in os.environ:
        random.seed(int(os.environ["SANITY_RANDOM_SEED"]))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Iterator[None]:
    if "SANITY_CLOCK" not in os.environ:
        return (yield)
    # Travel as late as possible so slow startup can't tick 23:59:59.5 past midnight early.
    # Pass a timestamp: an aware datetime makes time-machine force the local zone (ignoring TZ).
    instant = datetime.fromisoformat(os.environ["SANITY_CLOCK"]).timestamp()
    with time_machine.travel(instant, tick=True):
        return (yield)
