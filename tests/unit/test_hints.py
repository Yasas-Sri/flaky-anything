import sys
import textwrap
from pathlib import Path

from flaky_anything.hints import Hints, hints_for

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

CORPUS = Path(__file__).parents[1] / "corpus"


def project(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, src in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(textwrap.dedent(src))
    return tmp_path


def test_direct_hints_resolve_aliases(tmp_path: Path) -> None:
    root = project(
        tmp_path,
        {
            "tests/test_x.py": """
            import os, random as rnd, threading
            from datetime import datetime as dt
            from time import sleep

            def test_clock(): assert dt.now()
            def test_random(): rnd.choice([1, 2])
            def test_sleep(): sleep(0)
            def test_env(): os.environ["A"] = "1"
            def test_env_del(): del os.environ["A"]
            def test_env_update(): os.environ.update(A="1")
            def test_set(): ", ".join({"a", "b"})
            def test_threads(): threading.Thread(target=print)
            def test_plain(): assert 1 + 1 == 2
            def test_env_read(): assert os.environ.get("A") is None
            class TestC:
                def test_m(self): rnd.random()
            """,
        },
    )
    names = [
        "clock", "random", "sleep", "env", "env_del", "env_update", "set", "threads", "plain",
        "env_read",
    ]  # fmt: skip
    ids = [f"tests/test_x.py::test_{n}" for n in names] + ["tests/test_x.py::TestC::test_m[1]"]
    direct = {n.split("::")[-1]: h.direct for n, h in hints_for(root, ids).items()}
    assert direct == {
        "test_clock": {"clock"},
        "test_random": {"random"},
        "test_sleep": {"sleep"},
        "test_env": {"env_write"},
        "test_env_del": {"env_write"},
        "test_env_update": {"env_write"},
        "test_set": {"set_order"},
        "test_threads": {"threads"},
        "test_plain": set(),
        "test_env_read": {"env_read"},
        "test_m[1]": {"random"},
    }


def test_indirect_hints_come_from_file_and_imported_project_modules(tmp_path: Path) -> None:
    root = project(
        tmp_path,
        {
            "src/pkg/__init__.py": "",
            "src/pkg/state.py": "_CACHE: dict[str, int] = {}\ndef get(k): return _CACHE.get(k)\n",
            "src/pkg/net.py": "import socket\ndef ping(): socket.socket()\n",
            "src/pkg/pure.py": "def add(a, b): return a + b\n",
            "tests/test_a.py": """
            import random
            import requests
            from pkg import state, pure
            import pkg.net
            SEED = random.random()  # module level: affects every test in the file
            def _helper(): return pkg.net.ping()
            def test_a(): assert state.get("k") is None and _helper() is None
            def test_other(): requests.get("http://example.invalid")  # not called by test_a
            """,
            "tests/test_pure.py": """
            from pkg import pure
            def test_p(): assert pure.add(1, 2) == 3
            """,
        },
    )
    h = hints_for(root, ["tests/test_a.py::test_a", "tests/test_pure.py::test_p"])
    assert h["tests/test_a.py::test_a"] == Hints(
        direct=frozenset(), indirect=frozenset({"global_state", "network", "random"})
    )
    assert h["tests/test_pure.py::test_p"] == Hints()


def test_unparseable_or_missing_files_give_no_hints(tmp_path: Path) -> None:
    root = project(tmp_path, {"tests/test_bad.py": "def test_x(:\n"})
    assert hints_for(root, ["tests/test_bad.py::test_x", "tests/nope.py::test_y"]) == {
        "tests/test_bad.py::test_x": Hints(),
        "tests/nope.py::test_y": Hints(),
    }


def test_score_weights_direct_hints_double() -> None:
    assert Hints(frozenset({"clock"}), frozenset({"clock", "random"})).score == 3


# Category -> hint kinds that should point at it (a sanity check that hints are relevant).
EXPECTED = {
    "order": {"global_state", "env_write", "env_read"},
    "time": {"clock"},
    "combined": {"clock"},
    "tz": {"clock"},
    "seed:random": {"random"},
    "seed:hash": {"set_order"},
    "uncontrolled": {"random"},
}


def test_every_corpus_case_gets_a_relevant_hint() -> None:
    cases = tomllib.loads((CORPUS / "ground_truth.toml").read_text())["cases"]
    hints = hints_for(CORPUS / "project", [c["nodeid"] for c in cases.values()])
    for case in cases.values():
        h = hints[case["nodeid"]]
        expected = EXPECTED.get(case["category"]) or EXPECTED[case["category"].split(":")[0]]
        assert expected & (h.direct | h.indirect), (case["nodeid"], h)
