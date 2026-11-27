import os

from corpuslib import cache


def test_lookup_empty_cache():
    """O1 victim: assumes the module-level cache starts empty."""
    assert cache.size() == 0


def test_warm_cache():
    """O1 polluter: fills the cache and never clears it."""
    cache.put("user:1", {"name": "ada"})
    assert cache.get("user:1") == {"name": "ada"}


def test_configure():
    """O2 state-setter: sets an env var other tests silently rely on."""
    os.environ["CORPUS_MODE"] = "fast"
    assert os.environ["CORPUS_MODE"] == "fast"


def test_reads_configured_value():
    """O2 brittle: only passes if test_configure ran earlier in the session."""
    assert os.environ.get("CORPUS_MODE") == "fast"


def test_default_currency():
    """O3 victim: reads a module 'constant' another test mutates."""
    assert cache.default_currency() == "USD"


def test_switch_to_eur():
    """O3 polluter: mutates the shared DEFAULTS dict without restoring it."""
    cache.DEFAULTS["currency"] = "EUR"
    assert cache.default_currency() == "EUR"
