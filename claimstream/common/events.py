"""Claim event contract shared by producer, processor and API (schema v1)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ClaimType = Literal["collision", "theft", "glass", "liability", "fire"]
Channel = Literal["web", "app", "phone", "agent"]


class ClaimEvent(BaseModel):
    schema_version: Literal[1] = 1
    claim_id: str = Field(min_length=8, max_length=64)
    policy_id: int = Field(gt=0)
    loss_ts: datetime
    reported_ts: datetime
    amount: float = Field(gt=0, lt=5_000_000)
    claim_type: ClaimType
    channel: Channel
    fraud_label: bool | None = None   # only present on synthetic history / simulator events

    @field_validator("loss_ts", "reported_ts")
    @classmethod
    def must_be_tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware (UTC)")
        return v

    @model_validator(mode="after")
    def reported_after_loss(self) -> "ClaimEvent":
        if self.reported_ts < self.loss_ts:
            raise ValueError("reported_ts precedes loss_ts")
        return self
