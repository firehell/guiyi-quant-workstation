"""Deterministic DOMINANT_ROLL reconciliation over formal Market facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import AlertEvent
from app.execution_review.models import TradeDecision, TradeEpisode, TradeExecution
from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.market_data_service import (
    DominantContractSegmentSummary,
    MarketDataError,
)


ROLL_REFERENCE_FREQUENCY = BarFrequency.M1


class RollMarketData(Protocol):
    def dominant_segment_for_day(
        self,
        symbol: str,
        trading_day: date,
    ) -> DominantContractSegmentSummary: ...

    def latest_dominant_segment(
        self,
        symbol: str,
    ) -> DominantContractSegmentSummary: ...

    def contract_bars_for_trading_day(
        self,
        *,
        symbol: str,
        contract: str,
        frequency: BarFrequency,
        trading_day: date,
    ) -> tuple[CanonicalBar, ...]: ...


@dataclass(frozen=True, slots=True)
class RollReconcileResult:
    status: str
    symbol: str
    episode_id: int | None = None
    reason: str | None = None


class ExecutionReviewRollReconciler:
    """Close OPEN Episodes only from uniquely confirmed rank1 and M1 facts."""

    def __init__(self, session: Session, *, market_data: RollMarketData) -> None:
        self._session = session
        self._market_data = market_data

    def reconcile_symbol(self, symbol: str) -> RollReconcileResult:
        normalized_symbol = symbol.strip().lower()
        try:
            episode = self._session.scalar(
                select(TradeEpisode)
                .where(
                    TradeEpisode.symbol == normalized_symbol,
                    TradeEpisode.closed_at.is_(None),
                )
                .with_for_update()
            )
            if episode is None:
                self._session.rollback()
                return RollReconcileResult("NOOP", normalized_symbol)
            episode_id = episode.id

            lineage = self._session.execute(
                select(TradeDecision, AlertEvent)
                .join(AlertEvent, AlertEvent.id == TradeDecision.alert_event_id)
                .where(TradeDecision.id == episode.origin_decision_id)
            ).one_or_none()
            timeline = tuple(
                self._session.scalars(
                    select(TradeExecution)
                    .where(TradeExecution.episode_id == episode.id)
                    .order_by(TradeExecution.sequence_no)
                    .with_for_update()
                )
            )
            if lineage is None:
                return self._required(normalized_symbol, episode_id, "LINEAGE_INVALID")
            decision, event = lineage
            if not self._valid_lineage(episode, decision, event, timeline):
                return self._required(normalized_symbol, episode_id, "LINEAGE_INVALID")
            assert event.trading_day is not None

            try:
                old_segment = self._market_data.dominant_segment_for_day(
                    event.symbol,
                    event.trading_day,
                )
                if old_segment.contract != episode.contract:
                    return self._required(
                        normalized_symbol,
                        episode_id,
                        "HISTORICAL_IDENTITY_CONFLICT",
                    )
                current_segment = self._market_data.latest_dominant_segment(
                    normalized_symbol
                )
                if current_segment.contract == episode.contract:
                    self._session.rollback()
                    return RollReconcileResult(
                        "NOOP",
                        normalized_symbol,
                        episode_id,
                    )
                reference_bars = self._market_data.contract_bars_for_trading_day(
                    symbol=episode.symbol,
                    contract=episode.contract,
                    frequency=ROLL_REFERENCE_FREQUENCY,
                    trading_day=old_segment.end_trading_day,
                )
            except MarketDataError as exc:
                return self._required(
                    normalized_symbol,
                    episode_id,
                    exc.code,
                )
            if not reference_bars:
                return self._required(
                    normalized_symbol,
                    episode_id,
                    "REFERENCE_BAR_MISSING",
                )
            reference = max(reference_bars, key=lambda bar: bar.bar_end)
            latest_real_execution_at = max(row.executed_at for row in timeline)
            if (
                _utc(reference.bar_end) < _utc(episode.opened_at)
                or _utc(reference.bar_end) < _utc(latest_real_execution_at)
            ):
                return self._required(
                    normalized_symbol,
                    episode_id,
                    "REFERENCE_BEFORE_REAL_EXECUTION",
                )

            episode.close_reason = "DOMINANT_ROLL"
            episode.closed_at = reference.bar_end
            episode.roll_reference_exit_price = reference.close
            episode.roll_reference_bar_end = reference.bar_end
            self._session.commit()
            return RollReconcileResult(
                "DOMINANT_ROLL",
                normalized_symbol,
                episode_id,
            )
        except Exception:
            self._session.rollback()
            raise

    def reconcile_open_episodes(self) -> tuple[RollReconcileResult, ...]:
        symbols = tuple(
            self._session.scalars(
                select(TradeEpisode.symbol)
                .where(TradeEpisode.closed_at.is_(None))
                .distinct()
                .order_by(TradeEpisode.symbol)
            )
        )
        self._session.rollback()
        return tuple(self.reconcile_symbol(symbol) for symbol in symbols)

    def _required(
        self,
        symbol: str,
        episode_id: int,
        reason: str,
    ) -> RollReconcileResult:
        self._session.rollback()
        return RollReconcileResult(
            "ROLL_RECONCILIATION_REQUIRED",
            symbol,
            episode_id,
            reason,
        )

    @staticmethod
    def _valid_lineage(
        episode: TradeEpisode,
        decision: TradeDecision,
        event: AlertEvent,
        timeline: tuple[TradeExecution, ...],
    ) -> bool:
        expected_direction = (
            "LONG"
            if tuple(event.result_codes or ()) == ("buy",)
            else "SHORT"
            if tuple(event.result_codes or ()) == ("sell",)
            else None
        )
        return bool(
            decision.disposition == "EXECUTED"
            and event.trading_day is not None
            and event.symbol == episode.symbol
            and event.contract == episode.contract
            and expected_direction == episode.direction
            and timeline
            and tuple(row.sequence_no for row in timeline)
            == tuple(range(1, len(timeline) + 1))
            and timeline[0].execution_type == "OPEN"
            and timeline[0].trigger_decision_id == episode.origin_decision_id
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
