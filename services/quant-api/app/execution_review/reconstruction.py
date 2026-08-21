"""Post-hoc Canonical reconstruction for Execution Review Events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal, Protocol

from sqlalchemy.orm import Session

from app.execution_review.eligibility import (
    ELIGIBLE_RULE_CODE,
    EventContext,
    eligible_event,
    event_context,
)
from app.execution_review.errors import (
    invalid as _invalid,
    persistence_failure as _persistence_failure,
)
from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.market_data_service import (
    DominantContractSegmentSummary,
    MarketDataError,
)


ReconstructionMode = Literal["signal", "full"]
ReconstructionUnavailableReason = Literal[
    "MARKET_HISTORY_NOT_READY",
    "MARKET_IDENTITY_CONFLICT",
    "MARKET_PARTITION_UNAVAILABLE",
]

_RECONSTRUCTION_HISTORY_CODES = frozenset(
    {
        "DOMINANT_CONTEXT_MISSING",
        "TRADING_CALENDAR_MISSING",
        "MAIN_CONTRACT_MAP_MISSING",
        "INSTRUMENT_EXCHANGE_MISSING",
        "TRADING_SESSION_MISSING",
        "PREVIOUS_TRADING_DAY_MISSING",
        "PRODUCT_RETIRED",
    }
)
_RECONSTRUCTION_IDENTITY_CODES = frozenset(
    {"MAIN_CONTRACT_MAP_CONFLICT", "BAR_IDENTITY_CONFLICT"}
)
_RECONSTRUCTION_PARTITION_CODES = frozenset(
    {
        "DATASET_OR_PARTITION_MISSING",
        "QUERY_WINDOW_EMPTY",
        "PARTITION_INTEGRITY_INVALID",
    }
)


class HistoricalMarketData(Protocol):
    def dominant_segment_for_day(
        self,
        symbol: str,
        trading_day: date,
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
class ReconstructionWindow:
    start_trading_day: date
    end_trading_day: date
    bar_end_cutoff: datetime | None


@dataclass(frozen=True, slots=True)
class EventReconstruction:
    status: Literal["READY", "UNAVAILABLE"]
    reason: ReconstructionUnavailableReason | None
    mode: ReconstructionMode
    post_hoc_reconstruction: bool
    event: EventContext
    segment: DominantContractSegmentSummary | None
    window: ReconstructionWindow | None
    bars_5m: tuple[CanonicalBar, ...]
    bars_15m: tuple[CanonicalBar, ...]


class EventReconstructionService:
    """Reconstruct immutable Event context from formal historical bars."""

    def __init__(
        self,
        session: Session,
        *,
        market_data: HistoricalMarketData,
    ) -> None:
        self._session = session
        self._market_data = market_data

    def reconstruct_event(
        self,
        event_id: int,
        *,
        mode: ReconstructionMode = "signal",
    ) -> EventReconstruction:
        """Rebuild immutable Event context from formal historical Canonical bars."""
        if mode not in {"signal", "full"}:
            raise _invalid("RECONSTRUCTION_MODE_INVALID")
        event, _ = eligible_event(self._session, event_id)
        assert event.trading_day is not None
        context = event_context(event, ELIGIBLE_RULE_CODE)
        try:
            segment = self._market_data.dominant_segment_for_day(
                event.symbol,
                event.trading_day,
            )
            if segment.contract != event.contract:
                return self._unavailable_reconstruction(
                    context,
                    mode=mode,
                    reason="MARKET_IDENTITY_CONFLICT",
                )
            if mode == "signal":
                trading_days: tuple[date, ...] = (event.trading_day,)
                cutoff = _utc(event.bar_end)
            else:
                trading_days = tuple(
                    segment.start_trading_day + timedelta(days=offset)
                    for offset in range(
                        (segment.end_trading_day - segment.start_trading_day).days + 1
                    )
                )
                cutoff = None
            bars_by_frequency: dict[BarFrequency, tuple[CanonicalBar, ...]] = {}
            for frequency in (BarFrequency.M5, BarFrequency.M15):
                values = tuple(
                    bar
                    for trading_day in trading_days
                    for bar in self._market_data.contract_bars_for_trading_day(
                        symbol=event.symbol,
                        contract=event.contract,
                        frequency=frequency,
                        trading_day=trading_day,
                    )
                    if cutoff is None or _utc(bar.bar_end) <= cutoff
                )
                bars_by_frequency[frequency] = tuple(
                    sorted(values, key=lambda item: item.bar_end)
                )
        except MarketDataError as exc:
            reason = _public_reconstruction_reason(exc.code)
            if reason is None:
                raise _persistence_failure() from None
            return self._unavailable_reconstruction(
                context,
                mode=mode,
                reason=reason,
            )

        event_frequency = BarFrequency(event.frequency)
        if not any(
            bar.trading_day == event.trading_day
            and _utc(bar.bar_end) == _utc(event.bar_end)
            for bar in bars_by_frequency[event_frequency]
        ):
            return self._unavailable_reconstruction(
                context,
                mode=mode,
                reason="MARKET_HISTORY_NOT_READY",
            )
        return EventReconstruction(
            status="READY",
            reason=None,
            mode=mode,
            post_hoc_reconstruction=True,
            event=context,
            segment=segment,
            window=ReconstructionWindow(
                start_trading_day=(
                    event.trading_day if mode == "signal" else segment.start_trading_day
                ),
                end_trading_day=(
                    event.trading_day if mode == "signal" else segment.end_trading_day
                ),
                bar_end_cutoff=cutoff,
            ),
            bars_5m=bars_by_frequency[BarFrequency.M5],
            bars_15m=bars_by_frequency[BarFrequency.M15],
        )

    @staticmethod
    def _unavailable_reconstruction(
        event: EventContext,
        *,
        mode: ReconstructionMode,
        reason: ReconstructionUnavailableReason,
    ) -> EventReconstruction:
        return EventReconstruction(
            status="UNAVAILABLE",
            reason=reason,
            mode=mode,
            post_hoc_reconstruction=True,
            event=event,
            segment=None,
            window=None,
            bars_5m=(),
            bars_15m=(),
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _public_reconstruction_reason(
    code: str,
) -> ReconstructionUnavailableReason | None:
    if code in _RECONSTRUCTION_HISTORY_CODES:
        return "MARKET_HISTORY_NOT_READY"
    if code in _RECONSTRUCTION_IDENTITY_CODES:
        return "MARKET_IDENTITY_CONFLICT"
    if code in _RECONSTRUCTION_PARTITION_CODES:
        return "MARKET_PARTITION_UNAVAILABLE"
    return None
