from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data import subing_calibration as calibration_module
from app.market_data.subing_calibration import (
    DirectionalSide,
    build_outcomes_at,
    build_research_samples,
    candidate_quantiles,
    evaluate_threshold,
    slope_direction,
)
from app.market_data.subing_research import (
    MacdCross,
    PriceSide,
    SubingFactorResult,
    SubingFactorSnapshot,
    SubingFactorStatus,
)


_DAY = date(2026, 8, 3)
_SEGMENT_START = date(2026, 8, 1)
_START = datetime(2026, 8, 3, 1, tzinfo=UTC)


def _bar(
    index: int,
    *,
    close: str,
    high: str,
    low: str,
    trading_day: date = _DAY,
) -> CanonicalBar:
    value = Decimal(close)
    return CanonicalBar(
        bar_end=_START + timedelta(minutes=5 * index),
        trading_day=trading_day,
        open=value,
        high=Decimal(high),
        low=Decimal(low),
        close=value,
        volume=Decimal("100"),
        turnover=None,
        open_interest=None,
    )


def _factor(
    bar: CanonicalBar,
    *,
    timeframe: BarFrequency = BarFrequency.M5,
    contract: str = "JM2609",
    segment_start: date = _SEGMENT_START,
    ema21: str = "90",
    slope5: str = "2",
    slope10: str = "1",
    price_side: PriceSide = PriceSide.ABOVE,
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
            ema21=Decimal(ema21),
            price_side=price_side,
            slope_5_raw=Decimal("1"),
            slope_10_raw=Decimal("1"),
            slope_5_bps_per_bar=Decimal(slope5),
            slope_10_bps_per_bar=Decimal(slope10),
            macd_dif=Decimal("1"),
            macd_dea=Decimal("0"),
            macd_histogram=Decimal("2"),
            macd_cross=MacdCross.GOLDEN,
            macd_cross_level=Decimal("0.5"),
            macd_zero_distance_abs=Decimal("0.5"),
            macd_zero_distance_bps=Decimal("50"),
            volume=Decimal("100"),
            previous_volume=Decimal("100"),
            volume_ratio_prev=Decimal("1"),
        ),
    )


def _series(*, timeframe: BarFrequency = BarFrequency.M5):
    bars = (
        _bar(0, close="100", high="101", low="99"),
        _bar(1, close="101", high="103", low="99"),
        _bar(2, close="102", high="105", low="98"),
        _bar(3, close="103", high="104", low="100"),
        _bar(4, close="104", high="106", low="101"),
        _bar(5, close="105", high="107", low="102"),
        _bar(6, close="106", high="108", low="103"),
        _bar(7, close="107", high="109", low="104"),
        _bar(8, close="108", high="110", low="105"),
    )
    return bars, tuple(_factor(bar, timeframe=timeframe) for bar in bars)


@pytest.mark.parametrize(
    ("horizon", "long_return", "long_mfe", "long_mae", "short_return", "short_mfe", "short_mae"),
    (
        (3, "300", "500", "-200", "-300", "200", "-500"),
        (5, "500", "700", "-200", "-500", "200", "-700"),
        (8, "800", "1000", "-200", "-800", "200", "-1000"),
    ),
)
@pytest.mark.parametrize(
    "timeframe",
    (BarFrequency.M5, BarFrequency.M15, BarFrequency.D1),
)
def test_build_outcomes_uses_exact_long_and_short_formulas(
    timeframe: BarFrequency,
    horizon: int,
    long_return: str,
    long_mfe: str,
    long_mae: str,
    short_return: str,
    short_mfe: str,
    short_mae: str,
) -> None:
    bars, factors = _series(timeframe=timeframe)

    long_outcome = build_outcomes_at(
        factors, bars, index=0, direction=DirectionalSide.LONG, horizons=(horizon,)
    )[horizon]
    short_outcome = build_outcomes_at(
        factors, bars, index=0, direction=DirectionalSide.SHORT, horizons=(horizon,)
    )[horizon]

    assert long_outcome is not None
    assert long_outcome.directional_return_bps == Decimal(long_return)
    assert long_outcome.mfe_bps == Decimal(long_mfe)
    assert long_outcome.mae_bps == Decimal(long_mae)
    assert long_outcome.ema21_failure is False
    assert short_outcome is not None
    assert short_outcome.directional_return_bps == Decimal(short_return)
    assert short_outcome.mfe_bps == Decimal(short_mfe)
    assert short_outcome.mae_bps == Decimal(short_mae)


