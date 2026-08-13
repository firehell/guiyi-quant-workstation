from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from statistics import median
from types import MappingProxyType
from typing import Protocol
from zoneinfo import ZoneInfo

from .domain import (
    BarFrequency,
    CanonicalBar,
    MarketSeriesResult,
    SeriesKind,
    SeriesQuery,
)
from .subing_calibration import (
    CalibrationReport,
    DirectionalSide,
    SubingResearchSample,
    build_research_samples,
    candidate_quantiles,
    evaluate_threshold,
    slope_direction,
)
from .subing_research import (
    MacdCross,
    PriceSide,
    SubingFactorResult,
    SubingFactorSnapshot,
    SubingFactorStatus,
    calculate_subing_factor_series,
)


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SUPPORTED_FREQUENCIES = frozenset({BarFrequency.M5, BarFrequency.M15, BarFrequency.D1})
_INTRADAY_FREQUENCIES = frozenset({BarFrequency.M5, BarFrequency.M15})
_HORIZONS = (3, 5, 8)


class CalibrationPhase(StrEnum):
    SLOPE = "slope"
    ZERO_BAND = "zero-band"


class CalibrationMode(StrEnum):
    DISCOVERY = "discovery"
    VALIDATION = "validation"


@dataclass(frozen=True, slots=True)
class SlopeThresholds:
    m5: Decimal
    m15: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "m5", _threshold(self.m5, field="m5"))
        object.__setattr__(self, "m15", _threshold(self.m15, field="m15"))

    def for_frequency(self, frequency: BarFrequency) -> Decimal:
        if frequency is BarFrequency.M5:
            return self.m5
        if frequency is BarFrequency.M15:
            return self.m15
        raise ValueError("intraday slope threshold frequency required")


@dataclass(frozen=True, slots=True)
class CalibrationResearchRequest:
    phase: CalibrationPhase
    mode: CalibrationMode
    frequency: BarFrequency
    since: date
    through: date
    symbol: str | None = None
    slope_threshold_bps: Decimal | None = None
    slope_thresholds: SlopeThresholds | None = None
    zero_band_bps: Decimal | None = None

    def __post_init__(self) -> None:
        try:
            phase = CalibrationPhase(self.phase)
            mode = CalibrationMode(self.mode)
            frequency = BarFrequency(self.frequency)
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported calibration request") from exc
        if frequency not in _SUPPORTED_FREQUENCIES:
            raise ValueError("frequency must be one of 5m, 15m or 1d")
        if (
            not isinstance(self.since, date)
            or isinstance(self.since, datetime)
            or not isinstance(self.through, date)
            or isinstance(self.through, datetime)
            or self.since > self.through
        ):
            raise ValueError("since must not be later than through")
        symbol = self.symbol
        if symbol is not None:
            if not isinstance(symbol, str) or not symbol.strip():
                raise ValueError("symbol must be non-empty")
            symbol = symbol.strip().lower()
        slope = (
            None
            if self.slope_threshold_bps is None
            else _threshold(self.slope_threshold_bps, field="slope_threshold_bps")
        )
        zero_band = (
            None
            if self.zero_band_bps is None
            else _threshold(self.zero_band_bps, field="zero_band_bps")
        )
        object.__setattr__(self, "phase", phase)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "frequency", frequency)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "slope_threshold_bps", slope)
        object.__setattr__(self, "zero_band_bps", zero_band)
        self._validate_matrix()

    def _validate_matrix(self) -> None:
        if self.phase is CalibrationPhase.SLOPE:
            if self.slope_thresholds is not None or self.zero_band_bps is not None:
                raise ValueError("slope research forbids zero-band inputs")
            if self.mode is CalibrationMode.DISCOVERY:
                if self.slope_threshold_bps is not None:
                    raise ValueError("slope discovery forbids a threshold")
            elif self.slope_threshold_bps is None:
                raise ValueError("slope validation requires slope_threshold_bps")
            return

        if self.frequency in _INTRADAY_FREQUENCIES:
            if self.slope_thresholds is None or self.slope_threshold_bps is not None:
                raise ValueError("intraday zero-band research requires m5/m15 slopes")
        elif self.slope_threshold_bps is None or self.slope_thresholds is not None:
            raise ValueError("daily zero-band research requires slope_threshold_bps")
        if self.mode is CalibrationMode.DISCOVERY:
            if self.zero_band_bps is not None:
                raise ValueError("zero-band discovery forbids a zero-band threshold")
        elif self.zero_band_bps is None:
            raise ValueError("zero-band validation requires zero_band_bps")


