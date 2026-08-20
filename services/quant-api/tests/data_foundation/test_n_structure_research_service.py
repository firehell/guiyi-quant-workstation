from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType

from app.market_data.actual_dominant_research import ActualDominantResearchSeries
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesResult,
    ResolvedContractSegment,
)
from app.market_data.n_structure_policy import load_n_structure_policy
from app.market_data.n_structure_research_service import (
    NStructureResearchRequest,
    NStructureResearchService,
)


_VALUES = (
    ("10", "9"),
    ("9", "8.5"),
    ("8.5", "8"),
    ("9.5", "8.2"),
    ("12", "9"),
    ("11", "8.8"),
    ("13", "9"),
    ("14", "10"),
    ("13", "9.5"),
    ("15", "10"),
)


def _bars() -> tuple[CanonicalBar, ...]:
    start = datetime(2026, 8, 18, 1, 5, tzinfo=UTC)
    days = (
        *(date(2026, 8, 18) for _ in range(6)),
        *(date(2026, 8, 19) for _ in range(2)),
        *(date(2026, 8, 20) for _ in range(2)),
    )
    result: list[CanonicalBar] = []
    for index, ((high, low), trading_day) in enumerate(zip(_VALUES, days, strict=True)):
        high_value = Decimal(high)
        low_value = Decimal(low)
        close = (high_value + low_value) / Decimal(2)
        result.append(
            CanonicalBar(
                bar_end=start + timedelta(minutes=5 * index),
                trading_day=trading_day,
                open=close,
                high=high_value,
                low=low_value,
                close=close,
                volume=Decimal("1"),
                turnover=None,
                open_interest=None,
            )
        )
    return tuple(result)


class _FakeSegmentLoader:
    def __init__(self, bars: tuple[CanonicalBar, ...]) -> None:
        segment = ResolvedContractSegment(
            contract="JM2701",
            start_trading_day=date(2026, 8, 18),
            end_trading_day=date(2026, 8, 20),
        )
        result = MarketSeriesResult(
            request_identity={},
            bars=bars,
            coverage=(bars[0].bar_end, bars[-1].bar_end),
            resolved_contract_segments=(segment,),
        )
        self.result = ActualDominantResearchSeries(
            results=MappingProxyType({BarFrequency.M5: result}),
            segments=(segment,),
        )
        self.calls: list[dict[str, object]] = []

    def load(self, **kwargs: object) -> ActualDominantResearchSeries:
        self.calls.append(kwargs)
        return self.result


def test_reducer_uses_true_segment_prefix_but_counts_only_requested_window() -> None:
    loader = _FakeSegmentLoader(_bars())
    service = NStructureResearchService(
        loader,
        products=("jm", "ag"),
        policy=load_n_structure_policy(),
    )

    result = service.run(
        NStructureResearchRequest(
            since=date(2026, 8, 19),
            through=date(2026, 8, 20),
            symbol=" JM ",
        )
    )

    assert loader.calls == [
        {
            "symbol": "jm",
            "frequencies": (BarFrequency.M5,),
            "since": date(2026, 8, 19),
            "through": date(2026, 8, 20),
        }
    ]
    assert result.products == ("jm",)
    assert result.segment_count == 1
    assert result.evaluable_bar_count == 4
    assert result.confirmed_pivot_count == 3
    assert result.completed_n_counts == {"up": 2, "down": 0}
    assert result.structure_established_counts == {"bull": 1, "bear": 0, "range": 0}

    horizon_3 = result.horizon_summary[3]
    assert horizon_3.sample_count == 1
    assert horizon_3.median_directional_return_bps == Decimal(
        "1363.636363636363636363636364"
    )
    assert horizon_3.median_mfe_bps == Decimal(
        "3636.363636363636363636363636"
    )
    assert horizon_3.median_mae_bps == Decimal(
        "-1363.636363636363636363636364"
    )
    assert result.horizon_summary[5].sample_count == 0
    assert result.horizon_summary[8].sample_count == 0


def test_outcomes_stop_at_requested_through_even_if_loader_returns_later_bars() -> None:
    bars = _bars()
    later = tuple(
        CanonicalBar(
            bar_end=bars[-1].bar_end + timedelta(minutes=5 * (index + 1)),
            trading_day=date(2026, 8, 21),
            open=Decimal("13"),
            high=Decimal("14"),
            low=Decimal("12"),
            close=Decimal("13"),
            volume=Decimal("1"),
            turnover=None,
            open_interest=None,
        )
        for index in range(8)
    )
    loaded_bars = (*bars, *later)
    segment = ResolvedContractSegment(
        contract="JM2701",
        start_trading_day=date(2026, 8, 18),
        end_trading_day=date(2026, 8, 21),
    )
    loaded_result = MarketSeriesResult(
        request_identity={},
        bars=loaded_bars,
        coverage=(loaded_bars[0].bar_end, loaded_bars[-1].bar_end),
        resolved_contract_segments=(segment,),
    )
    loader = _FakeSegmentLoader(bars)
    loader.result = ActualDominantResearchSeries(
        results=MappingProxyType({BarFrequency.M5: loaded_result}),
        segments=(segment,),
    )
    service = NStructureResearchService(
        loader,
        products=("jm",),
        policy=load_n_structure_policy(),
    )

    result = service.run(
        NStructureResearchRequest(
            since=date(2026, 8, 19),
            through=date(2026, 8, 20),
            symbol="jm",
        )
    )

    assert loader.result.results[BarFrequency.M5].bars[-1].trading_day == date(
        2026, 8, 21
    )
    assert result.horizon_summary[5].sample_count == 0
    assert result.horizon_summary[8].sample_count == 0


def test_rank1_segment_change_resets_the_real_n_producer_chain() -> None:
    bars = _bars()
    segments = (
        ResolvedContractSegment(
            contract="JM2609",
            start_trading_day=date(2026, 8, 18),
            end_trading_day=date(2026, 8, 18),
        ),
        ResolvedContractSegment(
            contract="JM2701",
            start_trading_day=date(2026, 8, 19),
            end_trading_day=date(2026, 8, 20),
        ),
    )
    loaded_result = MarketSeriesResult(
        request_identity={},
        bars=bars,
        coverage=(bars[0].bar_end, bars[-1].bar_end),
        resolved_contract_segments=segments,
    )
    loader = _FakeSegmentLoader(bars)
    loader.result = ActualDominantResearchSeries(
        results=MappingProxyType({BarFrequency.M5: loaded_result}),
        segments=segments,
    )
    service = NStructureResearchService(
        loader,
        products=("jm",),
        policy=load_n_structure_policy(),
    )

    result = service.run(
        NStructureResearchRequest(
            since=date(2026, 8, 18),
            through=date(2026, 8, 20),
            symbol="jm",
        )
    )

    assert result.segment_count == 2
    assert result.evaluable_bar_count == len(bars)
    assert result.completed_n_counts == {"up": 0, "down": 0}
    assert all(
        evaluation.sample_count == 0
        for evaluation in result.horizon_summary.values()
    )