@pytest.mark.parametrize(
    ("direction", "future_ema21"),
    (
        (DirectionalSide.LONG, "102"),
        (DirectionalSide.SHORT, "100"),
    ),
)
def test_ema21_failure_uses_direction_and_ready_future_snapshots(
    direction: DirectionalSide,
    future_ema21: str,
) -> None:
    bars, factors = _series()
    failed = replace(factors[1].snapshot, ema21=Decimal(future_ema21))
    assert failed is not None

    outcome = build_outcomes_at(
        (
            factors[0],
            SubingFactorResult(SubingFactorStatus.READY, failed),
            *factors[2:],
        ),
        bars,
        index=0,
        direction=direction,
        horizons=(3,),
    )[3]

    assert outcome is not None
    assert outcome.ema21_failure is True


def test_non_ready_future_factor_does_not_erase_price_outcome() -> None:
    bars, factors = _series()
    with_gap = (
        factors[0],
        SubingFactorResult(SubingFactorStatus.INSUFFICIENT_DATA, None),
        *factors[2:],
    )

    outcome = build_outcomes_at(
        with_gap,
        bars,
        index=0,
        direction=DirectionalSide.LONG,
        horizons=(3,),
    )[3]

    assert outcome is not None
    assert outcome.directional_return_bps == Decimal("300")
    assert outcome.mfe_bps == Decimal("500")
    assert outcome.mae_bps == Decimal("-200")
    assert outcome.ema21_failure is False


def test_entry_factor_must_match_bar_trading_day() -> None:
    bars, factors = _series(timeframe=BarFrequency.D1)
    wrong_entry = replace(factors[0].snapshot, trading_day=date(2026, 8, 2))
    assert wrong_entry is not None

    with pytest.raises(ValueError, match="entry factor must be ready and aligned"):
        build_outcomes_at(
            (
                SubingFactorResult(SubingFactorStatus.READY, wrong_entry),
                *factors[1:],
            ),
            bars,
            index=0,
            direction=DirectionalSide.LONG,
            horizons=(3,),
        )


def test_entry_timeframe_must_be_supported_by_calibration() -> None:
    bars, factors = _series(timeframe=BarFrequency.M30)

    with pytest.raises(ValueError, match="timeframe"):
        build_outcomes_at(
            factors,
            bars,
            index=0,
            direction=DirectionalSide.LONG,
            horizons=(3,),
        )


def test_future_ready_factor_with_mixed_timeframe_invalidates_horizon() -> None:
    bars, factors = _series()
    wrong_timeframe = replace(factors[2].snapshot, timeframe=BarFrequency.M15)
    assert wrong_timeframe is not None

    outcome = build_outcomes_at(
        (
            *factors[:2],
            SubingFactorResult(SubingFactorStatus.READY, wrong_timeframe),
            *factors[3:],
        ),
        bars,
        index=0,
        direction=DirectionalSide.LONG,
        horizons=(3,),
    )[3]

    assert outcome is None


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("bar_end", _START + timedelta(minutes=11)),
        ("trading_day", date(2026, 8, 4)),
        ("close", Decimal("999")),
        ("timeframe", BarFrequency.M15),
        ("contract", "JM2701"),
        ("segment_start_trading_day", date(2026, 8, 2)),
    ),
)
def test_future_ready_factor_identity_mismatch_invalidates_horizon(
    field: str,
    value: object,
) -> None:
    bars, factors = _series()
    snapshot = factors[2].snapshot
    assert snapshot is not None
    wrong_identity = replace(snapshot, **{field: value})

    outcome = build_outcomes_at(
        (
            *factors[:2],
            SubingFactorResult(SubingFactorStatus.READY, wrong_identity),
            *factors[3:],
        ),
        bars,
        index=0,
        direction=DirectionalSide.LONG,
        horizons=(3,),
    )[3]

    assert outcome is None


def test_all_non_ready_future_factors_keep_price_outcome_and_no_ema_failure() -> None:
    bars, factors = _series()
    insufficient = SubingFactorResult(SubingFactorStatus.INSUFFICIENT_DATA, None)

    outcome = build_outcomes_at(
        (factors[0], insufficient, insufficient, insufficient, *factors[4:]),
        bars,
        index=0,
        direction=DirectionalSide.SHORT,
        horizons=(3,),
    )[3]

    assert outcome is not None
    assert outcome.directional_return_bps == Decimal("-300")
    assert outcome.mfe_bps == Decimal("200")
    assert outcome.mae_bps == Decimal("-500")
    assert outcome.ema21_failure is False


