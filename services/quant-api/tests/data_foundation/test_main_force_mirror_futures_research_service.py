from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from inspect import signature
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.market_data.domain import (
    ActualDominantTradingDayQuery,
    BarFrequency,
    CanonicalBar,
    MarketSeriesResult,
    ResolvedContractSegment,
    SeriesKind,
    SeriesQuery,
)
from app.market_data.main_force_mirror_futures_research_service import (
    MainForceMirrorFuturesResearchRequest,
    MainForceMirrorFuturesResearchService,
    _extract_events,
)


_DAY_ONE = date(2026, 8, 17)
_DAY_TWO = date(2026, 8, 18)


def _bar(
    *,
    trading_day: date = _DAY_ONE,
    hour: int = 1,
    close: str = "100",
    high: str | None = None,
    low: str | None = None,
    open_interest: str | None = "5000",
) -> CanonicalBar:
    close_value = Decimal(close)
    return CanonicalBar(
        bar_end=datetime(2026, 8, trading_day.day, hour, tzinfo=UTC),
        trading_day=trading_day,
        open=close_value,
        high=Decimal(high) if high is not None else close_value + Decimal("1"),
        low=Decimal(low) if low is not None else close_value - Decimal("1"),
        close=close_value,
        volume=Decimal("1000"),
        turnover=None,
        open_interest=(None if open_interest is None else Decimal(open_interest)),
    )


def _result(
    bars: tuple[CanonicalBar, ...],
    segments: tuple[ResolvedContractSegment, ...] = (),
) -> MarketSeriesResult:
    return MarketSeriesResult(
        request_identity={},
        bars=bars,
        coverage=(bars[0].bar_end, bars[-1].bar_end) if bars else None,
        resolved_contract_segments=segments,
    )


class _FakeMarketData:
    def __init__(
        self,
        *,
        contract_result: MarketSeriesResult | None = None,
        dominant_result: MarketSeriesResult | None = None,
    ) -> None:
        self.contract_result = contract_result
        self.dominant_result = dominant_result
        self.queries: list[SeriesQuery] = []
        self.dominant_queries: list[ActualDominantTradingDayQuery] = []

    def query(self, request: SeriesQuery) -> MarketSeriesResult:
        self.queries.append(request)
        if self.contract_result is None:
            raise AssertionError("contract query was not expected")
        return self.contract_result

    def query_actual_dominant_trading_days(
        self,
        request: ActualDominantTradingDayQuery,
    ) -> MarketSeriesResult:
        self.dominant_queries.append(request)
        if self.dominant_result is None:
            raise AssertionError("actual-dominant query was not expected")
        return self.dominant_result


def _request(
    *,
    symbol: str = "jm",
    series_kind: SeriesKind = SeriesKind.ACTUAL_DOMINANT,
    contract: str | None = None,
    frequency: BarFrequency = BarFrequency.H1,
    since: date = _DAY_ONE,
    through: date = _DAY_TWO,
) -> MainForceMirrorFuturesResearchRequest:
    return MainForceMirrorFuturesResearchRequest(
        symbol=symbol,
        series_kind=series_kind,
        contract=contract,
        frequency=frequency,
        since=since,
        through=through,
    )


def test_request_normalizes_supported_identity() -> None:
    dominant = _request(symbol=" JM ")
    contract = _request(
        symbol=" jm ",
        series_kind=SeriesKind.CONTRACT,
        contract=" jm2609 ",
    )

    assert dominant.symbol == "jm"
    assert dominant.series_kind is SeriesKind.ACTUAL_DOMINANT
    assert dominant.contract is None
    assert dominant.frequency is BarFrequency.H1
    assert contract.symbol == "jm"
    assert contract.contract == "JM2609"


@pytest.mark.parametrize(
    "changes",
    (
        {"frequency": BarFrequency.M30},
        {"series_kind": SeriesKind.CONTINUOUS},
        {"series_kind": SeriesKind.CONTRACT, "contract": None},
        {"series_kind": SeriesKind.CONTRACT, "contract": "AG2609"},
        {"series_kind": SeriesKind.ACTUAL_DOMINANT, "contract": "JM2609"},
        {"symbol": ""},
        {"symbol": "jm1"},
        {"since": _DAY_TWO, "through": _DAY_ONE},
    ),
)
def test_request_rejects_unsupported_or_invalid_input(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _request(**changes)  # type: ignore[arg-type]


def test_service_accepts_only_a_market_data_reader_dependency() -> None:
    constructor = signature(MainForceMirrorFuturesResearchService)
    assert tuple(constructor.parameters) == ("market_data",)

    for forbidden in (
        Path("/tmp/canonical"),
        object(),
        type("Store", (), {"read": lambda self: None})(),
        type("Provider", (), {"get_price": lambda self: None})(),
        type("Redis", (), {"get": lambda self: None})(),
        type("Writer", (), {"write": lambda self: None})(),
    ):
        with pytest.raises(TypeError):
            MainForceMirrorFuturesResearchService(forbidden)


def test_actual_dominant_uses_only_exact_trading_day_query_and_segments() -> None:
    bars = (_bar(trading_day=_DAY_ONE), _bar(trading_day=_DAY_TWO, hour=2))
    segments = (ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_TWO),)
    market_data = _FakeMarketData(dominant_result=_result(bars, segments))

    result = MainForceMirrorFuturesResearchService(market_data).run(_request())

    assert market_data.dominant_queries == [
        ActualDominantTradingDayQuery("jm", BarFrequency.H1, _DAY_ONE, _DAY_TWO)
    ]
    assert market_data.queries == []
    assert result.products == ("jm",)
    assert result.bars_valid_count == 2
    assert result.segment_reset_count == 0


