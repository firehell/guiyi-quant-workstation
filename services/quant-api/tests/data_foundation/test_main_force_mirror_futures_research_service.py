from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from inspect import signature
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.market_data import (
    main_force_mirror_futures_research_service as research_module,
)
from app.market_data.domain import (
    ActualDominantTradingDayQuery,
    BarFrequency,
    CanonicalBar,
    ContractTradingDayQuery,
    MarketSeriesResult,
    ResolvedContractSegment,
    SeriesKind,
)
from app.market_data.main_force_mirror_futures_research_service import (
    MAIN_FORCE_MIRROR_FUTURES_REPRESENTATIVE_PRODUCTS,
    MainForceMirrorFuturesEvent,
    MainForceMirrorFuturesResearchRequest,
    MainForceMirrorFuturesResearchService,
    _extract_events,
    _summarize_horizons,
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
        self.contract_queries: list[ContractTradingDayQuery] = []
        self.dominant_queries: list[ActualDominantTradingDayQuery] = []

    def query_contract_trading_days(
        self,
        request: ContractTradingDayQuery,
    ) -> MarketSeriesResult:
        self.contract_queries.append(request)
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


def test_representative_products_are_an_exact_non_executing_parameter_contract() -> (
    None
):
    assert MAIN_FORCE_MIRROR_FUTURES_REPRESENTATIVE_PRODUCTS == (
        "jm",
        "ag",
        "cu",
        "m",
        "sc",
    )
    assert isinstance(MAIN_FORCE_MIRROR_FUTURES_REPRESENTATIVE_PRODUCTS, tuple)


def test_service_reader_requires_only_the_two_trading_day_read_seams() -> None:
    reader = type(
        "TradingDayReader",
        (),
        {
            "query_actual_dominant_trading_days": lambda self, request: request,
            "query_contract_trading_days": lambda self, request: request,
        },
    )()

    service = MainForceMirrorFuturesResearchService(reader)

    assert service._market_data is reader


def test_actual_dominant_uses_only_exact_trading_day_query_and_segments() -> None:
    bars = (_bar(trading_day=_DAY_ONE), _bar(trading_day=_DAY_TWO, hour=2))
    segments = (ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_TWO),)
    market_data = _FakeMarketData(dominant_result=_result(bars, segments))

    result = MainForceMirrorFuturesResearchService(market_data).run(_request())

    assert market_data.dominant_queries == [
        ActualDominantTradingDayQuery("jm", BarFrequency.H1, _DAY_ONE, _DAY_TWO)
    ]
    assert result.products == ("jm",)
    assert result.bars_valid_count == 2
    assert result.segment_reset_count == 0


def test_contract_uses_only_exact_trading_day_query_and_binds_requested_contract() -> (
    None
):
    bars = (_bar(trading_day=_DAY_ONE), _bar(trading_day=_DAY_TWO, hour=2))
    market_data = _FakeMarketData(contract_result=_result(bars))
    request = _request(
        series_kind=SeriesKind.CONTRACT,
        contract="JM2609",
    )

    result = MainForceMirrorFuturesResearchService(market_data).run(request)

    assert market_data.contract_queries == [
        ContractTradingDayQuery(
            "jm",
            "JM2609",
            BarFrequency.H1,
            _DAY_ONE,
            _DAY_TWO,
        )
    ]
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
    assert result.events_per_1000_caution_ready_bars == 166.666667
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
    assert one.reversal_returns == (0.1, 0.111111)
    assert one.warning_mfe == (0.15, 0.222222)
    assert one.warning_mae == (0.05, 0.111111)

    three = result.horizon_summary[3]
    assert three.sample_count == 2
    assert three.reversal_returns == (0.3, 0.333333)
    assert three.warning_mfe == (0.4, 0.444444)
    assert three.warning_mae == (0.1, 0.333333)

    for horizon in (5, 10):
        summary = result.horizon_summary[horizon]
        assert summary.sample_count == 0
        assert summary.reversal_returns == ()
        assert summary.warning_mfe == ()
        assert summary.warning_mae == ()


def test_horizon_summary_rounds_negative_values_and_normalizes_zero() -> None:
    event_bar = _bar(close="90", high="90", low="90")
    lower_bar = _bar(hour=2, close="80", high="81", low="79")
    flat_bar = _bar(hour=2, close="90", high="90", low="90")
    event = MainForceMirrorFuturesEvent(
        indicator_code="main_force_mirror_futures_v1",
        indicator_version="futures-research-v1",
        parameters_hash="f7fd0c9bce0b08d1",
        symbol="jm",
        series_kind=SeriesKind.ACTUAL_DOMINANT,
        physical_contract="JM2609",
        trading_day=_DAY_ONE,
        bar_end=event_bar.bar_end,
        caution_direction="short_chase_caution",
        score=70.0,
        reason_codes=("SHORT_LOWER_EXTREME",),
        state="long_liquidation",
    )

    negative = _summarize_horizons(
        events=(event,),
        bars=(event_bar, lower_bar),
        physical_contracts=("JM2609", "JM2609"),
    )[1]
    assert negative.reversal_returns == (-0.111111,)
    assert negative.warning_mfe == (-0.1,)
    assert negative.warning_mae == (0.122222,)

    zero = _summarize_horizons(
        events=(event,),
        bars=(event_bar, flat_bar),
        physical_contracts=("JM2609", "JM2609"),
    )[1]
    assert zero.reversal_returns == (0.0,)
    assert zero.warning_mfe == (0.0,)
    assert zero.warning_mae == (0.0,)
    assert all(str(value) != "-0.0" for values in (
        zero.reversal_returns,
        zero.warning_mfe,
        zero.warning_mae,
    ) for value in values)


