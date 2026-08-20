from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data import composition
from app.market_data.domain import (
    ActualDominantTradingDayQuery,
    BarFrequency,
    CanonicalBar,
    MarketSeriesResult,
    ResolvedContractSegment,
)
from app.market_data.subing_calibration import build_research_samples, slope_direction
from app.market_data.subing_calibration_service import (
    CalibrationMode,
    CalibrationPhase,
    CalibrationResearchRequest,
    SlopeThresholds,
    SubingCalibrationResearchService,
)
from app.market_data.subing_research import (
    MacdCross,
    PriceSide,
    SubingFactorResult,
    SubingFactorSnapshot,
    SubingFactorStatus,
    calculate_subing_factor_series,
)


_DAY_ONE = date(2026, 8, 3)
_DAY_TWO = date(2026, 8, 4)
_ROLLOVER_THROUGH = date(2026, 8, 9)


class _FakeMarketData:
    def __init__(
        self,
        results: dict[tuple[str, BarFrequency], MarketSeriesResult],
    ) -> None:
        self._results = results
        self.queries: list[ActualDominantTradingDayQuery] = []

    def query_actual_dominant_trading_days(
        self,
        request: ActualDominantTradingDayQuery,
    ) -> MarketSeriesResult:
        self.queries.append(request)
        return self._results[(request.symbol, request.frequency)]