def test_contract_uses_only_series_query_and_binds_requested_contract() -> None:
    bars = (_bar(trading_day=_DAY_ONE), _bar(trading_day=_DAY_TWO, hour=2))
    market_data = _FakeMarketData(contract_result=_result(bars))
    request = _request(
        series_kind=SeriesKind.CONTRACT,
        contract="JM2609",
    )

    result = MainForceMirrorFuturesResearchService(market_data).run(request)

    assert len(market_data.queries) == 1
    query = market_data.queries[0]
    assert query.series_kind is SeriesKind.CONTRACT
    assert query.symbol == "jm"
    assert query.contract == "JM2609"
    assert query.frequency is BarFrequency.H1
    assert market_data.dominant_queries == []
    assert result.products == ("jm",)
    assert result.bars_valid_count == 2


def _observation(
    count: int,
    *,
    cautions: dict[int, str],
    conflicts: tuple[int, ...] = (),
) -> SimpleNamespace:
    caution_values: list[str | None] = [None] * count
    states: list[str | None] = ["turnover"] * count
    long_scores = [0.0] * count
    short_scores = [0.0] * count
    reasons: list[tuple[str, ...]] = [()] * count
    for index, caution in cautions.items():
        caution_values[index] = caution
        if caution == "long_chase_caution":
            states[index] = "short_cover"
            long_scores[index] = 70.0
            reasons[index] = (
                "LONG_UPPER_EXTREME",
                "LONG_OPEN_PRESSURE_DIVERGENCE",
            )
        else:
            states[index] = "long_liquidation"
            short_scores[index] = 85.0
            reasons[index] = (
                "SHORT_LOWER_EXTREME",
                "SHORT_LONG_LIQUIDATION_DOMINATED",
                "SHORT_OPEN_PRESSURE_DIVERGENCE",
            )
    caution_availability: list[str | None] = [None] * count
    for index in conflicts:
        caution_availability[index] = "MFM_FUTURES_V1_CAUTION_DIRECTION_CONFLICT"
        long_scores[index] = 70.0
        short_scores[index] = 70.0
        reasons[index] = ("LONG_UPPER_EXTREME", "SHORT_LOWER_EXTREME")
    return SimpleNamespace(
        metadata={
            "indicator_code": "main_force_mirror_futures_v1",
            "indicator_version": "futures-research-v1",
            "parameters_hash": "f7fd0c9bce0b08d1",
        },
        valid=[True] * count,
        state_ready=[True] * count,
        caution_ready=[True] * count,
        reason=[None] * count,
        caution_availability_reason=caution_availability,
        state=states,
        long_caution_score=long_scores,
        short_caution_score=short_scores,
        caution=caution_values,
        caution_reason_codes=tuple(reasons),
    )


def test_events_keep_exact_identity_and_conflict_creates_no_event() -> None:
    bars = (
        _bar(trading_day=_DAY_ONE, hour=1),
        _bar(trading_day=_DAY_ONE, hour=2),
        _bar(trading_day=_DAY_ONE, hour=3),
    )
    observation = _observation(
        len(bars),
        cautions={0: "long_chase_caution", 1: "short_chase_caution"},
        conflicts=(2,),
    )

    events = _extract_events(
        request=_request(),
        bars=bars,
        physical_contracts=("JM2609",) * len(bars),
        observation=observation,
    )

    assert len(events) == 2
    assert events[0].indicator_code == "main_force_mirror_futures_v1"
    assert events[0].indicator_version == "futures-research-v1"
    assert events[0].parameters_hash == "f7fd0c9bce0b08d1"
    assert events[0].symbol == "jm"
    assert events[0].series_kind is SeriesKind.ACTUAL_DOMINANT
    assert events[0].physical_contract == "JM2609"
    assert events[0].trading_day == _DAY_ONE
    assert events[0].bar_end == bars[0].bar_end
    assert events[0].caution_direction == "long_chase_caution"
    assert events[0].score == 70.0
    assert events[0].reason_codes == (
        "LONG_UPPER_EXTREME",
        "LONG_OPEN_PRESSURE_DIVERGENCE",
    )
    assert events[0].state == "short_cover"
    assert events[1].caution_direction == "short_chase_caution"
    assert events[1].score == 85.0
    assert all(event.bar_end != bars[2].bar_end for event in events)


