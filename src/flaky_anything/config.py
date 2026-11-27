"""TrialConfig: the full, replayable description of one trial (see ARCHITECTURE.md)."""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class OrderSpec(_Model):
    """How to order `TrialConfig.nodeids`. `explicit` = exactly as listed there (D13)."""

    mode: Literal["collection", "shuffle", "explicit"] = "collection"
    seed: int | None = None  # shuffle only

    @model_validator(mode="after")
    def _seed_iff_shuffle(self) -> "OrderSpec":
        if (self.mode == "shuffle") != (self.seed is not None):
            raise ValueError("order.seed is required for mode 'shuffle' and only allowed there")
        return self


class ClockSpec(_Model):
    instant: datetime | None = None  # None = real clock; stored normalised to UTC
    tick: bool = True

    @field_validator("instant")
    @classmethod
    def _aware_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        if v.tzinfo is None:
            raise ValueError("clock.instant must be timezone-aware (naive depends on TZ)")
        return v.astimezone(timezone.utc)

    @field_serializer("instant")
    def _iso(self, v: datetime | None) -> str | None:
        # stdlib isoformat, not pydantic's: config_id must not change across pydantic versions
        return None if v is None else v.isoformat()


class TrialConfig(_Model):
    nodeids: list[str] = Field(min_length=1)  # what to run; also the order if order=explicit
    order: OrderSpec = OrderSpec()
    hash_seed: int | None = Field(default=None, ge=0, le=2**32 - 1)  # None = PYTHONHASHSEED unset
    random_seed: int | None = None
    clock: ClockSpec = ClockSpec()
    tz: str | None = None  # IANA name; None = inherit
    timeout_s: float = Field(default=120, gt=0)

    @field_validator("tz")
    @classmethod
    def _known_tz(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                ZoneInfo(v)
            except (ZoneInfoNotFoundError, ValueError) as e:
                raise ValueError(f"unknown time zone {v!r}") from e
        return v

    def canonical_json(self) -> str:
        data: dict[str, Any] = self.model_dump(mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    @property
    def config_id(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()[:16]
