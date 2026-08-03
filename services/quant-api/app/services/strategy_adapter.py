"""Read-only strategy adapter contract for observation candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from app.services.observation_plans import ObservationPlan


@dataclass(frozen=True)
class StrategyContext:
    plan: ObservationPlan
    market_snapshot: object
    detected_at: datetime


@dataclass(frozen=True)
class SignalCandidate:
    observation_key: str
    direction: str
    detected_at: datetime
    actual_contract: str
    period: str
    strategy_code: str
    strategy_version: str
    policy_id: str
    native_candidate: object


@dataclass(frozen=True)
class StrategyEvaluation:
    candidates: tuple[SignalCandidate, ...]
    blocked: tuple[Any, ...]
    snapshot_sha256: str
    evaluated_at: datetime
    writes_enabled: bool = False
    signal_event_enabled: bool = False
    notification_enabled: bool = False


class StrategyAdapter(Protocol):
    def evaluate(self, context: StrategyContext) -> StrategyEvaluation: ...
