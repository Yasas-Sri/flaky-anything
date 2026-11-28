"""Static hints: which tests touch a hidden input? Only used to prioritise hunting, never as
evidence — a test is flaky only when trials show it both passing and failing.

AST scan of the test function (direct), plus (indirect) its file's module-level code, the
same-file helpers it calls and the project modules it references, one level deep. Names are
resolved through imports: `from datetime import datetime as dt; dt.now()` is
`datetime.datetime.now`.
"""

import ast
from collections.abc import Callable, Iterable
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

# kind -> qualified names; a use matches the name itself or anything under it ("random" ~ random.x)
CALLS = {
    "clock": (
        "datetime.datetime.now",
        "datetime.datetime.utcnow",
        "datetime.datetime.today",
        "datetime.date.today",
        "time.time",
        "time.time_ns",
        "time.localtime",
        "time.ctime",
    ),
    "random": ("random", "uuid.uuid1", "uuid.uuid4", "secrets", "os.urandom", "numpy.random"),
    "sleep": ("time.sleep", "asyncio.sleep"),
    "threads": ("threading", "concurrent.futures", "multiprocessing"),
    "asyncio": ("asyncio",),
    "network": ("socket", "requests", "httpx", "aiohttp", "urllib.request", "http.client"),
    "env_read": (
        "os.getenv",
        *(f"os.environ.{m}" for m in ("get", "items", "keys", "values", "copy")),
    ),
    "env_write": (
        "os.putenv",
        "os.unsetenv",
        *(f"os.environ.{m}" for m in ("update", "setdefault", "pop", "popitem", "clear")),
    ),
}
_MUTABLE_CALLS = {"dict", "list", "set", "defaultdict", "OrderedDict", "deque", "Counter"}


class Hints(NamedTuple):
    direct: frozenset[str] = frozenset()  # in the test function itself
    indirect: frozenset[str] = frozenset()  # elsewhere in its file / imported project modules

    @property
    def score(self) -> int:
        return 2 * len(self.direct) + len(self.indirect - self.direct)


def _aliases(tree: ast.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
    return out


def _dotted(node: ast.expr, aliases: dict[str, str]) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return ".".join([aliases.get(node.id, node.id), *reversed(parts)])


def _matches(name: str, prefixes: Iterable[str]) -> bool:
    return any(name == p or name.startswith(p + ".") for p in prefixes)


def _scan(nodes: Iterable[ast.AST], aliases: dict[str, str]) -> set[str]:
    found: set[str] = set()
    for root in nodes:
        for node in ast.walk(root):
            if isinstance(node, (ast.Attribute, ast.Name)) and isinstance(node.ctx, ast.Load):
                name = _dotted(node, aliases)
                if name:
                    found |= {kind for kind, names in CALLS.items() if _matches(name, names)}
            if isinstance(node, (ast.Set, ast.SetComp)) or (
                isinstance(node, ast.Call) and _dotted(node.func, aliases) in ("set", "frozenset")
            ):
                found.add("set_order")  # str/bytes sets iterate in PYTHONHASHSEED order
            if isinstance(node, ast.Subscript) and _dotted(node.value, aliases) == "os.environ":
                found.add("env_read" if isinstance(node.ctx, ast.Load) else "env_write")
            if isinstance(node, ast.Global):
                found.add("global_state")
    return found


def _module_globals(tree: ast.Module, aliases: dict[str, str]) -> set[str]:
    for stmt in tree.body:
        value = stmt.value if isinstance(stmt, (ast.Assign, ast.AnnAssign)) else None
        mutable = (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)
        if isinstance(value, mutable) or (
            isinstance(value, ast.Call)
            and (_dotted(value.func, aliases) or "").split(".")[-1] in _MUTABLE_CALLS
        ):
            return {"global_state"}
    return set()


def _project_module(name: str, root: Path) -> Path | None:
    rel = name.replace(".", "/")
    for base in (root, root / "src"):
        for candidate in (base / f"{rel}.py", base / rel / "__init__.py"):
            if candidate.is_file():
                return candidate
    return None


ModuleLookup = Callable[[str], "Path | None"]


def _references(
    node: ast.AST, aliases: dict[str, str], lookup: ModuleLookup
) -> tuple[set[Path], set[str]]:
    """Project module files and bare names (maybe same-file helpers) that `node` uses."""
    modules: set[Path] = set()
    names: set[str] = set()
    for n in ast.walk(node):
        if not (isinstance(n, (ast.Attribute, ast.Name)) and isinstance(n.ctx, ast.Load)):
            continue
        if isinstance(n, ast.Name):
            names.add(n.id)
        parts = (_dotted(n, aliases) or "").split(".")
        for i in range(len(parts), 0, -1):  # longest prefix that is a project module
            path = lookup(".".join(parts[:i]))
            if path is not None:
                modules.add(path)
                break
    # ponytail: root and root/src only; other pythonpath entries, relative imports and
    # fixtures from conftest are not followed
    return modules, names


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None  # collection would already have complained


def _find_test(tree: ast.Module, parts: list[str]) -> ast.AST | None:
    """The def for `Class::...::test` parts (params already stripped)."""
    node: ast.AST = tree
    defs = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for part in parts:
        children = getattr(node, "body", [])
        match = [n for n in children if isinstance(n, defs) and n.name == part]
        if not match:
            return None
        node = match[0]
    return node


def hints_for(project_root: Path, nodeids: Iterable[str]) -> dict[str, Hints]:
    module_hints: dict[Path, set[str]] = {}
    parse = lru_cache(maxsize=None)(_parse)  # caches live for one call: files may change
    lookup: ModuleLookup = lru_cache(maxsize=None)(lambda n: _project_module(n, project_root))

    def whole_module(path: Path) -> set[str]:
        if path not in module_hints:
            tree = parse(path)
            module_hints[path] = set()
            if tree is not None:
                aliases = _aliases(tree)
                module_hints[path] = _scan([tree], aliases) | _module_globals(tree, aliases)
        return module_hints[path]

    out: dict[str, Hints] = {}
    for nodeid in nodeids:
        file, *parts = nodeid.partition("[")[0].split("::")
        tree = parse(project_root / file)
        test = _find_test(tree, parts) if tree is not None else None
        if tree is None or test is None:
            out[nodeid] = Hints()
            continue
        aliases = _aliases(tree)
        defs = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        top_level = [n for n in tree.body if not isinstance(n, defs)]
        helpers = {n.name: n for n in tree.body if isinstance(n, defs)}
        modules, names = _references(test, aliases, lookup)
        called = [helpers[n] for n in names if n in helpers and helpers[n] is not test]
        for helper in called:
            modules |= _references(helper, aliases, lookup)[0]
        indirect = _scan([*top_level, *called], aliases) | _module_globals(tree, aliases)
        for module in modules:
            indirect |= whole_module(module)
        out[nodeid] = Hints(frozenset(_scan([test], aliases)), frozenset(indirect))
    return out
