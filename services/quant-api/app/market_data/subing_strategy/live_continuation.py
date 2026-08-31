"""Typed Live continuation identity contract shared by Current and Runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import Enum

from .direction_context import SubingStrategyDirectionContext
from .machine import SubingStrategySourceIdentity
from ..domain import BarFrequency, CanonicalBar


class SubingLiveContinuationKind(str, Enum):
    CONTINUE_SAME_SEGMENT = "CONTINUE_SAME_SEGMENT"
    LIVE_CONTRACT_AUTHORITY_PENDING = "LIVE_CONTRACT_AUTHORITY_PENDING"
    STALE_OR_IDENTITY_INVALID = "STALE_OR_IDENTITY_INVALID"


@dataclass(frozen=True, slots=True)
class SubingLiveContinuationDecision:
    kind: SubingLiveContinuationKind
    machine_identity: SubingStrategySourceIdentity
    incoming_trading_day: date
    market_trading_day: date | None
    frozen_live_contract: str | None
    live_eligible: bool
    live_available: bool
    direction_context: SubingStrategyDirectionContext | None


@dataclass(frozen=True, slots=True)
class SubingLiveCompletedBars:
    decision: SubingLiveContinuationDecision
    bars: Mapping[BarFrequency, tuple[CanonicalBar, ...]]