@pytest.mark.parametrize("timeframe", (BarFrequency.M5, BarFrequency.M15))
def test_intraday_outcomes_never_cross_trading_day_or_rank1_segment(
    timeframe: BarFrequency,
) -> None:
    bars, factors = _series(timeframe=timeframe)
    next_day_bar = replace(bars[3], trading_day=date(2026, 8, 4))
    next_day_factors = tuple(
        _factor(bar, timeframe=timeframe)
        for bar in (*bars[:3], next_day_bar, *bars[4:])
    )
    next_segment = _factor(
        bars[3],
        timeframe=timeframe,
        contract="JM2701",
        segment_start=date(2026, 8, 4),
    )

    day_poison = build_outcomes_at(
        next_day_factors,
        (*bars[:3], next_day_bar, *bars[4:]),
        index=0,
        direction=DirectionalSide.LONG,
        horizons=(3,),
    )
    segment_poison = build_outcomes_at(
        (*factors[:3], next_segment, *factors[4:]),
        bars,
        index=0,
        direction=DirectionalSide.LONG,
        horizons=(3,),
    )

    assert day_poison[3] is None
    assert segment_poison[3] is None


def test_daily_outcomes_may_cross_day_but_not_rank1_segment() -> None:
    bars, factors = _series(timeframe=BarFrequency.D1)
    later = tuple(
        replace(bar, trading_day=_DAY + timedelta(days=index))
        for index, bar in enumerate(bars)
    )
    daily_factors = tuple(
        _factor(bar, timeframe=BarFrequency.D1) for bar in later
    )

    outcomes = build_outcomes_at(
        daily_factors,
        later,
        index=0,
        direction=DirectionalSide.LONG,
        horizons=(3,),
    )
    segment_snapshot = daily_factors[3].snapshot
    assert segment_snapshot is not None
    changed_segment = replace(
        segment_snapshot,
        contract="JM2701",
        segment_start_trading_day=date(2026, 8, 6),
    )
    poison = build_outcomes_at(
        (
            *daily_factors[:3],
            SubingFactorResult(SubingFactorStatus.READY, changed_segment),
            *daily_factors[4:],
        ),
        later,
        index=0,
        direction=DirectionalSide.LONG,
        horizons=(3,),
    )

    assert outcomes[3] is not None
    assert poison[3] is None


def test_research_samples_use_only_the_explicit_direction_selector() -> None:
    bars, factors = _series()

    samples = build_research_samples(
        factors,
        bars,
        horizons=(3, 5, 8),
        direction_selector=(
            lambda index, factor: DirectionalSide.LONG if index == 0 else None
        ),
    )

    assert len(samples) == 1
    assert samples[0].direction is DirectionalSide.LONG
    assert samples[0].studied_value == Decimal("2")
    assert samples[0].outcomes[3] is not None
    assert samples[0].outcomes[3].directional_return_bps == Decimal("300")
    assert samples[0].outcomes[5] is not None
    assert samples[0].outcomes[8] is not None


def test_research_samples_fail_closed_without_direction_selector() -> None:
    bars, factors = _series()

    with pytest.raises(TypeError):
        build_research_samples(factors, bars, horizons=(3,))  # type: ignore[call-arg]


def test_slope_selector_excludes_wrong_side_or_disagreeing_slopes() -> None:
    bars, factors = _series()
    below = replace(
        factors[1].snapshot,
        price_side=PriceSide.BELOW,
        slope_5_bps_per_bar=Decimal("-2"),
        slope_10_bps_per_bar=Decimal("-1"),
    )
    assert below is not None
    disagreeing = replace(
        factors[2].snapshot,
        price_side=PriceSide.ABOVE,
        slope_5_bps_per_bar=Decimal("2"),
        slope_10_bps_per_bar=Decimal("-1"),
    )
    assert disagreeing is not None
    mixed = (
        factors[0],
        SubingFactorResult(SubingFactorStatus.READY, below),
        SubingFactorResult(SubingFactorStatus.READY, disagreeing),
        *factors[3:],
    )

    samples = build_research_samples(
        mixed,
        bars,
        horizons=(3, 5, 8),
        direction_selector=slope_direction,
    )

    assert [sample.direction for sample in samples[:2]] == [
        DirectionalSide.LONG,
        DirectionalSide.SHORT,
    ]
    assert all(sample.factor.bar_end != bars[2].bar_end for sample in samples)


