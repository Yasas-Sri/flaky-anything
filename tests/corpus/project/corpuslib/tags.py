"""Tags are a set; sets of str iterate in PYTHONHASHSEED-dependent order."""


def tags_for(kind: str) -> set[str]:
    return {"alpha", "beta"} if kind == "release" else {"misc"}


def render(tags: set[str]) -> str:
    return ", ".join(tags)


def render_sorted(tags: set[str]) -> str:
    return ", ".join(sorted(tags))
