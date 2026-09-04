from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesResult,
    ResolvedContractSegment,
)
from app.market_data.newow.futures_validation import (
    NewowFuturesSeriesError,
    build_newow_research_bars,
)


_START = date(2026, 1, 5)


def _bar(
    offset: int,
    *,
    trading_day: date | None = None,
    volume: str = "100",
    open_interest: str | None = "1000",
) -> CanonicalBar:
    value = Decimal(100 + offset)
    return CanonicalBar(
        bar_end=datetime(2026, 1, 5, 7, tzinfo=UTC) + timedelta(days=offset),
        trading_day=trading_day or _START + timedelta(days=offset),
        open=value,
        high=value + Decimal("1"),
        low=value - Decimal("1"),
        close=value,
        volume=Decimal(volume),
        turnover=Decimal("10000"),
        open_interest=None if open_interest is None else Decimal(open_interest),
    )


def _result(
    frequency: BarFrequency,
    *,
    bars: tuple[CanonicalBar, ...] | None = None,
    segments: tuple[ResolvedContractSegment, ...] | None = None,
    series_kind: str = "actual_dominant",
    symbol: str = "rb",
) -> MarketSeriesResult:
    values = bars or (_bar(0), _bar(1), _bar(2))
    resolved = segments or (
        ResolvedContractSegment("RB2610", _START, _START + timedelta(days=1)),
        ResolvedContractSegment(
            "RB2701",
            _START + timedelta(days=2),
            _START + timedelta(days=10),
        ),
    )
    return MarketSeriesResult(
        request_identity={
            "series_kind": series_kind,
            "symbol": symbol,
            "contract": None,
            "frequency": frequency.value,
            "start": "2026-01-04T00:00:00+00:00",
            "end": "2026-01-16T00:00:00+00:00",
        },
        bars=values,
        coverage=(values[0].bar_end, values[-1].bar_end),
        resolved_contract_segments=resolved,
        requested_trading_day_window=(_START, _START + timedelta(days=10)),
    )


@pytest.mark.parametrize(
    "frequency",
    (BarFrequency.D1, BarFrequency.W1, BarFrequency.H1),
)
def test_builds_completed_actual_dominant_research_bars_per_frequency(
    frequency: BarFrequency,
) -> None:
    result = _result(frequency)
    built = build_newow_research_bars(
        result,
        authoritative_segments=result.resolved_contract_segments,
        expected_product="rb",
        expected_frequency=frequency,
    )

    assert tuple(bar.frequency for bar in built) == (frequency.value,) * 3
    assert tuple(bar.physical_contract for bar in built) == (
        "RB2610",
        "RB2610",
        "RB2701",
    )
    assert all(bar.completed and bar.observation_eligible for bar in built)
    assert built[0].segment_id == "rb:RB2610:2026-01-05:2026-01-06"
    assert built[2].source_identity == (
        f"canonical:actual_dominant:rb:{frequency.value}:RB2701:"
        "2026-01-07:2026-01-07T07:00:00+00:00"
    )


def test_weekly_owner_comes_from_weekly_result_segments() -> None:
    weekly_bar = _bar(4, trading_day=date(2026, 1, 9))
    weekly = _result(
        BarFrequency.W1,
        bars=(weekly_bar,),
        segments=(
            ResolvedContractSegment(
                "RB2701",
                date(2026, 1, 9),
                date(2026, 1, 9),
            ),
        ),
    )

    built = build_newow_research_bars(
        weekly,
        authoritative_segments=weekly.resolved_contract_segments,
        expected_product="rb",
        expected_frequency=BarFrequency.W1,
    )

    assert built[0].physical_contract == "RB2701"
    assert built[0].frequency == "1w"


def test_segment_identity_uses_authoritative_unclipped_boundaries() -> None:
    authoritative = (
        ResolvedContractSegment(
            "RB2610",
            date(2025, 12, 1),
            date(2026, 2, 1),
        ),
    )
    short = _result(
        BarFrequency.D1,
        bars=(_bar(0),),
        segments=(ResolvedContractSegment("RB2610", _START, _START),),
    )
    extended = _result(
        BarFrequency.D1,
        bars=(_bar(0), _bar(1)),
        segments=(
            ResolvedContractSegment(
                "RB2610",
                _START,
                _START + timedelta(days=1),
            ),
        ),
    )

    short_built = build_newow_research_bars(
        short,
        authoritative_segments=authoritative,
        expected_product="rb",
        expected_frequency=BarFrequency.D1,
    )
    extended_built = build_newow_research_bars(
        extended,
        authoritative_segments=authoritative,
        expected_product="rb",
        expected_frequency=BarFrequency.D1,
    )

    assert short_built[0].segment_id == extended_built[0].segment_id
    assert short_built[0].segment_id == "rb:RB2610:2025-12-01:2026-02-01"