def test_slope_discovery_factorizes_each_rank1_segment_independently() -> None:
    """Catches rollover bars inheriting EMA/MACD state from the old contract."""
    old_segment = _bars(
        frequency=BarFrequency.M5,
        count=60,
        trading_day=_DAY_ONE,
        first_end=datetime(2026, 8, 3, 1, 5, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    short_new_segment = _bars(
        frequency=BarFrequency.M5,
        count=12,
        trading_day=_DAY_TWO,
        first_end=datetime(2026, 8, 4, 1, 5, tzinfo=UTC),
        first_close=Decimal("10000"),
    )
    market_data = _FakeMarketData(
        {
            ("jm", BarFrequency.M5): _result(
                old_segment + short_new_segment,
                (
                    ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),
                    ResolvedContractSegment("JM2701", _DAY_TWO, _DAY_TWO),
                ),
            )
        }
    )
    service = SubingCalibrationResearchService(market_data, products=("jm",))

    report = service.run(
        CalibrationResearchRequest(
            phase=CalibrationPhase.SLOPE,
            mode=CalibrationMode.DISCOVERY,
            frequency=BarFrequency.M5,
            since=_DAY_ONE,
            through=_DAY_TWO,
        )
    )

    expected_factors = calculate_subing_factor_series(
        old_segment,
        timeframe=BarFrequency.M5,
        contract="JM2609",
        segment_start_trading_day=_DAY_ONE,
        latest_bar_source="canonical",
    )
    expected_samples = build_research_samples(
        expected_factors,
        old_segment,
        direction_selector=slope_direction,
    )
    assert report.report.product_sample_counts == {"jm": len(expected_samples)}
    assert market_data.queries[0] == ActualDominantTradingDayQuery(
        "jm", BarFrequency.M5, _DAY_ONE, _DAY_TWO
    )


def test_service_uses_exact_trading_day_query() -> None:
    bars = _bars(
        frequency=BarFrequency.M5,
        count=1,
        trading_day=_DAY_ONE,
        first_end=datetime(2026, 8, 3, 1, 5, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    market_data = _FakeMarketData(
        {
            ("jm", BarFrequency.M5): _result(
                bars,
                (ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),),
            )
        }
    )

    SubingCalibrationResearchService(market_data, products=("jm",)).run(
        CalibrationResearchRequest(
            CalibrationPhase.SLOPE,
            CalibrationMode.DISCOVERY,
            BarFrequency.M5,
            _DAY_ONE,
            _DAY_ONE,
        )
    )

    assert market_data.queries == [
        ActualDominantTradingDayQuery("jm", BarFrequency.M5, _DAY_ONE, _DAY_ONE),
        ActualDominantTradingDayQuery("jm", BarFrequency.M5, _DAY_ONE, _DAY_ONE),
    ]


def test_intraday_zero_band_uses_latest_confirmed_matching_companion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches future or direction-conflicting companions admitting Cohort B rows."""
    primary = _bars(
        frequency=BarFrequency.M5,
        count=10,
        trading_day=_DAY_ONE,
        first_end=datetime(2026, 8, 3, 1, 5, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    companion = _bars(
        frequency=BarFrequency.M15,
        count=2,
        trading_day=_DAY_ONE,
        first_end=datetime(2026, 8, 3, 1, 10, tzinfo=UTC),
        first_close=Decimal("200"),
    )
    segments = (ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),)
    market_data = _FakeMarketData(
        {
            ("jm", BarFrequency.M5): _result(primary, segments),
            ("jm", BarFrequency.M15): _result(companion, segments),
        }
    )

    def factors(
        bars: tuple[CanonicalBar, ...],
        *,
        timeframe: BarFrequency,
        contract: str,
        segment_start_trading_day: date,
        latest_bar_source: str,
    ) -> tuple[SubingFactorResult, ...]:
        del latest_bar_source
        if timeframe is BarFrequency.M5:
            return tuple(
                _factor(
                    bar,
                    timeframe=timeframe,
                    contract=contract,
                    segment_start=segment_start_trading_day,
                    cross=(MacdCross.GOLDEN if index in {2, 6} else MacdCross.NONE),
                    zero_distance_bps=Decimal(str(10 + index)),
                    volume_ratio=Decimal("3"),
                )
                for index, bar in enumerate(bars)
            )
        return (
            _factor(
                bars[0],
                timeframe=timeframe,
                contract=contract,
                segment_start=segment_start_trading_day,
                price_side=PriceSide.BELOW,
                slope5=Decimal("-2"),
                slope10=Decimal("-1"),
            ),
            _factor(
                bars[1],
                timeframe=timeframe,
                contract=contract,
                segment_start=segment_start_trading_day,
            ),
        )

    monkeypatch.setattr(
        "app.market_data.subing_calibration_service.calculate_subing_factor_series",
        factors,
    )
    service = SubingCalibrationResearchService(market_data, products=("jm",))

    result = service.run(
        CalibrationResearchRequest(
            phase=CalibrationPhase.ZERO_BAND,
            mode=CalibrationMode.VALIDATION,
            frequency=BarFrequency.M5,
            since=_DAY_ONE,
            through=_DAY_ONE,
            slope_thresholds=SlopeThresholds(
                m5=Decimal("1"),
                m15=Decimal("1"),
            ),
            zero_band_bps=Decimal("20"),
        )
    )

    assert result.cohorts["A"].sample_count == 2
    assert result.cohorts["B"].sample_count == 1
    assert result.cohorts["B"].threshold_evaluation is not None
    assert result.cohorts["B"].threshold_evaluation.sample_count == 1
    assert [query.frequency for query in market_data.queries] == [
        BarFrequency.M5,
        BarFrequency.M15,
    ]


def test_companion_alignment_ignores_latest_confirmed_other_segment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches time-only alignment accepting a companion from another rank1 identity."""
    primary = _bars(
        frequency=BarFrequency.M5,
        count=1,
        trading_day=_DAY_ONE,
        first_end=datetime(2026, 8, 3, 1, 20, tzinfo=UTC),
        first_close=Decimal("100"),
    )
    companion = _bars(
        frequency=BarFrequency.M15,
        count=1,
        trading_day=_DAY_ONE,
        first_end=datetime(2026, 8, 3, 1, 15, tzinfo=UTC),
        first_close=Decimal("200"),
    )
    market_data = _FakeMarketData(
        {
            ("jm", BarFrequency.M5): _result(
                primary,
                (ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),),
            ),
            ("jm", BarFrequency.M15): _result(
                companion,
                (ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),),
            ),
        }
    )

    def factors(
        bars: tuple[CanonicalBar, ...],
        *,
        timeframe: BarFrequency,
        contract: str,
        segment_start_trading_day: date,
        latest_bar_source: str,
    ) -> tuple[SubingFactorResult, ...]:
        del latest_bar_source
        return (
            _factor(
                bars[0],
                timeframe=timeframe,
                contract=(contract if timeframe is BarFrequency.M5 else "JM2701"),
                segment_start=(
                    segment_start_trading_day
                    if timeframe is BarFrequency.M5
                    else _DAY_TWO
                ),
                cross=(
                    MacdCross.GOLDEN if timeframe is BarFrequency.M5 else MacdCross.NONE
                ),
                volume_ratio=Decimal("3"),
            ),
        )

    monkeypatch.setattr(
        "app.market_data.subing_calibration_service.calculate_subing_factor_series",
        factors,
    )

    result = SubingCalibrationResearchService(market_data, products=("jm",)).run(
        CalibrationResearchRequest(
            CalibrationPhase.ZERO_BAND,
            CalibrationMode.VALIDATION,
            BarFrequency.M5,
            _DAY_ONE,
            _DAY_ONE,
            slope_thresholds=SlopeThresholds(Decimal("1"), Decimal("1")),
            zero_band_bps=Decimal("20"),
        )
    )

    assert result.cohorts["A"].sample_count == 1
    assert result.cohorts["B"].sample_count == 0


