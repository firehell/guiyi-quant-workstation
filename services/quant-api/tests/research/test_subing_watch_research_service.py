from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import importlib
from types import SimpleNamespace

import pytest

from app.market_data.aggregation import SessionWindow
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesResult,
    ResolvedContractSegment,
)
from app.market_data.price_outcome import PriceOutcomeError
from app.market_data.subing_watch.contracts import load_subing_watch_policy


DAY = date(2026, 9, 1)
START = datetime(2026, 9, 1, tzinfo=UTC)
SEGMENT = ResolvedContractSegment("JM2601", DAY, DAY)


def _module():
    try:
        return importlib.import_module(
            "app.research.subing.subing_watch_research_service"
        )
    except ModuleNotFoundError:
        pytest.fail("SuBing Watch research service is not implemented")


def _bar(index: int, *, minutes: int = 15, close: str = "100") -> CanonicalBar:
    value = Decimal(close)
    return CanonicalBar(
        bar_end=START + timedelta(minutes=index * minutes),
        trading_day=DAY,
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal(100 + index),
        turnover=Decimal(1000 + index),
        open_interest=Decimal(200 + index),
    )


def _candidate_bars() -> tuple[CanonicalBar, ...]:
    return (
        *(_bar(index) for index in range(1, 35)),
        _bar(35, close="110"),
        _bar(36, close="80"),
    )


def _negative_candidate_bars() -> tuple[CanonicalBar, ...]:
    return (
        *(_bar(index) for index in range(1, 35)),
        _bar(35, close="110"),
        _bar(36, close="-80"),
        _bar(37, close="-70"),
    )


def _bars_for_day(day: date, closes: list[int]) -> tuple[CanonicalBar, ...]:
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return tuple(
        CanonicalBar(
            bar_end=start + timedelta(minutes=15 * index),
            trading_day=day,
            open=Decimal(close),
            high=Decimal(close),
            low=Decimal(close),
            close=Decimal(close),
            volume=Decimal(100 + index),
            turnover=Decimal(1000 + index),
            open_interest=Decimal(200 + index),
        )
        for index, close in enumerate(closes, start=1)
    )


class _MarketData:
    def __init__(
        self,
        bars_by_symbol: dict[str, tuple[CanonicalBar, ...]],
    ) -> None:
        self._bars_by_symbol = bars_by_symbol

    def query_actual_dominant_trading_days(self, request) -> MarketSeriesResult:
        source = (
            self._bars_by_symbol[request.symbol]
            if request.frequency is BarFrequency.M15
            else (_bar(1, minutes=60),)
        )
        bars = tuple(
            bar
            for bar in source
            if request.since <= bar.trading_day <= request.through
        )
        segment = ResolvedContractSegment(
            f"{request.symbol.upper()}2601",
            DAY,
            DAY,
        )
        return MarketSeriesResult(
            request_identity={
                "series_kind": "actual_dominant",
                "symbol": request.symbol,
                "frequency": request.frequency.value,
            },
            bars=bars,
            coverage=(bars[0].bar_end, bars[-1].bar_end) if bars else None,
            resolved_contract_segments=(segment,),
            requested_trading_day_window=(request.since, request.through),
        )

    def dominant_segment_for_day(self, symbol: str, trading_day: date):
        assert trading_day == DAY
        return SimpleNamespace(
            symbol=symbol,
            contract=f"{symbol.upper()}2601",
            start_trading_day=DAY,
            end_trading_day=DAY,
        )

    def session_windows(
        self,
        *,
        symbol: str,
        trading_day: date,
    ) -> tuple[SessionWindow, ...]:
        assert symbol in self._bars_by_symbol and trading_day == DAY
        return (
            SessionWindow(START, START + timedelta(hours=6)),
            SessionWindow(START + timedelta(hours=6), START + timedelta(hours=12)),
        )

    def connect_rqdata(self):
        raise AssertionError("diagnostics must not construct an RQData provider")

    def publish(self):
        raise AssertionError("diagnostics must not publish or write")


FIRST_DAY = date(2026, 8, 31)
SECOND_DAY = date(2026, 9, 1)
AFTER_THROUGH = date(2026, 9, 2)
FIRST_SEGMENT = ResolvedContractSegment("JM2601", FIRST_DAY, FIRST_DAY)
SECOND_SEGMENT = ResolvedContractSegment("JM2605", SECOND_DAY, AFTER_THROUGH)