@dataclass(frozen=True, slots=True)
class CalibrationResearchResult:
    products: tuple[str, ...]
    report: CalibrationReport
    cohorts: Mapping[str, CalibrationReport]


class _MarketDataReader(Protocol):
    def query(self, request: SeriesQuery) -> MarketSeriesResult: ...


@dataclass(frozen=True, slots=True)
class _FactorSeries:
    bars: tuple[CanonicalBar, ...]
    factors: tuple[SubingFactorResult, ...]


class SubingCalibrationResearchService:
    def __init__(
        self,
        market_data: _MarketDataReader,
        *,
        products: Sequence[str],
    ) -> None:
        normalized = tuple(
            dict.fromkeys(product.strip().lower() for product in products)
        )
        if not normalized or any(not product for product in normalized):
            raise ValueError("products must be non-empty")
        self._market_data = market_data
        self._products = normalized

    def run(self, request: CalibrationResearchRequest) -> CalibrationResearchResult:
        products = self._selected_products(request.symbol)
        if request.phase is CalibrationPhase.SLOPE:
            report = self._run_slope(request, products)
            return CalibrationResearchResult(products, report, MappingProxyType({}))
        cohorts = self._run_zero_band(request, products)
        return CalibrationResearchResult(products, cohorts["B"], cohorts)

    def _selected_products(self, symbol: str | None) -> tuple[str, ...]:
        if symbol is None:
            return self._products
        if symbol not in self._products:
            raise ValueError("symbol is outside the active product scope")
        return (symbol,)

    def _run_slope(
        self,
        request: CalibrationResearchRequest,
        products: tuple[str, ...],
    ) -> CalibrationReport:
        if request.mode is CalibrationMode.DISCOVERY:
            product_candidates: list[tuple[Decimal, Decimal, Decimal]] = []
            for product in products:
                series = self._factor_series(product, request.frequency, request)
                samples = build_research_samples(
                    series.factors,
                    series.bars,
                    horizons=_HORIZONS,
                    direction_selector=slope_direction,
                )
                candidates = candidate_quantiles(
                    {product: [sample.studied_value for sample in samples]}
                )[product]
                if candidates is not None:
                    product_candidates.append(candidates)
            global_candidates = _median_candidates(product_candidates)
            samples_by_product = self._slope_samples(products, request)
            all_samples = _flatten_samples(samples_by_product)
            return CalibrationReport(
                sample_count=len(all_samples),
                product_sample_counts={
                    product: len(samples_by_product[product]) for product in products
                },
                candidate_thresholds=global_candidates,
                candidate_evaluations=(
                    tuple(
                        evaluate_threshold(all_samples, candidate, horizons=_HORIZONS)
                        for candidate in global_candidates
                    )
                    if global_candidates is not None
                    else ()
                ),
            )

        assert request.slope_threshold_bps is not None
        samples_by_product = self._slope_samples(products, request)
        all_samples = _flatten_samples(samples_by_product)
        return CalibrationReport(
            sample_count=len(all_samples),
            product_sample_counts={
                product: len(samples_by_product[product]) for product in products
            },
            threshold_evaluation=evaluate_threshold(
                all_samples,
                request.slope_threshold_bps,
                horizons=_HORIZONS,
            ),
        )

    def _slope_samples(
        self,
        products: tuple[str, ...],
        request: CalibrationResearchRequest,
    ) -> dict[str, tuple[SubingResearchSample, ...]]:
        result: dict[str, tuple[SubingResearchSample, ...]] = {}
        for product in products:
            series = self._factor_series(product, request.frequency, request)
            result[product] = build_research_samples(
                series.factors,
                series.bars,
                horizons=_HORIZONS,
                direction_selector=slope_direction,
            )
        return result

    def _run_zero_band(
        self,
        request: CalibrationResearchRequest,
        products: tuple[str, ...],
    ) -> Mapping[str, CalibrationReport]:
        if request.mode is CalibrationMode.DISCOVERY:
            product_candidates: list[tuple[Decimal, Decimal, Decimal]] = []
            for product in products:
                _, cohort_b = self._zero_band_samples(product, request)
                candidates = candidate_quantiles(
                    {product: [sample.studied_value for sample in cohort_b]},
                    percentiles=(20, 40, 60),
                )[product]
                if candidates is not None:
                    product_candidates.append(candidates)
            candidates = _median_candidates(product_candidates)
            samples = {
                product: self._zero_band_samples(product, request)
                for product in products
            }
            return _zero_band_reports(products, samples, candidates=candidates)

        assert request.zero_band_bps is not None
        samples = {
            product: self._zero_band_samples(product, request) for product in products
        }
        return _zero_band_reports(
            products,
            samples,
            threshold=request.zero_band_bps,
        )

    def _zero_band_samples(
        self,
        product: str,
        request: CalibrationResearchRequest,
    ) -> tuple[tuple[SubingResearchSample, ...], tuple[SubingResearchSample, ...]]:
        primary = self._factor_series(product, request.frequency, request)
        companion_by_index: tuple[SubingFactorSnapshot | None, ...]
        if request.frequency in _INTRADAY_FREQUENCIES:
            companion_frequency = (
                BarFrequency.M15
                if request.frequency is BarFrequency.M5
                else BarFrequency.M5
            )
            companion = self._factor_series(product, companion_frequency, request)
            companion_by_index = _align_latest_companions(primary, companion)
        else:
            companion_by_index = (None,) * len(primary.factors)

        cohort_a = build_research_samples(
            primary.factors,
            primary.bars,
            horizons=_HORIZONS,
            direction_selector=_cross_direction,
            value_selector=lambda factor: factor.macd_zero_distance_bps,
        )
        cohort_b = build_research_samples(
            primary.factors,
            primary.bars,
            horizons=_HORIZONS,
            direction_selector=lambda index, factor: self._cohort_b_direction(
                request,
                index,
                factor,
                companion_by_index,
            ),
            value_selector=lambda factor: factor.macd_zero_distance_bps,
        )
        return cohort_a, cohort_b

    @staticmethod
    def _cohort_b_direction(
        request: CalibrationResearchRequest,
        index: int,
        factor: SubingFactorSnapshot,
        companions: Sequence[SubingFactorSnapshot | None],
    ) -> DirectionalSide | None:
        if request.frequency in _INTRADAY_FREQUENCIES:
            assert request.slope_thresholds is not None
            primary_threshold = request.slope_thresholds.for_frequency(
                request.frequency
            )
            companion_frequency = (
                BarFrequency.M15
                if request.frequency is BarFrequency.M5
                else BarFrequency.M5
            )
            companion_threshold = request.slope_thresholds.for_frequency(
                companion_frequency
            )
            if factor.volume_ratio_prev is None or factor.volume_ratio_prev < 3:
                return None
            companion = companions[index]
            if companion is None:
                return None
        else:
            assert request.slope_threshold_bps is not None
            primary_threshold = request.slope_threshold_bps
            companion_threshold = Decimal(0)
            companion = None

        if (
            factor.price_side is PriceSide.ABOVE
            and factor.slope_5_bps_per_bar > primary_threshold
            and factor.slope_10_bps_per_bar > 0
            and factor.macd_cross is MacdCross.GOLDEN
            and (
                companion is None
                or (
                    companion.price_side is PriceSide.ABOVE
                    and companion.slope_5_bps_per_bar > companion_threshold
                    and companion.slope_10_bps_per_bar > 0
                )
            )
        ):
            return DirectionalSide.LONG
        if (
            factor.price_side is PriceSide.BELOW
            and factor.slope_5_bps_per_bar < -primary_threshold
            and factor.slope_10_bps_per_bar < 0
            and factor.macd_cross is MacdCross.DEAD
            and (
                companion is None
                or (
                    companion.price_side is PriceSide.BELOW
                    and companion.slope_5_bps_per_bar < -companion_threshold
                    and companion.slope_10_bps_per_bar < 0
                )
            )
        ):
            return DirectionalSide.SHORT
        return None

    def _factor_series(
        self,
        symbol: str,
        frequency: BarFrequency,
        request: CalibrationResearchRequest,
    ) -> _FactorSeries:
        start, end = _research_window(request.since, request.through)
        result = self._market_data.query(
            SeriesQuery(
                SeriesKind.ACTUAL_DOMINANT,
                symbol,
                frequency,
                start,
                end,
            )
        )
        requested_bars = tuple(
            bar
            for bar in result.bars
            if request.since <= bar.trading_day <= request.through
        )
        pairs: list[tuple[CanonicalBar, SubingFactorResult]] = []
        covered: set[tuple[datetime, date]] = set()
        for segment in result.resolved_contract_segments:
            segment_bars = tuple(
                bar
                for bar in requested_bars
                if segment.start_trading_day
                <= bar.trading_day
                <= segment.end_trading_day
            )
            if not segment_bars:
                continue
            factors = calculate_subing_factor_series(
                segment_bars,
                timeframe=frequency,
                contract=segment.contract,
                segment_start_trading_day=segment.start_trading_day,
                latest_bar_source="canonical",
            )
            for bar, factor in zip(segment_bars, factors, strict=True):
                identity = (bar.bar_end, bar.trading_day)
                if identity in covered:
                    raise ValueError("rank1 segments overlap")
                covered.add(identity)
                pairs.append((bar, factor))
        if len(covered) != len(requested_bars):
            raise ValueError("rank1 segment identity is incomplete")
        pairs.sort(key=lambda pair: pair[0].bar_end)
        return _FactorSeries(
            bars=tuple(pair[0] for pair in pairs),
            factors=tuple(pair[1] for pair in pairs),
        )


