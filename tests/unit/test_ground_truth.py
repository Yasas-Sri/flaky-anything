"""Static consistency of tests/corpus/ground_truth.toml against the corpus source."""

import ast
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

CORPUS = Path(__file__).parents[1] / "corpus"
PROJECT = CORPUS / "project"
GT = tomllib.loads((CORPUS / "ground_truth.toml").read_text())

CATEGORIES = {"order:victim", "order:brittle", "time:month_end", "time:midnight", "tz"}
CATEGORIES |= {"seed:hash", "seed:random", "combined", "uncontrolled"}
KNOBS = {"order", "hash_seed", "random_seed", "clock", "tz"}


def corpus_nodeids() -> set[str]:
    ids = set()
    for f in (PROJECT / "tests").glob("test_*.py"):
        for node in ast.parse(f.read_text()).body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                ids.add(f"{f.relative_to(PROJECT).as_posix()}::{node.name}")
    return ids


def test_every_corpus_test_is_classified_exactly_once() -> None:
    flaky = [c["nodeid"] for c in GT["cases"].values()]
    stable = GT["stable"]["nodeids"]
    assert sorted(flaky + stable) == sorted(corpus_nodeids())


def test_cases_are_well_formed() -> None:
    known = corpus_nodeids()
    for case_id, c in GT["cases"].items():
        assert c["category"] in CATEGORIES, case_id
        assert set(c["necessary_knobs"]) <= KNOBS, case_id
        assert set(c.get("trigger", {})) <= {"order", "clock", "tz"}, case_id
        for key in ("polluter", "state_setter"):
            if key in c:
                assert c[key] in known, case_id
        for nodeid in c.get("trigger", {}).get("order", []):
            assert nodeid in known, case_id


def test_trigger_knobs_match_necessary_knobs() -> None:
    for case_id, c in GT["cases"].items():
        assert set(c.get("trigger", {})) <= set(c["necessary_knobs"]), case_id
