from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import random
from types import MappingProxyType

from app.market_data.actual_dominant_research import ActualDominantResearchSeries
from app.market_data.aggregation import SessionWindow, aggregate_bucket
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesResult,
    ResolvedContractSegment,
)
from app.market_data.subing_strategy.direction_context import (
    SubingStrategyDirectionContext,
)
from app.market_data.subing_strategy.contracts import (
    SubingStrategyAction,
    SubingStrategyActionKind,
    SubingStrategyFillBasis,
    subing_strategy_action_id,
    subing_strategy_episode_id,
    SubingStrategyDirection,
)
from app.market_data.subing_lifecycle import ConfirmationSource


STRATEGY_ID = "subing_strategy_v1"
FORMULA_VERSION = "subing_strategy_15m_v1"
SEGMENT_START = date(2026, 1, 5)


@dataclass(frozen=True, slots=True)
class RecordedStrategyStream:
    bars_1m: tuple[CanonicalBar, ...]
    bars_5m: tuple[CanonicalBar, ...]
    bars_15m: tuple[CanonicalBar, ...]
    sessions: tuple[SessionWindow, ...]
    direction: SubingStrategyDirection


def recorded_strategy_stream(
    seed: int,
    direction: SubingStrategyDirection,
) -> RecordedStrategyStream:
    """Deterministic complete facts that exercise real Factor/Lifecycle paths."""

    trading_day = date(2026, 8, 3)
    session_start = datetime(2026, 8, 3, 0, 0, tzinfo=UTC)
    randomizer = random.Random(seed)
    price = Decimal("100")
    bars_5m: list[CanonicalBar] = []
    for index in range(180):
        delta = Decimal(str(randomizer.choice((-3, -2, -1, -0.5, 0, 0.5, 1, 2, 3))))
        close = max(Decimal("10"), price + delta)
        high = max(price, close) + Decimal(str(randomizer.choice((0.5, 1, 2))))
        low = min(price, close) - Decimal(str(randomizer.choice((0.5, 1, 2))))
        bars_5m.append(
            CanonicalBar(
                bar_end=session_start + timedelta(minutes=5 * (index + 1)),
                trading_day=trading_day,
                open=price,
                high=high,
                low=low,
                close=close,
                volume=Decimal(str(randomizer.choice((10, 20, 30, 60, 100)))),
                turnover=None,
                open_interest=Decimal("100"),
            )
        )
        price = close
    completed_5m = tuple(bars_5m)
    bars_15m = tuple(
        aggregate_bucket(
            completed_5m[index : index + 3],
            bucket_end=completed_5m[index + 2].bar_end,
        )
        for index in range(0, len(completed_5m), 3)
    )
    bars_1m = tuple(
        CanonicalBar(
            bar_end=bar_5m.bar_end - timedelta(minutes=5 - minute),
            trading_day=trading_day,
            open=bar_5m.open,
            high=(bar_5m.high if minute == 1 else max(bar_5m.open, bar_5m.close)),
            low=(bar_5m.low if minute == 1 else min(bar_5m.open, bar_5m.close)),
            close=bar_5m.close if minute == 5 else bar_5m.open,
            volume=bar_5m.volume if minute == 5 else Decimal("0"),
            turnover=None,
            open_interest=bar_5m.open_interest,
        )
        for bar_5m in completed_5m
        for minute in range(1, 6)
    )
    return RecordedStrategyStream(
        bars_1m=bars_1m,
        bars_5m=completed_5m,
        bars_15m=bars_15m,
        sessions=(
            SessionWindow(
                start=session_start,
                end=completed_5m[-1].bar_end,
            ),
        ),
        direction=direction,
    )


def aware_dt(hour: int, minute: int) -> datetime:
    return datetime(2026, 1, 5, hour, minute, tzinfo=UTC)