def test_event_rate_uses_only_directional_events_and_is_null_without_ready_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars = tuple(
        _bar(trading_day=_DAY_ONE, hour=index + 1) for index in range(3)
    )
    market_data = _FakeMarketData(
        dominant_result=_result(
            bars,
            (ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),),
        )
    )
    monkeypatch.setattr(
        research_module,
        "compute_main_force_mirror_futures",
        lambda **_kwargs: _observation(
            3,
            cautions={0: "long_chase_caution", 1: "short_chase_caution"},
            conflicts=(2,),
        ),
    )

    result = MainForceMirrorFuturesResearchService(market_data).run(
        _request(through=_DAY_ONE)
    )

    assert result.event_count_long == 1
    assert result.event_count_short == 1
    assert result.conflict_count == 1
    assert result.events_per_1000_caution_ready_bars == 666.666667

    empty_market_data = _FakeMarketData(dominant_result=_result(()))
    monkeypatch.setattr(
        research_module,
        "compute_main_force_mirror_futures",
        lambda **_kwargs: _observation(0, cautions={}),
    )

    empty = MainForceMirrorFuturesResearchService(empty_market_data).run(_request())

    assert empty.bars_caution_ready_count == 0
    assert empty.events_per_1000_caution_ready_bars is None


def test_real_kernel_full_public_prefix_identity_and_only_outcomes_gain_samples() -> (
    None
):
    count = 41
    datetimes = [
        datetime(2026, 8, 17, tzinfo=UTC) + timedelta(hours=index)
        for index in range(count)
    ]
    close = [100.0 + index for index in range(count)]
    open_ = [value - 0.5 for value in close]
    high = [value + 1.0 for value in close]
    low = [value - 1.0 for value in close]
    volume = [1000.0 + index for index in range(count)]
    open_interest = [5000.0 + 10.0 * index for index in range(count)]
    open_[30] = 129.0
    high[30] = 134.0
    low[30] = 128.0
    close[30] = 131.0
    volume[30] = 5000.0
    open_interest[30] = 5270.0
    payload = {
        "datetimes": datetimes,
        "physical_contract": ["JM2609"] * count,
        "open_": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "open_interest": open_interest,
    }
    prefix_count = 31
    full_observation = research_module.compute_main_force_mirror_futures(**payload)
    prefix_observation = research_module.compute_main_force_mirror_futures(
        **{key: values[:prefix_count] for key, values in payload.items()}
    )

    for field in (
        "valid",
        "state_ready",
        "caution_ready",
        "ready",
        "reason",
        "caution_availability_reason",
        "state",
        "signed_score",
        "strength",
        "price_impulse",
        "clv",
        "volume_ratio",
        "delta_oi",
        "oi_impulse",
        "direction",
        "range_position",
        "long_open_pressure",
        "short_open_pressure",
        "long_caution_score",
        "short_caution_score",
        "caution",
        "caution_reason_codes",
    ):
        full_prefix = tuple(getattr(full_observation, field)[:prefix_count])
        prefix = tuple(getattr(prefix_observation, field))
        assert len(full_prefix) == len(prefix)
        for left, right in zip(full_prefix, prefix, strict=True):
            if left != left:  # NaN is the only public scalar unequal to itself.
                assert right != right
            else:
                assert left == right

    bars = tuple(
        CanonicalBar(
            bar_end=datetimes[index],
            trading_day=_DAY_ONE,
            open=Decimal(str(open_[index])),
            high=Decimal(str(high[index])),
            low=Decimal(str(low[index])),
            close=Decimal(str(close[index])),
            volume=Decimal(str(volume[index])),
            turnover=None,
            open_interest=Decimal(str(open_interest[index])),
        )
        for index in range(count)
    )
    request = _request(through=_DAY_ONE)
    full_events = _extract_events(
        request=request,
        bars=bars,
        physical_contracts=("JM2609",) * count,
        observation=full_observation,
    )
    prefix_events = _extract_events(
        request=request,
        bars=bars[:prefix_count],
        physical_contracts=("JM2609",) * prefix_count,
        observation=prefix_observation,
    )

    assert prefix_events
    assert (
        tuple(
            event
            for event in full_events
            if event.bar_end <= bars[prefix_count - 1].bar_end
        )
        == prefix_events
    )

    segment = (ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),)
    prefix_result = MainForceMirrorFuturesResearchService(
        _FakeMarketData(dominant_result=_result(bars[:prefix_count], segment))
    ).run(request)
    full_result = MainForceMirrorFuturesResearchService(
        _FakeMarketData(dominant_result=_result(bars, segment))
    ).run(request)

    assert full_result.event_count_long == prefix_result.event_count_long == 1
    assert full_result.event_count_short == prefix_result.event_count_short == 0
    assert full_result.score_distribution == prefix_result.score_distribution == (100,)
    assert (
        full_result.reason_code_distribution == prefix_result.reason_code_distribution
    )
    for horizon in (1, 3, 5, 10):
        assert prefix_result.horizon_summary[horizon].sample_count == 0
        assert full_result.horizon_summary[horizon].sample_count == 1


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