def test_candidate_quantiles_are_product_bounded_inclusive_and_explicit() -> None:
    assert candidate_quantiles(
        {
            "JM": [
                Decimal("1"),
                Decimal("2"),
                Decimal("3"),
                Decimal("4"),
                Decimal("5"),
            ],
            "AG": [Decimal("7.5")],
            "RB": [],
        }
    ) == {
        "JM": (Decimal("1.4"), Decimal("1.8"), Decimal("2.2")),
        "AG": (Decimal("7.5"), Decimal("7.5"), Decimal("7.5")),
        "RB": None,
    }


@pytest.mark.parametrize(
    "percentiles",
    ((0, 20, 30), (10, 20, 100), (10, 10, 30), (True, 20, 30)),
)
def test_candidate_quantiles_reject_invalid_percentiles(
    percentiles: tuple[int, int, int],
) -> None:
    with pytest.raises(ValueError, match="percentiles"):
        candidate_quantiles(
            {"JM": [Decimal("1"), Decimal("2")]},
            percentiles=percentiles,
        )


@pytest.mark.parametrize("invalid", (Decimal("NaN"), Decimal("-1")))
def test_candidate_quantiles_reject_non_finite_or_negative_values(
    invalid: Decimal,
) -> None:
    with pytest.raises(ValueError, match="candidate value"):
        candidate_quantiles({"JM": [invalid]})


def test_candidate_quantiles_require_decimal_values_and_named_products() -> None:
    with pytest.raises(TypeError, match="candidate value must be Decimal"):
        candidate_quantiles({"JM": [1.25]})  # type: ignore[list-item]
    with pytest.raises(ValueError, match="product"):
        candidate_quantiles({" ": [Decimal("1")]})


def test_horizons_reject_booleans_even_though_bool_is_an_int_subclass() -> None:
    bars, factors = _series()

    with pytest.raises(ValueError, match="positive integers"):
        build_outcomes_at(
            factors,
            bars,
            index=0,
            direction=DirectionalSide.LONG,
            horizons=(True,),
        )


@pytest.mark.parametrize("invalid", (Decimal("NaN"), Decimal("-1")))
def test_threshold_rejects_non_finite_or_negative_decimal(invalid: Decimal) -> None:
    with pytest.raises(ValueError, match="threshold"):
        evaluate_threshold((), invalid)


def test_threshold_requires_decimal_input() -> None:
    with pytest.raises(TypeError, match="threshold must be Decimal"):
        evaluate_threshold((), 1.25)  # type: ignore[arg-type]


def test_threshold_evaluation_reports_hand_checked_horizon_statistics() -> None:
    bars, factors = _series()
    base = build_research_samples(
        factors,
        bars,
        horizons=(3,),
        direction_selector=(
            lambda index, factor: DirectionalSide.LONG if index < 3 else None
        ),
    )
    failed_outcome = base[1].outcomes[3]
    assert failed_outcome is not None
    samples = (
        replace(base[0], studied_value=Decimal("1")),
        replace(
            base[1],
            studied_value=Decimal("2"),
            outcomes={3: replace(failed_outcome, ema21_failure=True)},
        ),
        replace(base[2], studied_value=Decimal("3")),
    )

    evaluation = evaluate_threshold(samples, Decimal("1"), horizons=(3,))

    assert evaluation.threshold == Decimal("1")
    assert evaluation.sample_count == 2
    assert evaluation.horizons[3].sample_count == 2
    assert evaluation.horizons[3].median_directional_return_bps == Decimal(
        "295.5736750145602795573675014"
    )
    assert evaluation.horizons[3].median_mfe_bps == Decimal(
        "492.6227916909337992622791690"
    )
    assert evaluation.horizons[3].median_mae_bps == Decimal(
        "-246.5540671714230246554067172"
    )
    assert evaluation.horizons[3].ema21_failure_rate == Decimal("0.5")


def test_threshold_direction_is_strict_above_or_inclusive_at_or_below() -> None:
    bars, factors = _series()
    base = build_research_samples(
        factors,
        bars,
        horizons=(3,),
        direction_selector=(
            lambda index, factor: DirectionalSide.LONG if index < 3 else None
        ),
    )
    samples = tuple(
        replace(sample, studied_value=Decimal(index))
        for index, sample in enumerate(base, start=1)
    )

    strict_above = evaluate_threshold(samples, Decimal("2"), horizons=(3,))
    inclusive_below = evaluate_threshold(
        samples,
        Decimal("2"),
        horizons=(3,),
        include_at_or_below=True,
    )

    assert strict_above.sample_count == 1
    assert inclusive_below.sample_count == 2


_CALIBRATION_FIXTURE = (
    Path(__file__).parent / "fixtures" / "subing_calibration_test_v1.json"
)