class _TwoSegmentMarketData:
    def __init__(self) -> None:
        first = _bars_for_day(
            FIRST_DAY,
            [100] * 34
            + [125, 50, 45, 40, 35, 30, 25, 20, 15, 10, 50, 100],
        )
        second = _bars_for_day(SECOND_DAY, [100] * 34 + [125])
        after = _bars_for_day(AFTER_THROUGH, [120, 115, 110, 105])
        self._bars_15m = (*first, *second, *after)
        self._bars_60m = tuple(
            _bars_for_day(day, [100])[0]
            for day in (FIRST_DAY, SECOND_DAY, AFTER_THROUGH)
        )
        self.requests: list[object] = []

    def query_actual_dominant_trading_days(self, request) -> MarketSeriesResult:
        self.requests.append(request)
        source = (
            self._bars_15m
            if request.frequency is BarFrequency.M15
            else self._bars_60m
        )
        bars = tuple(
            bar
            for bar in source
            if request.since <= bar.trading_day <= request.through
        )
        segments = tuple(
            segment
            for segment in (FIRST_SEGMENT, SECOND_SEGMENT)
            if any(
                segment.start_trading_day
                <= bar.trading_day
                <= segment.end_trading_day
                for bar in bars
            )
        )
        return MarketSeriesResult(
            request_identity={
                "series_kind": "actual_dominant",
                "symbol": request.symbol,
                "frequency": request.frequency.value,
            },
            bars=bars,
            coverage=(bars[0].bar_end, bars[-1].bar_end),
            resolved_contract_segments=segments,
            requested_trading_day_window=(request.since, request.through),
        )

    def dominant_segment_for_day(self, symbol: str, trading_day: date):
        segment = FIRST_SEGMENT if trading_day == FIRST_DAY else SECOND_SEGMENT
        return SimpleNamespace(
            symbol=symbol,
            contract=segment.contract,
            start_trading_day=segment.start_trading_day,
            end_trading_day=segment.end_trading_day,
        )

    def session_windows(
        self,
        *,
        symbol: str,
        trading_day: date,
    ) -> tuple[SessionWindow, ...]:
        assert symbol == "jm" and trading_day in {FIRST_DAY, SECOND_DAY}
        start = datetime(
            trading_day.year,
            trading_day.month,
            trading_day.day,
            tzinfo=UTC,
        )
        return (
            SessionWindow(start, start + timedelta(hours=6)),
            SessionWindow(start + timedelta(hours=6), start + timedelta(hours=12)),
        )


def _service(bars_by_symbol: dict[str, tuple[CanonicalBar, ...]]):
    module = _module()
    return module.SubingWatchResearchService(
        _MarketData(bars_by_symbol),
        products=tuple(reversed(tuple(bars_by_symbol))),
        policy=load_subing_watch_policy(),
    )


def test_service_replays_actual_dominant_segments_and_sorts_products() -> None:
    module = _module()
    service = _service({"jm": _candidate_bars(), "ag": tuple(_bar(i) for i in range(1, 41))})
    request = module.SubingWatchResearchRequest(
        since=DAY,
        through=DAY,
        symbols=("jm", "ag"),
        forward_bars=(1, 2),
    )

    result = service.run(request)

    assert tuple(product.symbol for product in result.products) == ("ag", "jm")
    ag, jm = result.products
    assert ag.candidate_count == 0
    assert jm.candidate_count == 2
    assert jm.direction_counts == {"buy": 1, "sell": 1}
    assert jm.candidates_per_trading_day == {DAY.isoformat(): 2}
    assert jm.range_state_distribution == {
        "range_unavailable": 2,
        "no_active_range": 0,
        "intact": 0,
        "broken_up": 0,
        "broken_down": 0,
    }
    assert jm.higher_timeframe_alignment_distribution["unavailable"] == 2
    assert jm.context_availability.available_count == 2
    assert jm.context_availability.rate.denominator == 2
    assert sum(jm.session_distribution.values()) == 2


def test_forward_diagnostics_truncate_at_physical_segment_tail() -> None:
    module = _module()
    result = _service({"jm": _candidate_bars()}).run(
        module.SubingWatchResearchRequest(
            since=DAY,
            through=DAY,
            symbols=("jm",),
            forward_bars=(1, 2, 4, 8),
        )
    )

    forward = result.products[0].forward_diagnostics
    assert (forward[1].sample_count, forward[1].truncated_count) == (1, 1)
    assert (forward[2].sample_count, forward[2].truncated_count) == (0, 2)
    assert (forward[4].sample_count, forward[4].truncated_count) == (0, 2)
    assert (forward[8].sample_count, forward[8].truncated_count) == (0, 2)
    assert forward[1].median_directional_close_change_bps is not None
    assert forward[2].median_directional_close_change_bps is None
    assert forward[2].median_mfe_bps is None
    assert forward[2].median_mae_bps is None