def test_service_uses_future_bars_only_for_mirrored_segment_local_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prices = (
        ("100", "101", "99"),
        ("90", "105", "85"),
        ("100", "110", "80"),
        ("70", "95", "60"),
        ("120", "130", "90"),
        ("130", "135", "125"),
        ("140", "145", "135"),
        ("150", "155", "145"),
        ("160", "165", "155"),
        ("170", "175", "165"),
        ("180", "185", "175"),
        ("190", "195", "185"),
    )
    bars = tuple(
        _bar(
            trading_day=_DAY_ONE if index < 5 else _DAY_TWO,
            hour=index + 1,
            close=close,
            high=high,
            low=low,
        )
        for index, (close, high, low) in enumerate(prices)
    )
    segments = (
        ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),
        ResolvedContractSegment("JM2701", _DAY_TWO, _DAY_TWO),
    )
    market_data = _FakeMarketData(dominant_result=_result(bars, segments))
    observation = _observation(
        len(bars),
        cautions={0: "long_chase_caution", 1: "short_chase_caution"},
        conflicts=(2,),
    )
    kernel_calls: list[dict[str, object]] = []

    def compute(**kwargs: object) -> SimpleNamespace:
        kernel_calls.append(kwargs)
        return observation

    monkeypatch.setattr(
        "app.market_data.main_force_mirror_futures_research_service.compute_main_force_mirror_futures",
        compute,
    )

    result = MainForceMirrorFuturesResearchService(market_data).run(_request())

    assert len(kernel_calls) == 1
    assert kernel_calls[0]["physical_contract"] == (
        "JM2609",
        "JM2609",
        "JM2609",
        "JM2609",
        "JM2609",
        "JM2701",
        "JM2701",
        "JM2701",
        "JM2701",
        "JM2701",
        "JM2701",
        "JM2701",
    )
    assert result.event_count_long == 1
    assert result.event_count_short == 1
    assert result.conflict_count == 1
    assert result.segment_reset_count == 1
    assert result.score_distribution == (70, 85)
    assert result.reason_code_distribution == {
        "LONG_OPEN_PRESSURE_DIVERGENCE": 1,
        "LONG_UPPER_EXTREME": 1,
        "SHORT_LONG_LIQUIDATION_DOMINATED": 1,
        "SHORT_LOWER_EXTREME": 1,
        "SHORT_OPEN_PRESSURE_DIVERGENCE": 1,
    }

    one = result.horizon_summary[1]
    assert one.sample_count == 2
    assert one.reversal_returns == pytest.approx((0.1, 10 / 90))
    assert one.warning_mfe == pytest.approx((0.15, 20 / 90))
    assert one.warning_mae == pytest.approx((0.05, 10 / 90))

    three = result.horizon_summary[3]
    assert three.sample_count == 2
    assert three.reversal_returns == pytest.approx((0.3, 30 / 90))
    assert three.warning_mfe == pytest.approx((0.4, 40 / 90))
    assert three.warning_mae == pytest.approx((0.1, 30 / 90))

    for horizon in (5, 10):
        summary = result.horizon_summary[horizon]
        assert summary.sample_count == 0
        assert summary.reversal_returns == ()
        assert summary.warning_mfe == ()
        assert summary.warning_mae == ()


def test_insufficient_future_bars_do_not_create_horizon_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars = tuple(
        _bar(trading_day=_DAY_ONE, hour=index + 1, close=str(100 + index))
        for index in range(4)
    )
    market_data = _FakeMarketData(
        dominant_result=_result(
            bars,
            (ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),),
        )
    )
    monkeypatch.setattr(
        "app.market_data.main_force_mirror_futures_research_service.compute_main_force_mirror_futures",
        lambda **_kwargs: _observation(
            len(bars),
            cautions={2: "long_chase_caution"},
        ),
    )

    result = MainForceMirrorFuturesResearchService(market_data).run(_request())

    assert result.horizon_summary[1].sample_count == 1
    assert result.horizon_summary[3].sample_count == 0
    assert result.horizon_summary[5].sample_count == 0
    assert result.horizon_summary[10].sample_count == 0


@pytest.mark.parametrize(
    ("segments", "code"),
    (
        ((), "MFM_FUTURES_V1_PHYSICAL_CONTRACT_MISSING"),
        (
            (
                ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_TWO),
                ResolvedContractSegment("JM2701", _DAY_ONE, _DAY_TWO),
            ),
            "MFM_FUTURES_V1_SEGMENT_CONFLICT",
        ),
    ),
)
def test_actual_dominant_never_fabricates_missing_or_conflicting_segments(
    segments: tuple[ResolvedContractSegment, ...],
    code: str,
) -> None:
    market_data = _FakeMarketData(dominant_result=_result((_bar(),), segments))

    with pytest.raises(RuntimeError) as exc_info:
        MainForceMirrorFuturesResearchService(market_data).run(_request())

    assert getattr(exc_info.value, "code", None) == code