def _write_calibration_payload(
    path: Path,
    payload: dict[str, object],
) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _valid_calibration_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "calibration_id": "subing_test_intraday_v1",
        "accepted_timeframes": ["5m", "15m"],
        "slope_flat_threshold_bps_per_bar": {
            "5m": "1.25",
            "15m": "0.80",
        },
    }


def test_missing_calibration_file_returns_pending(tmp_path: Path) -> None:
    calibration = calibration_module.load_subing_calibration(tmp_path / "missing.json")

    assert calibration.calibration_id is None
    assert calibration.accepted_timeframes == frozenset()
    assert calibration.slope_flat_threshold_bps_per_bar == {}


def test_valid_slope_only_fixture_loads_exact_immutable_values() -> None:
    calibration = calibration_module.load_subing_calibration(_CALIBRATION_FIXTURE)

    assert calibration.calibration_id == "subing_test_intraday_v1"
    assert calibration.accepted_timeframes == frozenset(
        {BarFrequency.M5, BarFrequency.M15}
    )
    assert calibration.slope_flat_threshold_bps_per_bar == {
        BarFrequency.M5: Decimal("1.25"),
        BarFrequency.M15: Decimal("0.80"),
    }
    with pytest.raises(TypeError):
        calibration.slope_flat_threshold_bps_per_bar[BarFrequency.M5] = Decimal(  # type: ignore[index]
            "9"
        )


def test_unknown_calibration_schema_fails_closed(tmp_path: Path) -> None:
    payload = _valid_calibration_payload()
    payload["schema_version"] = 2
    path = tmp_path / "calibration.json"
    _write_calibration_payload(path, payload)

    with pytest.raises(ValueError, match="SUBING_CALIBRATION_INVALID"):
        calibration_module.load_subing_calibration(path)


@pytest.mark.parametrize("invalid", ("-0.01", "NaN", "Infinity", "-Infinity", None))
def test_negative_non_finite_or_null_slope_fails_closed(
    tmp_path: Path,
    invalid: str | None,
) -> None:
    payload = _valid_calibration_payload()
    slopes = payload["slope_flat_threshold_bps_per_bar"]
    assert isinstance(slopes, dict)
    slopes["5m"] = invalid
    path = tmp_path / "calibration.json"
    _write_calibration_payload(path, payload)

    with pytest.raises(ValueError, match="SUBING_CALIBRATION_INVALID"):
        calibration_module.load_subing_calibration(path)


def test_sentinel_scale_slope_fails_closed(tmp_path: Path) -> None:
    payload = _valid_calibration_payload()
    slopes = payload["slope_flat_threshold_bps_per_bar"]
    assert isinstance(slopes, dict)
    slopes["5m"] = "1E+999999"
    path = tmp_path / "calibration.json"
    _write_calibration_payload(path, payload)

    with pytest.raises(ValueError, match="SUBING_CALIBRATION_INVALID"):
        calibration_module.load_subing_calibration(path)


@pytest.mark.parametrize("missing", ("5m", "15m"))
def test_missing_required_intraday_slope_fails_closed(
    tmp_path: Path,
    missing: str,
) -> None:
    payload = _valid_calibration_payload()
    slopes = payload["slope_flat_threshold_bps_per_bar"]
    assert isinstance(slopes, dict)
    del slopes[missing]
    path = tmp_path / "calibration.json"
    _write_calibration_payload(path, payload)

    with pytest.raises(ValueError, match="SUBING_CALIBRATION_INVALID"):
        calibration_module.load_subing_calibration(path)


def test_daily_accepted_value_fails_closed(tmp_path: Path) -> None:
    payload = _valid_calibration_payload()
    accepted = payload["accepted_timeframes"]
    slopes = payload["slope_flat_threshold_bps_per_bar"]
    assert isinstance(accepted, list)
    assert isinstance(slopes, dict)
    accepted.append("1d")
    slopes["1d"] = "1.00"
    path = tmp_path / "calibration.json"
    _write_calibration_payload(path, payload)

    with pytest.raises(ValueError, match="SUBING_CALIBRATION_INVALID"):
        calibration_module.load_subing_calibration(path)


def test_executable_zero_band_field_fails_closed(tmp_path: Path) -> None:
    payload = _valid_calibration_payload()
    payload["macd_zero_band_bps"] = {"5m": "16", "15m": "27"}
    path = tmp_path / "calibration.json"
    _write_calibration_payload(path, payload)

    with pytest.raises(ValueError, match="SUBING_CALIBRATION_INVALID"):
        calibration_module.load_subing_calibration(path)