@pytest.mark.parametrize(
    "frequency",
    (BarFrequency.M5, BarFrequency.M15, BarFrequency.D1),
)
def test_slope_labels_never_consume_an_insufficient_next_rank1_segment(
    frequency: BarFrequency,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a pre-roll entry labeling the next contract's large price gap."""
    market_data = _rollover_market_data(frequency)
    monkeypatch.setattr(
        "app.market_data.subing_calibration_service.calculate_subing_factor_series",
        _rollover_factors,
    )

    result = SubingCalibrationResearchService(market_data, products=("jm",)).run(
        CalibrationResearchRequest(
            CalibrationPhase.SLOPE,
            CalibrationMode.VALIDATION,
            frequency,
            _DAY_ONE,
            _ROLLOVER_THROUGH,
            slope_threshold_bps=Decimal("1"),
        )
    )

    evaluation = result.report.threshold_evaluation
    assert evaluation is not None
    assert evaluation.sample_count == 4
    assert evaluation.horizons[3].sample_count == 1
    assert evaluation.horizons[3].median_directional_return_bps == Decimal("300")


@pytest.mark.parametrize(
    "frequency",
    (BarFrequency.M5, BarFrequency.M15, BarFrequency.D1),
)
def test_zero_band_cohorts_keep_future_labels_inside_each_rank1_segment(
    frequency: BarFrequency,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches Cohort A or B outcomes crossing into insufficient rollover warm-up."""
    market_data = _rollover_market_data(frequency)
    monkeypatch.setattr(
        "app.market_data.subing_calibration_service.calculate_subing_factor_series",
        _rollover_factors,
    )
    inputs: dict[str, object]
    if frequency is BarFrequency.D1:
        inputs = {"slope_threshold_bps": Decimal("1")}
    else:
        inputs = {"slope_thresholds": SlopeThresholds(Decimal("1"), Decimal("1"))}

    result = SubingCalibrationResearchService(market_data, products=("jm",)).run(
        CalibrationResearchRequest(
            CalibrationPhase.ZERO_BAND,
            CalibrationMode.VALIDATION,
            frequency,
            _DAY_ONE,
            _ROLLOVER_THROUGH,
            zero_band_bps=Decimal("20"),
            **inputs,  # type: ignore[arg-type]
        )
    )

    for cohort_name in ("A", "B"):
        evaluation = result.cohorts[cohort_name].threshold_evaluation
        assert evaluation is not None
        assert evaluation.sample_count == 4
        assert evaluation.horizons[3].sample_count == 1
        assert evaluation.horizons[3].median_directional_return_bps == Decimal("300")


def test_slope_discovery_uses_equal_product_weight_and_two_read_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches pooled rows overweighting a liquid product or reusing discovery rows."""
    jm = _bars(
        frequency=BarFrequency.M5,
        count=5,
        trading_day=_DAY_ONE,
        first_end=datetime(2026, 8, 3, 1, 5, tzinfo=UTC),
        first_close=Decimal("101"),
    )
    rb = _bars(
        frequency=BarFrequency.M5,
        count=1,
        trading_day=_DAY_ONE,
        first_end=datetime(2026, 8, 3, 1, 5, tzinfo=UTC),
        first_close=Decimal("200"),
    )
    segment = (ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),)
    market_data = _FakeMarketData(
        {
            ("jm", BarFrequency.M5): _result(jm, segment),
            ("rb", BarFrequency.M5): _result(
                rb,
                (ResolvedContractSegment("RB2610", _DAY_ONE, _DAY_ONE),),
            ),
        }
    )

    def factors(
        bars: tuple[CanonicalBar, ...],
        *,
        timeframe: BarFrequency,
        contract: str,
        segment_start_trading_day: date,
        latest_bar_source: str,
    ) -> tuple[SubingFactorResult, ...]:
        del latest_bar_source
        base = Decimal("100") if contract.startswith("JM") else Decimal("100")
        return tuple(
            _factor(
                bar,
                timeframe=timeframe,
                contract=contract,
                segment_start=segment_start_trading_day,
                slope5=bar.close - base,
            )
            for bar in bars
        )

    monkeypatch.setattr(
        "app.market_data.subing_calibration_service.calculate_subing_factor_series",
        factors,
    )

    result = SubingCalibrationResearchService(
        market_data,
        products=("jm", "rb"),
    ).run(
        CalibrationResearchRequest(
            CalibrationPhase.SLOPE,
            CalibrationMode.DISCOVERY,
            BarFrequency.M5,
            _DAY_ONE,
            _DAY_ONE,
        )
    )

    assert result.report.candidate_thresholds == (
        Decimal("50.7"),
        Decimal("50.9"),
        Decimal("51.1"),
    )
    assert result.report.product_sample_counts == {"jm": 5, "rb": 1}
    assert len(result.report.candidate_evaluations) == 3
    assert [(query.symbol, query.frequency) for query in market_data.queries] == [
        ("jm", BarFrequency.M5),
        ("rb", BarFrequency.M5),
        ("jm", BarFrequency.M5),
        ("rb", BarFrequency.M5),
    ]


def test_zero_band_discovery_uses_cohort_b_product_quantiles_and_reports_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches zero-band candidates coming from pooled or Cohort A-only rows."""
    jm_primary = _bars(
        frequency=BarFrequency.M5,
        count=5,
        trading_day=_DAY_ONE,
        first_end=datetime(2026, 8, 3, 1, 5, tzinfo=UTC),
        first_close=Decimal("101"),
    )
    rb_primary = _bars(
        frequency=BarFrequency.M5,
        count=1,
        trading_day=_DAY_ONE,
        first_end=datetime(2026, 8, 3, 1, 5, tzinfo=UTC),
        first_close=Decimal("200"),
    )
    jm_companion = _bars(
        frequency=BarFrequency.M15,
        count=1,
        trading_day=_DAY_ONE,
        first_end=datetime(2026, 8, 3, 1, 0, tzinfo=UTC),
        first_close=Decimal("300"),
    )
    rb_companion = _bars(
        frequency=BarFrequency.M15,
        count=1,
        trading_day=_DAY_ONE,
        first_end=datetime(2026, 8, 3, 1, 0, tzinfo=UTC),
        first_close=Decimal("400"),
    )
    market_data = _FakeMarketData(
        {
            ("jm", BarFrequency.M5): _result(
                jm_primary,
                (ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),),
            ),
            ("jm", BarFrequency.M15): _result(
                jm_companion,
                (ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),),
            ),
            ("rb", BarFrequency.M5): _result(
                rb_primary,
                (ResolvedContractSegment("RB2610", _DAY_ONE, _DAY_ONE),),
            ),
            ("rb", BarFrequency.M15): _result(
                rb_companion,
                (ResolvedContractSegment("RB2610", _DAY_ONE, _DAY_ONE),),
            ),
        }
    )

    def factors(
        bars: tuple[CanonicalBar, ...],
        *,
        timeframe: BarFrequency,
        contract: str,
        segment_start_trading_day: date,
        latest_bar_source: str,
    ) -> tuple[SubingFactorResult, ...]:
        del latest_bar_source
        primary = timeframe is BarFrequency.M5
        return tuple(
            _factor(
                bar,
                timeframe=timeframe,
                contract=contract,
                segment_start=segment_start_trading_day,
                cross=MacdCross.GOLDEN if primary else MacdCross.NONE,
                zero_distance_bps=(
                    bar.close - Decimal("100") if primary else Decimal("0")
                ),
                volume_ratio=Decimal("3"),
            )
            for bar in bars
        )

    monkeypatch.setattr(
        "app.market_data.subing_calibration_service.calculate_subing_factor_series",
        factors,
    )

    result = SubingCalibrationResearchService(
        market_data,
        products=("jm", "rb"),
    ).run(
        CalibrationResearchRequest(
            CalibrationPhase.ZERO_BAND,
            CalibrationMode.DISCOVERY,
            BarFrequency.M5,
            _DAY_ONE,
            _DAY_ONE,
            slope_thresholds=SlopeThresholds(Decimal("1"), Decimal("1")),
        )
    )

    assert result.report.candidate_thresholds == (
        Decimal("50.9"),
        Decimal("51.3"),
        Decimal("51.7"),
    )
    assert (
        result.cohorts["A"].candidate_thresholds == result.report.candidate_thresholds
    )
    assert (
        result.cohorts["B"].candidate_thresholds == result.report.candidate_thresholds
    )
    assert result.cohorts["A"].sample_count == 6
    assert result.cohorts["B"].sample_count == 6
    assert len(market_data.queries) == 8


def test_daily_cohort_b_has_no_companion_or_volume_hard_condition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches intraday companion/volume rules leaking into the independent daily lane."""
    daily = (_bar(datetime(2026, 8, 3, 7, tzinfo=UTC), _DAY_ONE, Decimal("100")),)
    market_data = _FakeMarketData(
        {
            ("jm", BarFrequency.D1): _result(
                daily,
                (ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),),
            )
        }
    )

    def factors(
        bars: tuple[CanonicalBar, ...],
        *,
        timeframe: BarFrequency,
        contract: str,
        segment_start_trading_day: date,
        latest_bar_source: str,
    ) -> tuple[SubingFactorResult, ...]:
        del latest_bar_source
        return tuple(
            _factor(
                bar,
                timeframe=timeframe,
                contract=contract,
                segment_start=segment_start_trading_day,
                cross=MacdCross.GOLDEN,
                volume_ratio=None,
            )
            for bar in bars
        )

    monkeypatch.setattr(
        "app.market_data.subing_calibration_service.calculate_subing_factor_series",
        factors,
    )

    result = SubingCalibrationResearchService(market_data, products=("jm",)).run(
        CalibrationResearchRequest(
            CalibrationPhase.ZERO_BAND,
            CalibrationMode.VALIDATION,
            BarFrequency.D1,
            _DAY_ONE,
            _DAY_ONE,
            slope_threshold_bps=Decimal("1"),
            zero_band_bps=Decimal("20"),
        )
    )

    assert result.cohorts["B"].sample_count == 1
    assert [query.frequency for query in market_data.queries] == [BarFrequency.D1]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"slope_threshold_bps": Decimal("1")},
        {"phase": CalibrationPhase.SLOPE, "mode": CalibrationMode.VALIDATION},
        {"phase": CalibrationPhase.ZERO_BAND},
        {
            "phase": CalibrationPhase.ZERO_BAND,
            "slope_thresholds": SlopeThresholds(Decimal("1"), Decimal("1")),
            "mode": CalibrationMode.VALIDATION,
        },
    ],
)
def test_request_rejects_threshold_inputs_outside_the_phase_mode_matrix(
    kwargs: dict[str, object],
) -> None:
    """Catches discovery choosing values or validation silently omitting frozen values."""
    values: dict[str, object] = {
        "phase": CalibrationPhase.SLOPE,
        "mode": CalibrationMode.DISCOVERY,
        "frequency": BarFrequency.M5,
        "since": _DAY_ONE,
        "through": _DAY_ONE,
    }
    values.update(kwargs)

    with pytest.raises(ValueError):
        CalibrationResearchRequest(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [Decimal("-1"), Decimal("NaN")])
