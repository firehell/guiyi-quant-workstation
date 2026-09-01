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

    with pytest.raises(ValueError, match="SUBING_WATCH_RESEARCH_SYMBOL_INVALID"):
        service.run(
            module.SubingWatchResearchRequest(
                since=DAY,
                through=DAY,
                symbols=("ag",),
                forward_bars=(),
            )
        )


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
