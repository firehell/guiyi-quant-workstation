"""Pure adapter from authoritative actual-dominant results to Newow research bars."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from guiyi_quant.newow import NewowResearchBar

from app.market_data.domain import (
    BarFrequency,
    MarketSeriesResult,
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
            )
        )
    return tuple(built)