def test_thresholds_reject_negative_or_non_finite_values(value: Decimal) -> None:
    with pytest.raises(ValueError):
        SlopeThresholds(value, Decimal("1"))


def test_composition_builder_constructs_only_market_data_calibration_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches the builder accidentally constructing MarketRead/Redis/provider paths."""
    daily = (_bar(datetime(2026, 8, 3, 7, tzinfo=UTC), _DAY_ONE, Decimal("100")),)
    market_data = _FakeMarketData(
        {
            ("jm", BarFrequency.D1): _result(
                daily,
                (ResolvedContractSegment("JM2609", _DAY_ONE, _DAY_ONE),),
            )
        }
    )
    monkeypatch.setattr(
        composition, "build_market_data_service", lambda session: market_data
    )
    monkeypatch.setattr(composition, "load_active_products", lambda: ("jm",))
    monkeypatch.setattr(
        composition,
        "build_market_read_service",
        lambda session: pytest.fail("MarketReadService must not be constructed"),
    )

    service = composition.build_subing_calibration_research_service(object())
    result = service.run(
        CalibrationResearchRequest(
            CalibrationPhase.SLOPE,
            CalibrationMode.DISCOVERY,
            BarFrequency.D1,
            _DAY_ONE,
            _DAY_ONE,
        )
    )

    assert result.products == ("jm",)


def _bars(
    *,
    frequency: BarFrequency,
    count: int,
    trading_day: date,
    first_end: datetime,
    first_close: Decimal,
) -> tuple[CanonicalBar, ...]:
    minutes = {BarFrequency.M5: 5, BarFrequency.M15: 15}[frequency]
    return tuple(
        _bar(
            first_end + timedelta(minutes=minutes * index),
            trading_day,
            first_close + Decimal(index),
        )
        for index in range(count)
    )


def _bar(bar_end: datetime, trading_day: date, close: Decimal) -> CanonicalBar:
    return CanonicalBar(
        bar_end=bar_end,
        trading_day=trading_day,
        open=close,
        high=close + Decimal("1"),
        low=close - Decimal("1"),
        close=close,
        volume=Decimal("100"),
        turnover=None,
        open_interest=None,
    )


def _result(
    bars: tuple[CanonicalBar, ...],
    segments: tuple[ResolvedContractSegment, ...],
) -> MarketSeriesResult:
    return MarketSeriesResult(
        request_identity={},
        bars=bars,
        coverage=(bars[0].bar_end, bars[-1].bar_end),
        resolved_contract_segments=segments,
    )


def _rollover_market_data(frequency: BarFrequency) -> _FakeMarketData:
    results = {("jm", frequency): _rollover_result(frequency)}
    if frequency in {BarFrequency.M5, BarFrequency.M15}:
        companion = (
            BarFrequency.M15 if frequency is BarFrequency.M5 else BarFrequency.M5
        )
        results[("jm", companion)] = _rollover_result(companion, companion=True)
    return _FakeMarketData(results)


def _rollover_result(
    frequency: BarFrequency,
    *,
    companion: bool = False,
) -> MarketSeriesResult:
    if companion:
        minute = 55 if frequency is BarFrequency.M15 else 70
        old = (
            _bar(
                datetime(2026, 8, 3, 0, tzinfo=UTC) + timedelta(minutes=minute),
                _DAY_ONE,
                Decimal("200"),
            ),
        )
        new = (
            _bar(
                datetime(2026, 8, 4, 0, tzinfo=UTC) + timedelta(minutes=minute),
                _DAY_TWO,
                Decimal("20000"),
            ),
        )
    elif frequency is BarFrequency.D1:
        old = tuple(
            _bar(
                datetime(2026, 8, 3 + index, 7, tzinfo=UTC),
                _DAY_ONE + timedelta(days=index),
                Decimal(100 + index),
            )
            for index in range(4)
        )
        new = tuple(
            _bar(
                datetime(2026, 8, 7 + index, 7, tzinfo=UTC),
                date(2026, 8, 7) + timedelta(days=index),
                Decimal(10000 + index),
            )
            for index in range(3)
        )
    else:
        first_minute = 5 if frequency is BarFrequency.M5 else 15
        old = _bars(
            frequency=frequency,
            count=4,
            trading_day=_DAY_ONE,
            first_end=datetime(2026, 8, 3, 1, first_minute, tzinfo=UTC),
            first_close=Decimal("100"),
        )
        new = _bars(
            frequency=frequency,
            count=3,
            trading_day=_DAY_TWO,
            first_end=datetime(2026, 8, 4, 1, first_minute, tzinfo=UTC),
            first_close=Decimal("10000"),
        )
    old_end = date(2026, 8, 6) if frequency is BarFrequency.D1 else _DAY_ONE
    new_start = date(2026, 8, 7) if frequency is BarFrequency.D1 else _DAY_TWO
    new_end = date(2026, 8, 9) if frequency is BarFrequency.D1 else _DAY_TWO
    return _result(
        old + new,
        (
            ResolvedContractSegment("JM2609", _DAY_ONE, old_end),
            ResolvedContractSegment("JM2701", new_start, new_end),
        ),
    )


def _rollover_factors(
    bars: tuple[CanonicalBar, ...],
    *,
    timeframe: BarFrequency,
    contract: str,
    segment_start_trading_day: date,
    latest_bar_source: str,
) -> tuple[SubingFactorResult, ...]:
    del latest_bar_source
    if contract == "JM2701":
        return tuple(
            SubingFactorResult(SubingFactorStatus.INSUFFICIENT_DATA, None)
            for _bar_value in bars
        )
    return tuple(
        _factor(
            bar,
            timeframe=timeframe,
            contract=contract,
            segment_start=segment_start_trading_day,
            cross=MacdCross.GOLDEN,
            volume_ratio=Decimal("3"),
        )
        for bar in bars
    )


def _factor(
    bar: CanonicalBar,
    *,
    timeframe: BarFrequency,
    contract: str,
    segment_start: date,
    price_side: PriceSide = PriceSide.ABOVE,
    slope5: Decimal = Decimal("2"),
    slope10: Decimal = Decimal("1"),
    cross: MacdCross = MacdCross.NONE,
    zero_distance_bps: Decimal = Decimal("10"),
    volume_ratio: Decimal | None = Decimal("1"),
) -> SubingFactorResult:
    return SubingFactorResult(
        status=SubingFactorStatus.READY,
        snapshot=SubingFactorSnapshot(
            timeframe=timeframe,
            bar_end=bar.bar_end,
            trading_day=bar.trading_day,
            contract=contract,
            segment_start_trading_day=segment_start,
            bar_source="canonical",
            close=bar.close,
            ema21=bar.close - Decimal("1"),
            price_side=price_side,
            slope_5_raw=Decimal("1"),
            slope_10_raw=Decimal("1"),
            slope_5_bps_per_bar=slope5,
            slope_10_bps_per_bar=slope10,
            macd_dif=Decimal("1"),
            macd_dea=Decimal("0"),
            macd_histogram=Decimal("2"),
            macd_cross=cross,
            macd_cross_level=Decimal("0.5"),
            macd_zero_distance_abs=Decimal("0.5"),
            macd_zero_distance_bps=zero_distance_bps,
            volume=bar.volume,
            previous_volume=bar.volume,
            volume_ratio_prev=volume_ratio,
        ),
    )