@pytest.mark.parametrize(
    "result,expected_frequency",
    (
        (_result(BarFrequency.D1, series_kind="continuous"), BarFrequency.D1),
        (_result(BarFrequency.D1, symbol="jm"), BarFrequency.D1),
        (_result(BarFrequency.D1), BarFrequency.H1),
        (
            _result(
                BarFrequency.D1,
                segments=(
                    ResolvedContractSegment(
                        "RB2610",
                        _START,
                        _START,
                    ),
                ),
            ),
            BarFrequency.D1,
        ),
        (
            _result(
                BarFrequency.D1,
                segments=(
                    ResolvedContractSegment(
                        "RB2610",
                        _START,
                        _START + timedelta(days=2),
                    ),
                    ResolvedContractSegment(
                        "RB2701",
                        _START + timedelta(days=2),
                        _START + timedelta(days=3),
                    ),
                ),
            ),
            BarFrequency.D1,
        ),
        (
            _result(
                BarFrequency.D1,
                bars=(_bar(0, volume="1.5"),),
                segments=(
                    ResolvedContractSegment("RB2610", _START, _START),
                ),
            ),
            BarFrequency.D1,
        ),
    ),
)
def test_rejects_untrusted_or_ambiguous_series(
    result: MarketSeriesResult,
    expected_frequency: BarFrequency,
) -> None:
    with pytest.raises(NewowFuturesSeriesError) as exc_info:
        build_newow_research_bars(
            result,
            authoritative_segments=result.resolved_contract_segments,
            expected_product="rb",
            expected_frequency=expected_frequency,
        )

    assert exc_info.value.code == "NEWOW_FUTURES_SERIES_INVALID"


def test_rejects_empty_inconsistent_coverage_and_nonintegral_oi() -> None:
    valid = _result(BarFrequency.D1)
    cases = (
        MarketSeriesResult(
            request_identity=valid.request_identity,
            bars=(),
            coverage=None,
            resolved_contract_segments=valid.resolved_contract_segments,
            requested_trading_day_window=valid.requested_trading_day_window,
        ),
        MarketSeriesResult(
            request_identity=valid.request_identity,
            bars=valid.bars,
            coverage=(valid.bars[0].bar_end, valid.bars[1].bar_end),
            resolved_contract_segments=valid.resolved_contract_segments,
            requested_trading_day_window=valid.requested_trading_day_window,
        ),
        _result(
            BarFrequency.D1,
            bars=(_bar(0, open_interest="1000.5"),),
            segments=(ResolvedContractSegment("RB2610", _START, _START),),
        ),
    )

    for result in cases:
        with pytest.raises(
            NewowFuturesSeriesError,
            match="NEWOW_FUTURES_SERIES_INVALID",
        ):
            build_newow_research_bars(
                result,
                authoritative_segments=result.resolved_contract_segments,
                expected_product="rb",
                expected_frequency=BarFrequency.D1,
            )


def test_rejects_overlapping_returned_segments_even_without_a_bar_on_overlap() -> None:
    result = _result(
        BarFrequency.D1,
        segments=(
            ResolvedContractSegment(
                "RB2610",
                _START,
                _START + timedelta(days=8),
            ),
            ResolvedContractSegment(
                "RB2701",
                _START + timedelta(days=8),
                _START + timedelta(days=10),
            ),
        ),
    )

    with pytest.raises(
        NewowFuturesSeriesError,
        match="NEWOW_FUTURES_SERIES_INVALID",
    ):
        build_newow_research_bars(
            result,
            authoritative_segments=result.resolved_contract_segments,
            expected_product="rb",
            expected_frequency=BarFrequency.D1,
        )


def test_rejects_a_contract_that_does_not_belong_to_the_expected_product() -> None:
    result = _result(
        BarFrequency.D1,
        segments=(
            ResolvedContractSegment(
                "AU2610",
                _START,
                _START + timedelta(days=10),
            ),
        ),
    )

    with pytest.raises(
        NewowFuturesSeriesError,
        match="NEWOW_FUTURES_SERIES_INVALID",
    ):
        build_newow_research_bars(
            result,
            authoritative_segments=result.resolved_contract_segments,
            expected_product="rb",
            expected_frequency=BarFrequency.D1,
        )