def _research_window(since: date, through: date) -> tuple[datetime, datetime]:
    start = datetime.combine(since - timedelta(days=1), time.min, _SHANGHAI).astimezone(
        UTC
    )
    end = datetime.combine(through + timedelta(days=1), time.max, _SHANGHAI).astimezone(
        UTC
    )
    return start, end


def _align_latest_companions(
    primary: _FactorSeries,
    companion: _FactorSeries,
) -> tuple[SubingFactorSnapshot | None, ...]:
    pointer = 0
    latest_by_segment: dict[tuple[str, date], SubingFactorSnapshot] = {}
    aligned: list[SubingFactorSnapshot | None] = []
    for bar, primary_result in zip(primary.bars, primary.factors, strict=True):
        while (
            pointer < len(companion.bars)
            and companion.bars[pointer].bar_end <= bar.bar_end
        ):
            companion_result = companion.factors[pointer]
            if (
                companion_result.status is SubingFactorStatus.READY
                and companion_result.snapshot is not None
            ):
                snapshot = companion_result.snapshot
                latest_by_segment[
                    (snapshot.contract, snapshot.segment_start_trading_day)
                ] = snapshot
            pointer += 1
        if (
            primary_result.status is SubingFactorStatus.READY
            and primary_result.snapshot is not None
        ):
            snapshot = primary_result.snapshot
            aligned.append(
                latest_by_segment.get(
                    (snapshot.contract, snapshot.segment_start_trading_day)
                )
            )
        else:
            aligned.append(None)
    return tuple(aligned)


