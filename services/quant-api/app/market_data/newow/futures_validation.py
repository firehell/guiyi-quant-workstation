"""Pure adapter from authoritative actual-dominant results to Newow research bars."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from guiyi_quant.newow import NewowResearchBar, NewowStrategyReplaySegment

from app.market_data.domain import (
    BarFrequency,
    MarketSeriesResult,
    MarketSeriesPageResult,
    ResolvedContractSegment,
    normalize_contract_for_symbol,
)


class NewowFuturesSeriesError(ValueError):
    def __init__(self) -> None:
        self.code = "NEWOW_FUTURES_SERIES_INVALID"
        super().__init__(self.code)


def _integral(value: Decimal | None) -> int | None:
    if value is None:
        return None
    if value != value.to_integral_value():
        raise NewowFuturesSeriesError
    return int(value)


def _valid_segment(segment: ResolvedContractSegment, product: str) -> bool:
    return (
        bool(segment.contract)
        and segment.contract == segment.contract.upper()
        and normalize_contract_for_symbol(product, segment.contract)
        == segment.contract
        and type(segment.start_trading_day) is date
        and type(segment.end_trading_day) is date
        and segment.start_trading_day <= segment.end_trading_day
    )


def build_newow_research_bars(
    result: MarketSeriesResult,
    *,
    authoritative_segments: tuple[ResolvedContractSegment, ...],
    expected_product: str,
    expected_frequency: BarFrequency,
) -> tuple[NewowResearchBar, ...]:
    """Adapt one frequency using loader-restored, query-invariant owners."""

    if (
        not expected_product
        or expected_product != expected_product.lower()
        or not isinstance(expected_frequency, BarFrequency)
        or result.request_identity.get("series_kind") != "actual_dominant"
        or result.request_identity.get("symbol") != expected_product
        or result.request_identity.get("frequency") != expected_frequency.value
        or result.request_identity.get("contract") is not None
        or not result.bars
        or not result.resolved_contract_segments
        or not authoritative_segments
        or result.coverage
        != (result.bars[0].bar_end, result.bars[-1].bar_end)
        or result.requested_trading_day_window is None
        or any(
            not _valid_segment(item, expected_product)
            for item in result.resolved_contract_segments
        )
        or any(
            not _valid_segment(item, expected_product)
            for item in authoritative_segments
        )
    ):
        raise NewowFuturesSeriesError

    since, through = result.requested_trading_day_window
    if (
        type(since) is not date
        or type(through) is not date
        or since > through
        or any(not since <= bar.trading_day <= through for bar in result.bars)
        or any(
            current.bar_end <= previous.bar_end
            for previous, current in zip(result.bars, result.bars[1:], strict=False)
        )
        or any(
            current.start_trading_day <= previous.end_trading_day
            for previous, current in zip(
                result.resolved_contract_segments,
                result.resolved_contract_segments[1:],
                strict=False,
            )
        )
        or any(
            current.start_trading_day <= previous.end_trading_day
            for previous, current in zip(
                authoritative_segments,
                authoritative_segments[1:],
                strict=False,
            )
        )
    ):
        raise NewowFuturesSeriesError

    built: list[NewowResearchBar] = []
    seen_sources: set[str] = set()
    for bar in result.bars:
        raw_owners = tuple(
            segment
            for segment in result.resolved_contract_segments
            if segment.start_trading_day
            <= bar.trading_day
            <= segment.end_trading_day
        )
        owners = tuple(
            segment
            for segment in authoritative_segments
            if segment.start_trading_day
            <= bar.trading_day
            <= segment.end_trading_day
        )
        if (
            len(raw_owners) != 1
            or len(owners) != 1
            or raw_owners[0].contract != owners[0].contract
        ):
            raise NewowFuturesSeriesError
        owner = owners[0]
        source_identity = (
            f"canonical:actual_dominant:{expected_product}:"
            f"{expected_frequency.value}:{owner.contract}:"
            f"{bar.trading_day.isoformat()}:{bar.bar_end.isoformat()}"
        )
        if source_identity in seen_sources:
            raise NewowFuturesSeriesError
        seen_sources.add(source_identity)
        built.append(
            NewowResearchBar(
                product=expected_product,
                physical_contract=owner.contract,
                segment_id=(
                    f"{expected_product}:{owner.contract}:"
                    f"{owner.start_trading_day.isoformat()}:"
                    f"{owner.end_trading_day.isoformat()}"
                ),
                trading_day=bar.trading_day,
                bar_end=bar.bar_end,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=_integral(bar.volume) or 0,
                open_interest=_integral(bar.open_interest),
                source_identity=source_identity,
                observation_eligible=True,
                completed=True,
                frequency=expected_frequency.value,
                turnover=bar.turnover,
            )
        )
    return tuple(built)


def _same_ohlcv(left: object, right: object) -> bool:
    return all(
        getattr(left, field) == getattr(right, field)
        for field in (
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover",
            "open_interest",
        )
    )


def build_newow_strategy_replay_segments(
    actual_bars: tuple[NewowResearchBar, ...],
    *,
    authoritative_segments: tuple[ResolvedContractSegment, ...],
    physical_prefix_pages: tuple[MarketSeriesPageResult, ...],
    expected_product: str,
    expected_frequency: BarFrequency,
) -> tuple[NewowStrategyReplaySegment, ...]:
    """Build Web-parity physical-prefix replays without making prefixes tradable."""

    try:
        if (
            not actual_bars
            or not authoritative_segments
            or any(
                not _valid_segment(segment, expected_product)
                for segment in authoritative_segments
            )
            or any(
                current.start_trading_day <= previous.end_trading_day
                for previous, current in zip(
                    authoritative_segments,
                    authoritative_segments[1:],
                    strict=False,
                )
            )
            or any(bar.product != expected_product for bar in actual_bars)
            or any(bar.frequency != expected_frequency.value for bar in actual_bars)
            or any(not bar.observation_eligible for bar in actual_bars)
        ):
            raise NewowFuturesSeriesError
        actual_by_segment: dict[str, tuple[NewowResearchBar, ...]] = {}
        for segment in authoritative_segments:
            segment_id = (
                f"{expected_product}:{segment.contract}:"
                f"{segment.start_trading_day.isoformat()}:"
                f"{segment.end_trading_day.isoformat()}"
            )
            owned = tuple(bar for bar in actual_bars if bar.segment_id == segment_id)
            if owned:
                actual_by_segment[segment_id] = owned
        if sum(len(owned) for owned in actual_by_segment.values()) != len(actual_bars):
            raise NewowFuturesSeriesError

        observed_segments = tuple(
            segment
            for segment in authoritative_segments
            if any(
                bar.segment_id
                == (
                    f"{expected_product}:{segment.contract}:"
                    f"{segment.start_trading_day.isoformat()}:"
                    f"{segment.end_trading_day.isoformat()}"
                )
                for bar in actual_bars
            )
        )
        if len(observed_segments) != len(physical_prefix_pages):
            raise NewowFuturesSeriesError

        result: list[NewowStrategyReplaySegment] = []
        for segment, page in zip(
            observed_segments, physical_prefix_pages, strict=True
        ):
            segment_id = (
                f"{expected_product}:{segment.contract}:"
                f"{segment.start_trading_day.isoformat()}:"
                f"{segment.end_trading_day.isoformat()}"
            )
            owned = actual_by_segment[segment_id]
            identity = page.request_identity
            if (
                identity.get("series_kind") != "contract"
                or identity.get("symbol") != expected_product
                or identity.get("contract") != segment.contract
                or identity.get("frequency") != expected_frequency.value
                or identity.get("before")
                != (owned[-1].bar_end + timedelta(microseconds=1)).isoformat()
                or identity.get("limit") != 2000
                or page.has_more_before
                or not page.bars
                or page.canonical_coverage
                != (page.bars[0].bar_end, page.bars[-1].bar_end)
                or page.resolved_contract_segments
            ):
                raise NewowFuturesSeriesError
            owned_by_key = {
                (bar.trading_day, bar.bar_end): bar for bar in owned
            }
            replay_bars: list[NewowResearchBar] = []
            matched: set[tuple[date, object]] = set()
            previous_end = None
            for bar in page.bars:
                if previous_end is not None and bar.bar_end <= previous_end:
                    raise NewowFuturesSeriesError
                previous_end = bar.bar_end
                key = (bar.trading_day, bar.bar_end)
                ranked = owned_by_key.get(key)
                if ranked is not None:
                    if not _same_ohlcv(bar, ranked):
                        raise NewowFuturesSeriesError
                    source_identity = ranked.source_identity
                    matched.add(key)
                else:
                    if bar.trading_day >= segment.start_trading_day:
                        raise NewowFuturesSeriesError
                    source_identity = (
                        f"canonical:contract:{expected_product}:"
                        f"{expected_frequency.value}:{segment.contract}:"
                        f"{bar.trading_day.isoformat()}:{bar.bar_end.isoformat()}"
                    )
                replay_bars.append(
                    NewowResearchBar(
                        product=expected_product,
                        physical_contract=segment.contract,
                        segment_id=segment_id,
                        trading_day=bar.trading_day,
                        bar_end=bar.bar_end,
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=_integral(bar.volume) or 0,
                        open_interest=_integral(bar.open_interest),
                        source_identity=source_identity,
                        observation_eligible=ranked is not None,
                        completed=True,
                        series_kind=(
                            "actual_dominant" if ranked is not None else "contract"
                        ),
                        frequency=expected_frequency.value,
                        turnover=bar.turnover,
                    )
                )
            if matched != set(owned_by_key):
                raise NewowFuturesSeriesError
            result.append(NewowStrategyReplaySegment(tuple(replay_bars)))
        return tuple(result)
    except (AttributeError, TypeError, ValueError):
        raise NewowFuturesSeriesError from None