def action_fixture(
    *,
    reference_price: Decimal = Decimal("100"),
    contract: str = "JM2605",
    kind: SubingStrategyActionKind = SubingStrategyActionKind.CLOSE_LONG,
    decision_at: datetime = aware_dt(10, 0),
    effective_open_at: datetime | None = aware_dt(10, 15),
    effective_bar_end: datetime = aware_dt(10, 30),
    fill_basis: SubingStrategyFillBasis = SubingStrategyFillBasis.NEXT_BAR_OPEN,
    episode_id: str | None = None,
) -> SubingStrategyAction:
    identity = {
        "strategy_id": STRATEGY_ID,
        "formula_version": FORMULA_VERSION,
        "symbol": "JM",
        "contract": contract,
        "segment_start_trading_day": SEGMENT_START.isoformat(),
        "opportunity_id": "subing-opportunity:test",
        "kind": kind.value,
        "decision_at": decision_at.isoformat(),
        "effective_bar_end": effective_bar_end.isoformat(),
        "fill_basis": fill_basis.value,
    }
    is_open = kind in {
        SubingStrategyActionKind.OPEN_LONG,
        SubingStrategyActionKind.OPEN_SHORT,
    }
    return SubingStrategyAction(
        action_id=subing_strategy_action_id(identity),
        episode_id=(
            episode_id
            or (
                subing_strategy_episode_id(identity)
                if is_open
                else "subing-episode:test"
            )
        ),
        strategy_id=STRATEGY_ID,
        formula_version=FORMULA_VERSION,
        kind=kind,
        symbol="JM",
        contract=contract,
        trading_day=SEGMENT_START,
        segment_start_trading_day=SEGMENT_START,
        opportunity_id="subing-opportunity:test",
        decision_at=decision_at,
        effective_open_at=effective_open_at,
        effective_bar_end=effective_bar_end,
        reference_price=reference_price,
        fill_basis=fill_basis,
        confirmation_source=(ConfirmationSource.FORMAL_V1 if is_open else None),
        reason_codes=(() if is_open else ("EMA21_BREACH_LONG",)),
        direction_context_source_day=(SEGMENT_START if is_open else None),
        direction_context_target_day=(SEGMENT_START if is_open else None),
        bound_reference_pivot=None,
    )


class FakeSegmentLoader:
    def __init__(
        self,
        result: ActualDominantResearchSeries | Exception,
    ) -> None:
        self.result = result
        self.requests: list[tuple[str, tuple[BarFrequency, ...], date, date]] = []
        self.session_requests: list[tuple[str, tuple[date, ...]]] = []

    def load(
        self,
        *,
        symbol: str,
        frequencies: Sequence[BarFrequency],
        since: date,
        through: date,
    ) -> ActualDominantResearchSeries:
        self.requests.append((symbol, tuple(frequencies), since, through))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def sessions(
        self,
        *,
        symbol: str,
        trading_days: Sequence[date],
    ) -> Mapping[date, tuple[SessionWindow, ...]]:
        days = tuple(trading_days)
        self.session_requests.append((symbol, days))
        if isinstance(self.result, Exception):
            raise self.result
        bars = self.result.results[BarFrequency.M15].bars
        return MappingProxyType(
            {
                day: (
                    SessionWindow(
                        start=min(bar.bar_end for bar in bars if bar.trading_day == day)
                        - timedelta(minutes=15),
                        end=max(bar.bar_end for bar in bars if bar.trading_day == day),
                    ),
                )
                for day in days
            }
        )


class FakeDirectionContextResolver:
    def __init__(
        self,
        contexts: Mapping[date, SubingStrategyDirectionContext],
    ) -> None:
        self.contexts = contexts
        self.requests: list[tuple[str, tuple[date, ...]]] = []

    def resolve(
        self,
        symbol: str,
        target_days: Sequence[date],
    ) -> Mapping[date, SubingStrategyDirectionContext]:
        days = tuple(target_days)
        self.requests.append((symbol, days))
        return MappingProxyType({day: self.contexts[day] for day in days})


def loaded_series(
    *,
    segments: tuple[ResolvedContractSegment, ...],
    bars_1m: tuple[CanonicalBar, ...] | None = None,
    bars_5m: tuple[CanonicalBar, ...],
    bars_15m: tuple[CanonicalBar, ...],
) -> ActualDominantResearchSeries:
    def result(
        frequency: BarFrequency,
        bars: tuple[CanonicalBar, ...],
    ) -> MarketSeriesResult:
        return MarketSeriesResult(
            request_identity={
                "series_kind": "actual_dominant",
                "symbol": "jm",
                "frequency": frequency.value,
            },
            bars=bars,
            coverage=((bars[0].bar_end, bars[-1].bar_end) if bars else None),
            resolved_contract_segments=segments,
        )

    return ActualDominantResearchSeries(
        results=MappingProxyType(
            {
                BarFrequency.M1: result(
                    BarFrequency.M1,
                    bars_5m if bars_1m is None else bars_1m,
                ),
                BarFrequency.M5: result(BarFrequency.M5, bars_5m),
                BarFrequency.M15: result(BarFrequency.M15, bars_15m),
            }
        ),
        segments=segments,
    )