def _cross_direction(
    _index: int,
    factor: SubingFactorSnapshot,
) -> DirectionalSide | None:
    if factor.macd_cross is MacdCross.GOLDEN:
        return DirectionalSide.LONG
    if factor.macd_cross is MacdCross.DEAD:
        return DirectionalSide.SHORT
    return None


def _median_candidates(
    values: Sequence[tuple[Decimal, Decimal, Decimal]],
) -> tuple[Decimal, Decimal, Decimal] | None:
    if not values:
        return None
    return (
        median(value[0] for value in values),
        median(value[1] for value in values),
        median(value[2] for value in values),
    )


def _flatten_samples(
    values: Mapping[str, tuple[SubingResearchSample, ...]],
) -> tuple[SubingResearchSample, ...]:
    return tuple(sample for samples in values.values() for sample in samples)


def _zero_band_reports(
    products: tuple[str, ...],
    samples: Mapping[
        str,
        tuple[tuple[SubingResearchSample, ...], tuple[SubingResearchSample, ...]],
    ],
    *,
    candidates: tuple[Decimal, Decimal, Decimal] | None = None,
    threshold: Decimal | None = None,
) -> Mapping[str, CalibrationReport]:
    reports: dict[str, CalibrationReport] = {}
    for cohort_index, cohort_name in enumerate(("A", "B")):
        product_samples = {
            product: samples[product][cohort_index] for product in products
        }
        all_samples = _flatten_samples(product_samples)
        reports[cohort_name] = CalibrationReport(
            sample_count=len(all_samples),
            product_sample_counts={
                product: len(product_samples[product]) for product in products
            },
            candidate_thresholds=candidates,
            candidate_evaluations=(
                tuple(
                    evaluate_threshold(
                        all_samples,
                        candidate,
                        horizons=_HORIZONS,
                        include_at_or_below=True,
                    )
                    for candidate in candidates
                )
                if candidates is not None
                else ()
            ),
            threshold_evaluation=(
                evaluate_threshold(
                    all_samples,
                    threshold,
                    horizons=_HORIZONS,
                    include_at_or_below=True,
                )
                if threshold is not None
                else None
            ),
        )
    return MappingProxyType(reports)


def _threshold(value: Decimal, *, field: str) -> Decimal:
    threshold = Decimal(value)
    if not threshold.is_finite() or threshold < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return threshold