def test_two_segments_reset_and_bound_forward_metrics_to_segment_and_through() -> None:
    module = _module()
    market_data = _TwoSegmentMarketData()
    service = module.SubingWatchResearchService(
        market_data,
        products=("jm",),
        policy=load_subing_watch_policy(),
    )

    product = service.run(
        module.SubingWatchResearchRequest(
            since=FIRST_DAY,
            through=SECOND_DAY,
            symbols=("jm",),
            forward_bars=(1, 2, 4, 8),
        )
    ).products[0]

    assert all(request.through == SECOND_DAY for request in market_data.requests)
    assert product.candidate_count == 4
    assert product.direction_counts == {"buy": 3, "sell": 1}
    assert product.candidates_per_trading_day == {
        FIRST_DAY.isoformat(): 3,
        SECOND_DAY.isoformat(): 1,
    }
    expected = {
        1: (
            Decimal("-2500.000000"),
            Decimal("-2500.000000"),
            Decimal("-2500.000000"),
        ),
        2: (
            Decimal("-2200.000000"),
            Decimal("-2000.000000"),
            Decimal("-2700.000000"),
        ),
        4: (
            Decimal("-1600.000000"),
            Decimal("-1000.000000"),
            Decimal("-3100.000000"),
        ),
        8: (
            Decimal("-400.000000"),
            Decimal("1000.000000"),
            Decimal("-3900.000000"),
        ),
    }
    for horizon, metrics in expected.items():
        diagnostics = product.forward_diagnostics[horizon]
        assert diagnostics.sample_count == 2
        assert diagnostics.truncated_count == 2
        assert (
            diagnostics.median_directional_close_change_bps,
            diagnostics.median_mfe_bps,
            diagnostics.median_mae_bps,
        ) == metrics


def test_rollover_tail_truncates_before_next_physical_contract() -> None:
    module = _module()
    market_data = _TwoSegmentMarketData()
    service = module.SubingWatchResearchService(
        market_data,
        products=("jm",),
        policy=load_subing_watch_policy(),
    )

    product = service.run(
        module.SubingWatchResearchRequest(
            since=FIRST_DAY,
            through=FIRST_DAY,
            symbols=("jm",),
            forward_bars=(1, 2, 4, 8),
        )
    ).products[0]

    assert product.candidate_count == 3
    assert product.candidates_per_trading_day == {FIRST_DAY.isoformat(): 3}
    assert all(request.through == FIRST_DAY for request in market_data.requests)
    assert {
        horizon: (diagnostics.sample_count, diagnostics.truncated_count)
        for horizon, diagnostics in product.forward_diagnostics.items()
    } == {1: (2, 1), 2: (2, 1), 4: (2, 1), 8: (2, 1)}


def test_negative_price_candidate_fails_closed_via_shared_price_outcome() -> None:
    module = _module()

    with pytest.raises(PriceOutcomeError, match="PRICE_OUTCOME_ENTRY_INVALID"):
        _service({"jm": _negative_candidate_bars()}).run(
            module.SubingWatchResearchRequest(
                since=DAY,
                through=DAY,
                symbols=("jm",),
                forward_bars=(1,),
            )
        )


def test_empty_candidate_sample_has_zero_denominators_and_no_forward_samples() -> None:
    module = _module()
    result = _service({"jm": tuple(_bar(i) for i in range(1, 41))}).run(
        module.SubingWatchResearchRequest(
            since=DAY,
            through=DAY,
            symbols=("jm",),
            forward_bars=(1,),
        )
    )

    product = result.products[0]
    assert product.candidate_count == 0
    assert product.same_direction_clustering.rate.denominator == 0
    assert product.same_direction_clustering.rate.value is None
    assert product.context_availability.rate.denominator == 0
    assert product.context_availability.rate.value is None
    assert product.forward_diagnostics[1].sample_count == 0
    assert product.forward_diagnostics[1].truncated_count == 0


def test_request_validates_symbol_date_order_and_forward_set() -> None:
    module = _module()

    for values in (
        {"since": DAY + timedelta(days=1), "through": DAY},
        {"symbols": ("jm", "jm")},
        {"symbols": ("JM",)},
        {"symbols": ("active", "jm")},
        {"forward_bars": (2, 1)},
        {"forward_bars": (1, 3)},
        {"forward_bars": (1, 1)},
    ):
        kwargs = {
            "since": DAY,
            "through": DAY,
            "symbols": ("jm",),
            "forward_bars": (1, 2),
            **values,
        }
        with pytest.raises(ValueError, match="SUBING_WATCH_RESEARCH_REQUEST_INVALID"):
            module.SubingWatchResearchRequest(**kwargs)


def test_explicit_symbol_must_be_inside_active_products_before_market_read() -> None:
    module = _module()
    service = _service({"jm": _candidate_bars()})

    with pytest.raises(
        module.SubingWatchResearchError,
        match="SUBING_WATCH_RESEARCH_SYMBOL_INVALID",
    ) as captured:
        service.run(
            module.SubingWatchResearchRequest(
                since=DAY,
                through=DAY,
                symbols=("ag",),
                forward_bars=(),
            )
        )
    assert captured.value.code == "SUBING_WATCH_RESEARCH_SYMBOL_INVALID"


def test_active_scope_uses_only_injected_active_products_in_sorted_order() -> None:
    module = _module()
    service = _service({"jm": _candidate_bars(), "ag": tuple(_bar(i) for i in range(1, 41))})

    result = service.run(
        module.SubingWatchResearchRequest(
            since=DAY,
            through=DAY,
            symbols="active",
            forward_bars=(),
        )
    )

    assert tuple(product.symbol for product in result.products) == ("ag", "jm")
