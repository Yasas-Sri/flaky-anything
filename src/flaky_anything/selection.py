"""Which tests to hunt: collect node ids (fresh subprocess) and read CI JUnit history."""

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import NamedTuple

from flaky_anything.errors import FlakyAnythingError
from flaky_anything.runner import SCRUBBED_ENV, STDERR_TAIL

COLLECT_ARGS = ["--collect-only", "-q", "-p", "no:randomly", "-p", "no:cacheprovider"]


def collect(
    project_root: Path, paths: Sequence[str] = (), python: str = sys.executable
) -> list[str]:
    """Node ids pytest collects for `paths` (dirs, files or node ids; none = project testpaths).

    Runs in a subprocess like every trial (hard rule 2): collection imports the project.
    """
    env = {k: v for k, v in os.environ.items() if k not in SCRUBBED_ENV}
    proc = subprocess.run(
        [python, "-m", "pytest", *COLLECT_ARGS, *paths],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    output = proc.stdout + proc.stderr
    if proc.returncode == 5:
        raise FlakyAnythingError(
            f"pytest collected no tests in {project_root} for {list(paths) or 'testpaths'}",
            hint="pass test paths or node ids, or run from the project root",
        )
    if proc.returncode != 0:
        raise FlakyAnythingError(
            f"pytest collection failed (exit {proc.returncode}):\n{output[-STDERR_TAIL:]}",
            hint="fix the collection errors, or pass only paths that collect cleanly",
        )
    lines = proc.stdout.split("\n\n", 1)[0].splitlines()  # node ids end at the first blank line
    return [line for line in lines if "::" in line]


class History(NamedTuple):
    passed: int
    failed: int

    @property
    def mixed(self) -> bool:
        return self.passed > 0 and self.failed > 0


def junit_key(nodeid: str) -> tuple[str, str]:
    """(classname, name) pytest's junitxml writes for `nodeid` (mirrors mangle_test_address)."""
    path, bracket, params = nodeid.partition("[")  # params may contain "::" or "/"
    names = path.split("::")
    names[0] = names[0].replace("/", ".").removesuffix(".py")
    names[-1] += bracket + params
    return ".".join(names[:-1]), names[-1]


def junit_history(xml_files: Iterable[Path], collected: Sequence[str]) -> dict[str, History]:
    """Pass/fail counts per collected node id across CI JUnit reports, most suspicious first:
    mixed outcomes, then by failures. Skips are ignored; cases not collected now are dropped.
    """
    by_key = {junit_key(n): n for n in collected}
    counts: dict[str, list[int]] = {}
    for xml_file in xml_files:
        try:
            root = ET.parse(xml_file).getroot()
        except (ET.ParseError, OSError) as e:
            raise FlakyAnythingError(f"cannot read JUnit XML {xml_file}: {e}") from e
        for case in root.iter("testcase"):
            nodeid = by_key.get((case.get("classname", ""), case.get("name", "")))
            if nodeid is None or case.find("skipped") is not None:
                continue
            failed = case.find("failure") is not None or case.find("error") is not None
            counts.setdefault(nodeid, [0, 0])[failed] += 1
    history = {n: History(passed, failed) for n, (passed, failed) in counts.items()}
    return dict(sorted(history.items(), key=lambda kv: (not kv[1].mixed, -kv[1].failed)))
