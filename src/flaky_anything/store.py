"""SQLite store at <root>/.flaky-anything/runs.db: trials, per-test outcomes, failure signatures."""

import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from types import TracebackType

from pydantic import BaseModel

from flaky_anything.config import TrialConfig
from flaky_anything.errors import FlakyAnythingError
from flaky_anything.runner import STATE_DIR, TrialResult
from flaky_anything.trial_plugin import NodeResult

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE trials (
    trial_id TEXT PRIMARY KEY,
    config_id TEXT NOT NULL,
    config_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    duration REAL NOT NULL,
    status TEXT NOT NULL,
    stderr_tail TEXT NOT NULL,
    collection_errors TEXT NOT NULL
);
CREATE INDEX trials_config ON trials(config_id);
CREATE TABLE signatures (
    id TEXT PRIMARY KEY,
    exc_type TEXT NOT NULL,
    normalized_frames TEXT NOT NULL,
    sample_longrepr TEXT NOT NULL
);
CREATE TABLE outcomes (
    trial_id TEXT NOT NULL REFERENCES trials(trial_id),
    nodeid TEXT NOT NULL,
    outcome TEXT NOT NULL,
    phase TEXT NOT NULL,
    duration REAL NOT NULL,
    longrepr TEXT,
    signature_id TEXT REFERENCES signatures(id),
    PRIMARY KEY (trial_id, nodeid)
);
CREATE INDEX outcomes_nodeid ON outcomes(nodeid);
"""


class Signature(BaseModel):
    id: str
    exc_type: str
    normalized_frames: str
    sample_longrepr: str


class Store:
    def __init__(self, project_root: Path) -> None:
        path = project_root / STATE_DIR / "runs.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            with self.conn:
                self.conn.executescript(SCHEMA)
                self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        elif version != SCHEMA_VERSION:
            self.conn.close()
            raise FlakyAnythingError(
                f"{path} has schema version {version}, expected {SCHEMA_VERSION}",
                hint=f"delete {path} (it only caches past trials) and re-run",
            )

    def __enter__(self) -> "Store":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    def save_trial(
        self, result: TrialResult, signatures: Mapping[str, Signature] | None = None
    ) -> None:
        """Persist a trial. `signatures` maps nodeid -> signature of that test's failure."""
        signatures = signatures or {}
        with self.conn:
            self.conn.execute(
                "INSERT INTO trials VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result.trial_id,
                    result.config.config_id,
                    result.config.canonical_json(),
                    result.started_at.isoformat(),
                    result.duration,
                    result.status,
                    result.stderr_tail,
                    json.dumps(result.collection_errors),
                ),
            )
            for sig in signatures.values():
                self.conn.execute(
                    "INSERT OR IGNORE INTO signatures VALUES (?, ?, ?, ?)",
                    (sig.id, sig.exc_type, sig.normalized_frames, sig.sample_longrepr),
                )
            self.conn.executemany(
                "INSERT INTO outcomes VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        result.trial_id,
                        r.nodeid,
                        r.outcome,
                        r.phase,
                        r.duration,
                        r.longrepr,
                        signatures[r.nodeid].id if r.nodeid in signatures else None,
                    )
                    for r in result.results
                ],
            )

    def load_trial(self, trial_id: str) -> TrialResult:
        row = self.conn.execute(
            "SELECT config_json, started_at, duration, status, stderr_tail, collection_errors "
            "FROM trials WHERE trial_id = ?",
            (trial_id,),
        ).fetchone()
        if row is None:
            raise FlakyAnythingError(f"no trial {trial_id!r} in the store")
        config_json, started_at, duration, status, stderr_tail, collection_errors = row
        outcomes = self.conn.execute(
            "SELECT nodeid, outcome, phase, duration, longrepr FROM outcomes "
            "WHERE trial_id = ? ORDER BY rowid",
            (trial_id,),
        ).fetchall()
        return TrialResult(
            trial_id=trial_id,
            config=TrialConfig.model_validate_json(config_json),
            started_at=datetime.fromisoformat(started_at),
            duration=duration,
            status=status,
            stderr_tail=stderr_tail,
            collection_errors=json.loads(collection_errors),
            results=[
                NodeResult(nodeid=n, outcome=o, phase=p, duration=d, longrepr=lr)
                for n, o, p, d, lr in outcomes
            ],
        )

    def signature_of(self, trial_id: str, nodeid: str) -> Signature | None:
        row = self.conn.execute(
            "SELECT s.id, s.exc_type, s.normalized_frames, s.sample_longrepr FROM outcomes o "
            "JOIN signatures s ON s.id = o.signature_id WHERE o.trial_id = ? AND o.nodeid = ?",
            (trial_id, nodeid),
        ).fetchone()
        if row is None:
            return None
        return Signature(
            id=row[0], exc_type=row[1], normalized_frames=row[2], sample_longrepr=row[3]
        )
