"""Module-level state: the source of order-dependent tests."""

_CACHE: dict[str, object] = {}
DEFAULTS: dict[str, str] = {"currency": "USD"}


def put(key: str, value: object) -> None:
    _CACHE[key] = value


def get(key: str) -> object:
    return _CACHE.get(key)


def size() -> int:
    return len(_CACHE)


def clear() -> None:
    _CACHE.clear()


def default_currency() -> str:
    return DEFAULTS["currency"]
