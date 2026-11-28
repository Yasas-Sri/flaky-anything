"""Failure signatures: normalise a pytest longrepr (--tb=long) and hash it.

Two failures share a signature when they have the same exception type, the same frames (file +
failing source line; line numbers dropped so edits elsewhere don't split them) and the same
message once memory addresses, temp paths and numbers are masked.
"""

import hashlib
import re
from collections.abc import Hashable, Iterable
from typing import TypeVar

from flaky_anything.runner import TrialResult
from flaky_anything.store import Signature
from flaky_anything.trial_plugin import redact_env

SAMPLE_CHARS = 4000
_LOCATION = re.compile(r"^(?P<path>\S.*?):(?P<line>\d+):(?: (?P<rest>.*))?$")
_TMP = re.compile(
    r"(?:/private)?/(?:tmp|var/folders)/\S*"  # posix / macOS temp dirs
    r"|\S*pytest-of-[^\s/\\]+[/\\]pytest-\d+\S*"  # pytest's tmp_path roots
    r"|[A-Za-z]:\\\S*\\Temp\\\S*"  # Windows %TEMP%
)
_ADDR = re.compile(r"0x[0-9a-fA-F]+")
_NUM = re.compile(r"\d+(?:\.\d+)?")
_WS = re.compile(r"\s+")
# Pseudo exception types for outcomes that have no traceback.
NO_TRACEBACK = {"timeout": "Timeout", "error": "Crash"}

K = TypeVar("K", bound=Hashable)


def _norm_path(path: str) -> str:
    path = path.replace("\\", "/")
    path = re.sub(r"^.*/site-packages/", "site-packages/", path)
    return re.sub(r"python\d+\.\d+", "pythonX.Y", path)


def _norm_text(text: str) -> str:
    text = redact_env(text)  # already done in the plugin; also for longreprs from elsewhere
    text = _TMP.sub("<TMP>", text)
    text = _ADDR.sub("0xADDR", text)
    text = _NUM.sub("N", text)
    return _WS.sub(" ", text).strip()


def _make(exc_type: str, frames: list[str], message: list[str], sample: str) -> Signature:
    key = "\n".join([exc_type, *frames, "--", *message])
    return Signature(
        id=hashlib.sha256(key.encode()).hexdigest()[:16],
        exc_type=exc_type,
        normalized_frames="\n".join(frames),
        sample_longrepr=redact_env(sample)[:SAMPLE_CHARS],
    )


def signature(longrepr: str) -> Signature:
    exc_type, frames, message = "unknown", [], []
    failing_line = ""
    for line in longrepr.splitlines():
        if line.startswith(">"):
            failing_line = line[1:].strip()
        elif line.startswith("E "):
            message.append(_norm_text(line[1:]))
        elif m := _LOCATION.match(line):
            frames.append(f"{_norm_path(m['path'])}: {failing_line}")
            failing_line = ""
            if m["rest"]:
                exc_type = m["rest"].strip()
    return _make(exc_type, frames, [m for m in message if m], longrepr)


def signatures_for(result: TrialResult) -> dict[str, Signature]:
    """Signature per non-passing, non-skipped test in a trial (input for Store.save_trial)."""
    sigs = {}
    for r in result.results:
        if r.outcome in NO_TRACEBACK:
            sigs[r.nodeid] = _make(NO_TRACEBACK[r.outcome], [], [], result.stderr_tail)
        elif r.outcome == "failed":
            sigs[r.nodeid] = signature(r.longrepr or "")
    return sigs


def group(failures: Iterable[tuple[K, Signature]]) -> dict[str, list[K]]:
    """Group failure keys (e.g. (trial_id, nodeid)) by signature id, keeping input order."""
    groups: dict[str, list[K]] = {}
    for key, sig in failures:
        groups.setdefault(sig.id, []).append(key)
    return groups
