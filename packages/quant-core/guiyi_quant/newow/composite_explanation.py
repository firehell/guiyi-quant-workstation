"""Evidence-gated, page-reference Newow composite explanation facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from math import floor, isfinite

from .context_alignment import ContextSlot, ContextSnapshot
from .product_contracts import (
    EvidenceStatus,
    FeatureRuntimeStatus,
    FeatureStatus,
    ProductBar,
    ProductFrequency,
)
from .product_identity import utc_timestamp
from .target_absorb_display import PageSignalFact, PageSignalState


COMPOSITE_DECISION_FORMULA_VERSION = (
    "newow_composite_decision_page_v3_2_82_reachable_v1"
)
COMPOSITE_DIRECTION_FORMULA_VERSION = "newow_composite_direction_page_v3_2_58"
COMPOSITE_CERTAINTY_FORMULA_VERSION = "newow_composite_certainty_page_v3_2_59"
COMPOSITE_VOLATILITY_FORMULA_VERSION = (
    "newow_composite_volatility_mean_tr20_over_close_page_v3_2_59"
)
FIRST_ACTION_FORMULA_VERSION = "newow_first_action_principle_page_v3_2_63"
WEEK_DAY_MATRIX_FORMULA_VERSION = "newow_trend_week_day_matrix_page_v3_2_49"
EVIDENCE_MANIFEST_SHA256 = (
    "279aa0c3a88b6e6c5413387a57085dfe4c4d23a34befa751d95ced4c03be962f"
)
PAGE_SOURCE_SHA256 = "cd962170085dc2145fbaebf28a47ce6764b9f519e6032b54a896e37f0c9d0cf9"
REACHABILITY_SHA256 = "48888a4b3f1a2634d7e4664200aed07c0ef4ce9426fb62840baa8e88e0e68d5c"
AI_TEMPLATE_EVIDENCE_SHA256 = (
    "3a759abad84e1f7f03d8a4343872d2f4d9758ac746d3e9dd033bcd95106e606f"
)
FROZEN_RESULTS_SHA256 = (
    "163337b4b425241189ae348814610c29b3ff3b24a3c4b03a95da10864efbab3e"
)
FORMULA_VERSIONS = (
    COMPOSITE_DECISION_FORMULA_VERSION,
    COMPOSITE_DIRECTION_FORMULA_VERSION,
    COMPOSITE_CERTAINTY_FORMULA_VERSION,
    COMPOSITE_VOLATILITY_FORMULA_VERSION,
    FIRST_ACTION_FORMULA_VERSION,
    WEEK_DAY_MATRIX_FORMULA_VERSION,
)


class CompositeBias(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    CAUTIOUS = "cautious"
    WARNING = "warning"
    NEUTRAL = "neutral"


class CompositeStatusState(StrEnum):
    HOLDING = "holding"
    CLEARED = "cleared"
    IDLE = "idle"


class FirstActionTokenOwner(StrEnum):
    GUIYI_CLEAN_ROOM = "GUIYI_CLEAN_ROOM"


class VolatilityLevel(StrEnum):
    LOW = "low"
    MID = "mid"
    HIGH = "high"


class CompositeSourceUsage(StrEnum):
    CURRENT_FACT = "current_fact"
    VOLATILITY_PREFIX = "volatility_prefix"


def _text(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("NEWOW_COMPOSITE_INVALID_TEXT")


def _ready() -> FeatureStatus:
    return FeatureStatus(
        FeatureRuntimeStatus.READY,
        EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
    )


def _warming(reason: str) -> FeatureStatus:
    return FeatureStatus(
        FeatureRuntimeStatus.WARMING,
        EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
        reason,
    )


def _required(reason: str) -> FeatureStatus:
    return FeatureStatus(
        FeatureRuntimeStatus.EVIDENCE_REQUIRED,
        EvidenceStatus.EVIDENCE_REQUIRED,
        reason,
    )


@dataclass(frozen=True, slots=True)
class CompositeStatusFact:
    value: CompositeStatusState
    frequency: ProductFrequency
    bar_end: datetime
    physical_contract: str
    segment_id: str

    def __post_init__(self) -> None:
        try:
            value = CompositeStatusState(self.value)
            frequency = ProductFrequency(self.frequency)
            bar_end = utc_timestamp(self.bar_end)
        except (TypeError, ValueError) as error:
            raise ValueError("NEWOW_COMPOSITE_INVALID_STATUS_FACT") from error
        try:
            _text(self.physical_contract)
            _text(self.segment_id)
        except ValueError as error:
            raise ValueError("NEWOW_COMPOSITE_INVALID_STATUS_FACT") from error
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "frequency", frequency)
        object.__setattr__(self, "bar_end", bar_end)


@dataclass(frozen=True, slots=True)
class VerifiedCompositeEvidence:
    """Frozen evidence identities plus caller-supplied current context facts."""

    trend_weekly: PageSignalFact | None
    trend_daily: PageSignalFact | None
    trend_hourly: CompositeStatusFact | None
    oscillation_weekly: CompositeStatusFact | None
    oscillation_daily: CompositeStatusFact | None
    oscillation_hourly: CompositeStatusFact | None
    daily_bars: tuple[ProductBar, ...] = ()
    manifest_sha256: str = EVIDENCE_MANIFEST_SHA256
    page_source_sha256: str = PAGE_SOURCE_SHA256
    reachability_sha256: str = REACHABILITY_SHA256
    ai_template_evidence_sha256: str = AI_TEMPLATE_EVIDENCE_SHA256
    frozen_results_sha256: str = FROZEN_RESULTS_SHA256

    def __post_init__(self) -> None:
        page_facts = (self.trend_weekly, self.trend_daily)
        status_facts = (
            self.trend_hourly,
            self.oscillation_weekly,
            self.oscillation_daily,
            self.oscillation_hourly,
        )
        if any(
            fact is not None and not isinstance(fact, PageSignalFact)
            for fact in page_facts
        ) or any(
            fact is not None and not isinstance(fact, CompositeStatusFact)
            for fact in status_facts
        ):
            raise ValueError("NEWOW_COMPOSITE_INVALID_EVIDENCE")
        bars = tuple(self.daily_bars)
        if not all(isinstance(bar, ProductBar) for bar in bars):
            raise ValueError("NEWOW_COMPOSITE_INVALID_EVIDENCE")
        if (
            self.manifest_sha256 != EVIDENCE_MANIFEST_SHA256
            or self.page_source_sha256 != PAGE_SOURCE_SHA256
            or self.reachability_sha256 != REACHABILITY_SHA256
            or self.ai_template_evidence_sha256 != AI_TEMPLATE_EVIDENCE_SHA256
            or self.frozen_results_sha256 != FROZEN_RESULTS_SHA256
        ):
            raise ValueError("NEWOW_COMPOSITE_EVIDENCE_IDENTITY")
        object.__setattr__(self, "daily_bars", bars)


@dataclass(frozen=True, slots=True)
class CompositeBiasPair:
    trend: CompositeBias
    oscillation: CompositeBias


@dataclass(frozen=True, slots=True)
class CompositeDecision:
    source_key: str
    selected_key: str
    label: str
    position_range: str
    fallback_used: bool
    warning_branches_unreachable: bool = True
    position_is_target: bool = False
    position_is_hand_count: bool = False
    formula_version: str = COMPOSITE_DECISION_FORMULA_VERSION


@dataclass(frozen=True, slots=True)
class CompositeDirection:
    token: str
    certainty_points: int
    formula_version: str = COMPOSITE_DIRECTION_FORMULA_VERSION


@dataclass(frozen=True, slots=True)
class CertaintyBreakdown:
    trend: int
    oscillation: int
    alignment: int
    direction: int
    uncapped_total: int
    total: int
    cap: int | None
    is_probability: bool = False
    is_win_rate: bool = False
    formula_version: str = COMPOSITE_CERTAINTY_FORMULA_VERSION


@dataclass(frozen=True, slots=True)
class CompositeVolatility:
    value_pct: Decimal
    level: VolatilityLevel
    true_range_count: int
    method: str = "simple_mean_true_range_over_last_close"
    is_wilder_atr: bool = False
    formula_version: str = COMPOSITE_VOLATILITY_FORMULA_VERSION


@dataclass(frozen=True, slots=True)
class FirstActionPrinciple:
    rule_token: str
    level: str
    page_title: str
    page_detail: str
    token_owner: FirstActionTokenOwner = FirstActionTokenOwner.GUIYI_CLEAN_ROOM
    token_is_page_native: bool = False
    page_formula_version: str = FIRST_ACTION_FORMULA_VERSION


@dataclass(frozen=True, slots=True)
class WeekDayMatrixEntry:
    key: str
    name: str
    risk: str
    position: str
    formula_version: str = WEEK_DAY_MATRIX_FORMULA_VERSION


@dataclass(frozen=True, slots=True)
class CompositeSubfeature:
    name: str
    status: FeatureStatus
    value: object | None

    def __post_init__(self) -> None:
        _text(self.name)
        if not isinstance(self.status, FeatureStatus):
            raise ValueError("NEWOW_COMPOSITE_INVALID_SUBFEATURE")


@dataclass(frozen=True, slots=True)
class CompositeSourceBars:
    """Auditable current-fact or owner-local volatility input range."""

    usage: CompositeSourceUsage
    fact_names: tuple[str, ...]
    frequency: ProductFrequency
    physical_contract: str | None
    segment_id: str | None
    source_identities: tuple[str, ...]
    count: int
    first_bar_end: datetime | None
    last_bar_end: datetime | None
    first_trading_day: date | None
    last_trading_day: date | None
    as_of: datetime
    in_sample: bool
    repainting: bool
    repaint_status: FeatureStatus
    input_status: FeatureStatus

    def __post_init__(self) -> None:
        try:
            usage = CompositeSourceUsage(self.usage)
            frequency = ProductFrequency(self.frequency)
            as_of = utc_timestamp(self.as_of)
        except (TypeError, ValueError) as error:
            raise ValueError("NEWOW_COMPOSITE_INVALID_SOURCE_BARS") from error
        fact_names = tuple(self.fact_names)
        sources = tuple(self.source_identities)
        if (
            not fact_names
            or len(set(fact_names)) != len(fact_names)
            or any(not isinstance(name, str) or not name for name in fact_names)
            or len(set(sources)) != len(sources)
            or any(not isinstance(source, str) or not source for source in sources)
            or type(self.count) is not int
            or self.count < 0
            or type(self.in_sample) is not bool
            or type(self.repainting) is not bool
            or self.in_sample is not False
            or self.repainting is not False
            or not isinstance(self.repaint_status, FeatureStatus)
            or not isinstance(self.input_status, FeatureStatus)
            or self.repaint_status.status is not FeatureRuntimeStatus.READY
            or self.repaint_status.evidence_status
            is not EvidenceStatus.RESEARCH_EVIDENCE_ONLY
            or self.input_status.evidence_status
            is not EvidenceStatus.ACTIVE_CODE_VERIFIED
        ):
            raise ValueError("NEWOW_COMPOSITE_INVALID_SOURCE_BARS")

        current_names = {
            ProductFrequency.WEEKLY: ("trend_weekly", "oscillation_weekly"),
            ProductFrequency.DAILY: ("trend_daily", "oscillation_daily"),
            ProductFrequency.HOURLY: ("trend_hourly", "oscillation_hourly"),
        }
        if usage is CompositeSourceUsage.CURRENT_FACT:
            valid_usage = (
                fact_names == current_names.get(frequency)
                and self.count == 1
                and self.input_status.status is FeatureRuntimeStatus.READY
            )
        else:
            valid_usage = (
                frequency is ProductFrequency.DAILY
                and fact_names == ("volatility",)
                and self.count <= 21
                and self.input_status.status
                is (
                    FeatureRuntimeStatus.READY
                    if self.count >= 6
                    else FeatureRuntimeStatus.WARMING
                )
            )
        if not valid_usage:
            raise ValueError("NEWOW_COMPOSITE_INVALID_SOURCE_BARS")

        bounds = (
            self.first_bar_end,
            self.last_bar_end,
            self.first_trading_day,
            self.last_trading_day,
        )
        if self.count == 0:
            if (
                usage is not CompositeSourceUsage.VOLATILITY_PREFIX
                or any(bound is not None for bound in bounds)
                or self.physical_contract is not None
                or self.segment_id is not None
                or sources
            ):
                raise ValueError("NEWOW_COMPOSITE_INVALID_SOURCE_BARS")
        else:
            if (
                any(bound is None for bound in bounds)
                or not isinstance(self.physical_contract, str)
                or not self.physical_contract
                or not isinstance(self.segment_id, str)
                or not self.segment_id
                or not sources
            ):
                raise ValueError("NEWOW_COMPOSITE_INVALID_SOURCE_BARS")
            assert self.first_bar_end is not None
            assert self.last_bar_end is not None
            assert self.first_trading_day is not None
            assert self.last_trading_day is not None
            first_end = utc_timestamp(self.first_bar_end)
            last_end = utc_timestamp(self.last_bar_end)
            if (
                first_end > last_end
                or last_end > as_of
                or self.first_trading_day > self.last_trading_day
            ):
                raise ValueError("NEWOW_COMPOSITE_INVALID_SOURCE_BARS")
            object.__setattr__(self, "first_bar_end", first_end)
            object.__setattr__(self, "last_bar_end", last_end)
        object.__setattr__(self, "usage", usage)
        object.__setattr__(self, "fact_names", fact_names)
        object.__setattr__(self, "frequency", frequency)
        object.__setattr__(self, "source_identities", sources)
        object.__setattr__(self, "as_of", as_of)


@dataclass(frozen=True, slots=True)
class CompositeExplanationValue:
    decision: CompositeDecision
    direction: CompositeDirection
    certainty: CertaintyBreakdown
    volatility: CompositeVolatility | None
    first_action: FirstActionPrinciple
    week_day_matrix: WeekDayMatrixEntry
    subfeatures: tuple[CompositeSubfeature, ...]
    input_facts: tuple[PageSignalFact | CompositeStatusFact, ...]
    warning_branches_unreachable: bool = True
    diagnostic_tokens: None = None
    ai_copy: None = None
    six_combo_ranking: None = None
    evidence_manifest_sha256: str = EVIDENCE_MANIFEST_SHA256
    page_source_sha256: str = PAGE_SOURCE_SHA256
    reachability_sha256: str = REACHABILITY_SHA256
    ai_template_evidence_sha256: str = AI_TEMPLATE_EVIDENCE_SHA256
    frozen_results_sha256: str = FROZEN_RESULTS_SHA256

    def __post_init__(self) -> None:
        features = tuple(self.subfeatures)
        if len({feature.name for feature in features}) != len(features):
            raise ValueError("NEWOW_COMPOSITE_INVALID_VALUE")
        object.__setattr__(self, "subfeatures", features)
        object.__setattr__(self, "input_facts", tuple(self.input_facts))


@dataclass(frozen=True, slots=True)
class CompositeExplanationResult:
    status: FeatureRuntimeStatus
    evidence_status: EvidenceStatus
    reason_code: str | None
    as_of: datetime
    formula_versions: tuple[str, ...] = ()
    source_bars: tuple[CompositeSourceBars, ...] = ()
    value: CompositeExplanationValue | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", FeatureRuntimeStatus(self.status))
        object.__setattr__(
            self, "evidence_status", EvidenceStatus(self.evidence_status)
        )
        object.__setattr__(self, "as_of", utc_timestamp(self.as_of))
        formulas = tuple(self.formula_versions)
        for formula in formulas:
            _text(formula)
        object.__setattr__(self, "formula_versions", formulas)
        sources = tuple(self.source_bars)
        if any(not isinstance(source, CompositeSourceBars) for source in sources):
            raise ValueError("NEWOW_COMPOSITE_INVALID_SOURCE_BARS")
        if self.value is None and sources:
            raise ValueError("NEWOW_COMPOSITE_INVALID_SOURCE_BARS")
        expected_sources = {
            (CompositeSourceUsage.CURRENT_FACT, ProductFrequency.WEEKLY),
            (CompositeSourceUsage.CURRENT_FACT, ProductFrequency.DAILY),
            (CompositeSourceUsage.CURRENT_FACT, ProductFrequency.HOURLY),
            (CompositeSourceUsage.VOLATILITY_PREFIX, ProductFrequency.DAILY),
        }
        if (
            self.value is not None
            and {(source.usage, source.frequency) for source in sources}
            != expected_sources
        ):
            raise ValueError("NEWOW_COMPOSITE_INVALID_SOURCE_BARS")
        if self.value is not None and len(sources) != len(expected_sources):
            raise ValueError("NEWOW_COMPOSITE_INVALID_SOURCE_BARS")
        object.__setattr__(self, "source_bars", sources)
        if self.status is not FeatureRuntimeStatus.READY:
            _text(self.reason_code)


_DECISIONS: dict[str, tuple[str, str]] = {
    "bullish-bullish": ("建仓 / 加仓", "50%-100%"),
    "bullish-bearish": ("持仓观望", "30%-50%"),
    "bullish-neutral": ("建仓 / 加仓", "50%-100%"),
    "bearish-bullish": ("减仓观望", "30%-50%"),
    "bearish-bearish": ("清仓 / 空仓", "0%"),
    "bearish-neutral": ("清仓 / 空仓", "0%"),
    "cautious-bullish": ("谨慎持仓", "30%-50%"),
    "cautious-bearish": ("减仓观望", "10%-30%"),
    "cautious-neutral": ("谨慎持仓", "10%-30%"),
    "warning-bullish": ("减仓观望", "10%-30%"),
    "warning-bearish": ("减仓观望", "10%-30%"),
    "warning-neutral": ("减仓观望", "10%-30%"),
    "neutral-neutral": ("等待信号", "--"),
}


def _trend_bullish(value: PageSignalState | None) -> bool:
    return value in {PageSignalState.BUY, PageSignalState.HOLD}


def _trend_bearish(value: PageSignalState | None) -> bool:
    return value in {PageSignalState.SELL, PageSignalState.WAIT}


def classify_composite_biases(
    weekly: PageSignalState | None,
    daily: PageSignalState | None,
    trend_hourly: CompositeStatusState,
    oscillation_weekly: CompositeStatusState,
    oscillation_daily: CompositeStatusState,
    oscillation_hourly: CompositeStatusState,
) -> CompositeBiasPair:
    """Execute the pinned page branch order, including unreachable warning."""

    weekly = None if weekly is None else PageSignalState(weekly)
    daily = None if daily is None else PageSignalState(daily)
    trend_hourly = CompositeStatusState(trend_hourly)
    oscillation_weekly = CompositeStatusState(oscillation_weekly)
    oscillation_daily = CompositeStatusState(oscillation_daily)
    oscillation_hourly = CompositeStatusState(oscillation_hourly)

    trend = CompositeBias.NEUTRAL
    if _trend_bearish(weekly):
        trend = CompositeBias.BEARISH
    elif _trend_bullish(weekly) and _trend_bearish(daily):
        trend = CompositeBias.CAUTIOUS
    elif _trend_bullish(weekly) and _trend_bullish(daily):
        trend = (
            CompositeBias.CAUTIOUS
            if trend_hourly is CompositeStatusState.CLEARED
            else CompositeBias.BULLISH
        )
    elif _trend_bearish(weekly) and _trend_bullish(daily):
        trend = CompositeBias.WARNING

    oscillation = CompositeBias.NEUTRAL
    if (
        oscillation_weekly
        is oscillation_daily
        is oscillation_hourly
        is CompositeStatusState.HOLDING
    ):
        oscillation = CompositeBias.BULLISH
    elif (
        oscillation_weekly
        is oscillation_daily
        is oscillation_hourly
        is CompositeStatusState.CLEARED
    ):
        oscillation = CompositeBias.BEARISH
    elif (
        oscillation_daily is CompositeStatusState.HOLDING
        and oscillation_hourly is not CompositeStatusState.CLEARED
    ):
        oscillation = CompositeBias.BULLISH
    elif oscillation_daily is CompositeStatusState.CLEARED:
        oscillation = CompositeBias.BEARISH
    elif oscillation_hourly is CompositeStatusState.HOLDING:
        oscillation = CompositeBias.BULLISH
    elif oscillation_hourly is CompositeStatusState.CLEARED:
        oscillation = CompositeBias.BEARISH
    return CompositeBiasPair(trend, oscillation)


def select_composite_decision(
    trend: CompositeBias, oscillation: CompositeBias
) -> CompositeDecision:
    trend = CompositeBias(trend)
    oscillation = CompositeBias(oscillation)
    source_key = f"{trend}-{oscillation}"
    selected_key = source_key if source_key in _DECISIONS else "neutral-neutral"
    label, position = _DECISIONS[selected_key]
    return CompositeDecision(
        source_key=source_key,
        selected_key=selected_key,
        label=label,
        position_range=position,
        fallback_used=selected_key != source_key,
    )


def _up(value: PageSignalState | CompositeStatusState) -> bool:
    return value in {
        PageSignalState.BUY,
        PageSignalState.HOLD,
        CompositeStatusState.HOLDING,
    }


def _down(value: PageSignalState | CompositeStatusState) -> bool:
    return value in {
        PageSignalState.SELL,
        PageSignalState.WAIT,
        CompositeStatusState.CLEARED,
    }


def _direction(
    weekly: PageSignalState,
    daily: PageSignalState,
    hourly: CompositeStatusState,
) -> CompositeDirection:
    weekly = PageSignalState(weekly)
    daily = PageSignalState(daily)
    hourly = CompositeStatusState(hourly)
    if _down(weekly) and (_up(daily) or _up(hourly)):
        return CompositeDirection("weekly_bearish_rebound", 5)
    if _down(weekly):
        return CompositeDirection("weekly_bearish", 3)
    if _up(weekly) and _down(daily):
        return CompositeDirection("daily_pullback", 10)
    if _up(weekly) and _up(daily) and _down(hourly):
        return CompositeDirection("sixty_minute_pullback", 10)
    if _up(weekly) and _up(daily) and _up(hourly):
        return CompositeDirection("multiperiod_bullish", 20)
    return CompositeDirection("insufficient", 5)


def _certainty(
    weekly: PageSignalState,
    daily: PageSignalState,
    trend_hourly: CompositeStatusState,
    oscillation_weekly: CompositeStatusState,
    oscillation_daily: CompositeStatusState,
    oscillation_hourly: CompositeStatusState,
    biases: CompositeBiasPair,
    direction: CompositeDirection,
) -> CertaintyBreakdown:
    trend = (
        (12 if _trend_bullish(weekly) else 0)
        + (12 if _trend_bullish(daily) else 0)
        + (6 if trend_hourly is CompositeStatusState.HOLDING else 0)
    )
    oscillation = (
        (10 if oscillation_weekly is CompositeStatusState.HOLDING else 0)
        + (12 if oscillation_daily is CompositeStatusState.HOLDING else 0)
        + (8 if oscillation_hourly is CompositeStatusState.HOLDING else 0)
    )
    if (
        biases.trend is biases.oscillation is CompositeBias.BULLISH
        or biases.trend is biases.oscillation is CompositeBias.BEARISH
    ):
        alignment = 20
    elif CompositeBias.NEUTRAL in {biases.trend, biases.oscillation}:
        alignment = 10
    else:
        alignment = 0
    uncapped = trend + oscillation + alignment + direction.certainty_points
    cap = 60 if alignment == 0 else 85 if alignment == 10 else None
    total = min(uncapped, cap) if cap is not None else uncapped
    return CertaintyBreakdown(
        trend,
        oscillation,
        alignment,
        direction.certainty_points,
        uncapped,
        total,
        cap,
    )


def _daily_bars_are_ordered(bars: tuple[ProductBar, ...]) -> bool:
    return all(
        current.bar.bar_end > previous.bar.bar_end
        and current.bar.trading_day > previous.bar.trading_day
        for previous, current in zip(bars, bars[1:])
    )


def _daily_bars_share_owner(bars: tuple[ProductBar, ...]) -> bool:
    if not bars:
        return True
    first = bars[0]
    return all(
        bar.frequency is ProductFrequency.DAILY
        and bar.bar.completed
        and bar.bar.observation_eligible
        and bar.bar.product == first.bar.product
        and bar.bar.series_kind == first.bar.series_kind
        and bar.bar.physical_contract == first.bar.physical_contract
        and bar.bar.segment_id == first.bar.segment_id
        for bar in bars
    )


def _finite_page_number(value: Decimal | float) -> float:
    try:
        number = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError("NEWOW_COMPOSITE_PAGE_NUMBER_OUT_OF_RANGE") from error
    if not isfinite(number):
        raise ValueError("NEWOW_COMPOSITE_PAGE_NUMBER_OUT_OF_RANGE")
    return number


def calculate_composite_volatility(
    bars: tuple[ProductBar, ...],
) -> CompositeVolatility | None:
    """Return the page's simple mean-TR ratio; this is not Wilder ATR."""

    try:
        daily_bars = tuple(bars)
    except TypeError as error:
        raise ValueError("NEWOW_COMPOSITE_INVALID_DAILY_BARS") from error
    if not all(isinstance(bar, ProductBar) for bar in daily_bars):
        raise ValueError("NEWOW_COMPOSITE_INVALID_DAILY_BARS")
    if not _daily_bars_share_owner(daily_bars) or not _daily_bars_are_ordered(
        daily_bars
    ):
        raise ValueError("NEWOW_COMPOSITE_INVALID_DAILY_BARS")
    if len(daily_bars) < 6:
        return None
    count = min(20, len(daily_bars) - 1)
    start = len(daily_bars) - count
    true_ranges: list[float] = []
    for index in range(start, len(daily_bars)):
        current = daily_bars[index].bar
        numbers = tuple(
            _finite_page_number(value)
            for value in (
                current.open,
                current.high,
                current.low,
                current.close,
                daily_bars[index - 1].bar.close,
            )
        )
        _, high, low, _, previous_close = numbers
        true_range = _finite_page_number(
            max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        )
        true_ranges.append(true_range)
    if len(true_ranges) < 5:
        return None
    total = 0.0
    for true_range in true_ranges:
        total = _finite_page_number(total + true_range)
    last_close = _finite_page_number(daily_bars[-1].bar.close)
    if last_close <= 0:
        raise ValueError("NEWOW_COMPOSITE_PAGE_NUMBER_OUT_OF_RANGE")
    page_number = _finite_page_number(total / len(true_ranges) / last_close * 1000.0)
    value = Decimal(str(floor(page_number + 0.5) / 10))
    level = (
        VolatilityLevel.LOW
        if value < Decimal("2")
        else VolatilityLevel.MID
        if value < Decimal("4")
        else VolatilityLevel.HIGH
    )
    return CompositeVolatility(value, level, len(true_ranges))


def calculate_first_action_principle(
    weekly: PageSignalState | None,
    daily: PageSignalState | None,
    oscillation_weekly: CompositeStatusState,
    oscillation_daily: CompositeStatusState,
    oscillation_hourly: CompositeStatusState,
) -> FirstActionPrinciple:
    """Return Guiyi-owned tokens over the verified page priority branches."""

    weekly = None if weekly is None else PageSignalState(weekly)
    daily = None if daily is None else PageSignalState(daily)
    oscillation_weekly = CompositeStatusState(oscillation_weekly)
    oscillation_daily = CompositeStatusState(oscillation_daily)
    oscillation_hourly = CompositeStatusState(oscillation_hourly)
    oscillation_holding = (
        oscillation_weekly is CompositeStatusState.HOLDING
        or oscillation_daily is CompositeStatusState.HOLDING
    )
    weekly_text = "周线清仓" if weekly is PageSignalState.SELL else "周线空仓"
    daily_text = "日线清仓" if daily is PageSignalState.SELL else "日线空仓"
    weekly_bullish_text = "周线建仓" if weekly is PageSignalState.BUY else "周线持股"
    daily_bullish_text = "日线建仓" if daily is PageSignalState.BUY else "日线持股"
    oscillation_suffix = (
        "；震荡短暂持有不改趋势，逢高减仓" if oscillation_holding else ""
    )
    rebound_oscillation_suffix = "；震荡短暂持有不改趋势" if oscillation_holding else ""
    if _trend_bearish(weekly) and _trend_bearish(daily):
        return FirstActionPrinciple(
            "weekly_daily_bearish_hard_flat",
            "violate",
            f"第一行动原则：趋势{weekly_text}·{daily_text}（蓝色带），必须空仓观望！",
            "周线与日线同时出现清仓信号，大级别空头确立，无条件空仓等待反转"
            f"{oscillation_suffix}。同步确认大盘趋势状态，大盘蓝色带则整体空仓。",
        )
    if _trend_bearish(weekly) and _trend_bullish(daily):
        return FirstActionPrinciple(
            "weekly_bearish_daily_bullish_rebound_risk",
            "warn",
            f"风险提示：{weekly_text}（蓝色带）· {daily_bullish_text}（黄色带）"
            "——下跌中的反弹",
            "周线仍处空头，日线反弹多为下跌中继的背离走势（易二次探底）。若参与建议仓位"
            " ≤30%，设好止损、不追涨；日线转弱或周线未反转前不加仓"
            f"{rebound_oscillation_suffix}。同步确认大盘趋势状态。",
        )
    if _trend_bullish(weekly) and _trend_bearish(daily):
        return FirstActionPrinciple(
            "weekly_bullish_daily_bearish_wait_for_daily_stability",
            "warn",
            f"提示：{daily_text}（蓝色带）· {weekly_bullish_text}（黄色带）"
            "——等待日线企稳",
            "周线趋势仍向上，日线进入回调/清仓阶段。已持仓者按日线信号减仓；未持仓者等日线"
            "重新出现建仓信号（黄色带）再介入，勿急于抄底。",
        )
    if _trend_bearish(weekly) or _trend_bearish(daily):
        bearish_parts = []
        if _trend_bearish(weekly):
            bearish_parts.append(weekly_text)
        if _trend_bearish(daily):
            bearish_parts.append(daily_text)
        return FirstActionPrinciple(
            "single_bearish_unknown_counterpart_hard_flat",
            "violate",
            f"第一行动原则：趋势{'·'.join(bearish_parts)}（蓝色带），必须空仓观望！",
            "「趋势策略」出现清仓信号即无条件空仓，勿因 60min/日线反弹而逆势操作"
            f"{oscillation_suffix}。同步确认大盘趋势状态，大盘蓝色带则整体空仓。",
        )
    if oscillation_hourly is CompositeStatusState.CLEARED:
        return FirstActionPrinciple(
            "sixty_minute_oscillation_cleared",
            "warn",
            "看大做小：日/周线建仓 · 60分钟已清仓",
            "小周期服从大周期：60min 回踩吸筹（参考吸筹价）确认后再跟随「震荡策略」建仓；"
            "日线仓位不因 60min 清仓而清出。",
        )
    if oscillation_daily is CompositeStatusState.CLEARED:
        return FirstActionPrinciple(
            "daily_oscillation_cleared",
            "warn",
            "震荡日线已清仓 · 趋势建仓",
            "趋势（黄带）向上但震荡日线已清仓，等待震荡吸筹回补信号，勿急于加仓。",
        )
    if oscillation_weekly is CompositeStatusState.CLEARED:
        return FirstActionPrinciple(
            "weekly_oscillation_cleared",
            "warn",
            "震荡周线已清仓 · 趋势建仓",
            "趋势（黄带）向上但震荡周线已清仓，大级别震荡转弱，控制仓位等待回补。",
        )
    return FirstActionPrinciple(
        "normal_observation",
        "ok",
        "遵守：趋势周/日线均建仓（黄色波段）",
        "处于趋势建仓区间，可操作。严格执行「震荡策略」建仓/清仓信号，节奏不乱；"
        "大盘建仓期可顺势操作，仓位按建议执行。",
    )


_WEEK_DAY_MATRIX: dict[str, tuple[str, str, str]] = {
    "buy-buy": ("上涨启动", "bullish", "70-100%"),
    "buy-hold": ("震荡上涨", "bullish", "50-70%"),
    "buy-sell": ("趋势回调", "cautious", "30-50%"),
    "buy-wait": ("筑底反弹", "warning", "10-20%"),
    "hold-buy": ("上涨中继", "bullish", "50-70%"),
    "hold-hold": ("上涨趋势", "bullish", "50-70%"),
    "hold-sell": ("高位震荡", "cautious", "30-50%"),
    "hold-wait": ("高位震荡", "cautious", "30-50%"),
    "sell-buy": ("震荡反弹", "warning", "10-20%"),
    "sell-hold": ("震荡反弹", "warning", "10-20%"),
    "sell-sell": ("下跌趋势", "bearish", "0%"),
    "sell-wait": ("震荡下跌", "bearish", "0%"),
    "wait-buy": ("筑底反转", "bearish", "0%"),
    "wait-hold": ("筑底反弹", "warning", "10-20%"),
    "wait-sell": ("震荡下跌", "bearish", "0%"),
    "wait-wait": ("震荡下跌", "bearish", "0%"),
}


def select_week_day_matrix(
    weekly: PageSignalState, daily: PageSignalState
) -> WeekDayMatrixEntry:
    weekly = PageSignalState(weekly)
    daily = PageSignalState(daily)
    key = f"{weekly}-{daily}"
    name, risk, position = _WEEK_DAY_MATRIX[key]
    return WeekDayMatrixEntry(key, name, risk, position)


def _slot(context: ContextSnapshot, frequency: ProductFrequency) -> ContextSlot:
    return {
        ProductFrequency.WEEKLY: context.weekly,
        ProductFrequency.DAILY: context.daily,
        ProductFrequency.HOURLY: context.hourly,
    }[frequency]


def _matches_slot(
    fact: PageSignalFact | CompositeStatusFact, slot: ContextSlot
) -> bool:
    return (
        slot.status is FeatureRuntimeStatus.READY
        and fact.frequency is slot.frequency
        and fact.bar_end == slot.bar_end
        and fact.physical_contract == slot.physical_contract
        and fact.segment_id == slot.segment_id
        and fact.bar_end <= slot.as_of
    )


def _daily_prefix_matches_context(
    bars: tuple[ProductBar, ...], context: ContextSnapshot
) -> bool:
    if not bars:
        return True
    slot = context.daily
    if slot.frame is None or slot.identity is None or slot.bar_end is None:
        return False
    return (
        _daily_bars_share_owner(bars)
        and _daily_bars_are_ordered(bars)
        and all(
            bar.bar.product == slot.identity.product
            and bar.bar.series_kind == slot.identity.series_kind
            and bar.bar.physical_contract == slot.physical_contract
            and bar.bar.segment_id == slot.segment_id
            and bar.bar.bar_end <= slot.bar_end
            and bar.bar.bar_end <= context.as_of
            for bar in bars
        )
        and bars[-1] == slot.frame.bar
    )


def _source_status(count: int) -> FeatureStatus:
    if count >= 6:
        return FeatureStatus(
            FeatureRuntimeStatus.READY,
            EvidenceStatus.ACTIVE_CODE_VERIFIED,
        )
    return FeatureStatus(
        FeatureRuntimeStatus.WARMING,
        EvidenceStatus.ACTIVE_CODE_VERIFIED,
        "NEWOW_COMPOSITE_VOLATILITY_WARMING",
    )


def _repaint_status() -> FeatureStatus:
    return FeatureStatus(
        FeatureRuntimeStatus.READY,
        EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
    )


def _current_fact_source(
    slot: ContextSlot, fact_names: tuple[str, str], as_of: datetime
) -> CompositeSourceBars:
    if (
        slot.frame is None
        or slot.bar_end is None
        or slot.source_identity is None
        or slot.physical_contract is None
        or slot.segment_id is None
    ):
        raise ValueError("NEWOW_COMPOSITE_INVALID_SOURCE_BARS")
    bar = slot.frame.bar.bar
    return CompositeSourceBars(
        usage=CompositeSourceUsage.CURRENT_FACT,
        fact_names=fact_names,
        frequency=slot.frequency,
        physical_contract=slot.physical_contract,
        segment_id=slot.segment_id,
        source_identities=(slot.source_identity,),
        count=1,
        first_bar_end=slot.bar_end,
        last_bar_end=slot.bar_end,
        first_trading_day=bar.trading_day,
        last_trading_day=bar.trading_day,
        as_of=as_of,
        in_sample=False,
        repainting=False,
        repaint_status=_repaint_status(),
        input_status=FeatureStatus(
            FeatureRuntimeStatus.READY,
            EvidenceStatus.ACTIVE_CODE_VERIFIED,
        ),
    )


def _volatility_source(
    bars: tuple[ProductBar, ...], as_of: datetime
) -> CompositeSourceBars:
    consumed = bars[-21:]
    if not consumed:
        return CompositeSourceBars(
            usage=CompositeSourceUsage.VOLATILITY_PREFIX,
            fact_names=("volatility",),
            frequency=ProductFrequency.DAILY,
            physical_contract=None,
            segment_id=None,
            source_identities=(),
            count=0,
            first_bar_end=None,
            last_bar_end=None,
            first_trading_day=None,
            last_trading_day=None,
            as_of=as_of,
            in_sample=False,
            repainting=False,
            repaint_status=_repaint_status(),
            input_status=_source_status(0),
        )
    first = consumed[0].bar
    last = consumed[-1].bar
    return CompositeSourceBars(
        usage=CompositeSourceUsage.VOLATILITY_PREFIX,
        fact_names=("volatility",),
        frequency=ProductFrequency.DAILY,
        physical_contract=first.physical_contract,
        segment_id=first.segment_id,
        source_identities=tuple(
            dict.fromkeys(item.bar.source_identity for item in consumed)
        ),
        count=len(consumed),
        first_bar_end=first.bar_end,
        last_bar_end=last.bar_end,
        first_trading_day=first.trading_day,
        last_trading_day=last.trading_day,
        as_of=as_of,
        in_sample=False,
        repainting=False,
        repaint_status=_repaint_status(),
        input_status=_source_status(len(consumed)),
    )


def _source_bars(
    context: ContextSnapshot, daily_bars: tuple[ProductBar, ...]
) -> tuple[CompositeSourceBars, ...]:
    return (
        _current_fact_source(
            context.weekly,
            ("trend_weekly", "oscillation_weekly"),
            context.as_of,
        ),
        _current_fact_source(
            context.daily,
            ("trend_daily", "oscillation_daily"),
            context.as_of,
        ),
        _current_fact_source(
            context.hourly,
            ("trend_hourly", "oscillation_hourly"),
            context.as_of,
        ),
        _volatility_source(daily_bars, context.as_of),
    )


def _subfeatures(
    volatility: CompositeVolatility | None,
) -> tuple[CompositeSubfeature, ...]:
    ready_values: tuple[tuple[str, str], ...] = (
        ("composite_decision", COMPOSITE_DECISION_FORMULA_VERSION),
        ("direction", COMPOSITE_DIRECTION_FORMULA_VERSION),
        ("certainty", COMPOSITE_CERTAINTY_FORMULA_VERSION),
        ("first_action", FIRST_ACTION_FORMULA_VERSION),
        ("week_day_matrix", WEEK_DAY_MATRIX_FORMULA_VERSION),
    )
    gaps = (
        (
            "six_combo_output_oracle",
            "NEWOW_SIX_COMBO_OUTPUT_ORACLE_EVIDENCE_REQUIRED",
        ),
        (
            "stable_diagnostic_token_mapping",
            "NEWOW_DIAGNOSTIC_TOKEN_EVIDENCE_REQUIRED",
        ),
        ("ai_copy", "NEWOW_AI_COPY_EVIDENCE_REQUIRED"),
        (
            "intended_warning_semantics",
            "NEWOW_INTENDED_WARNING_SEMANTICS_EVIDENCE_REQUIRED",
        ),
    )
    volatility_feature = CompositeSubfeature(
        "volatility",
        _ready()
        if volatility is not None
        else _warming("NEWOW_COMPOSITE_VOLATILITY_WARMING"),
        volatility,
    )
    return (
        *(CompositeSubfeature(name, _ready(), value) for name, value in ready_values),
        volatility_feature,
        *(CompositeSubfeature(name, _required(reason), None) for name, reason in gaps),
    )


def _unavailable(context: ContextSnapshot, reason: str) -> CompositeExplanationResult:
    return CompositeExplanationResult(
        FeatureRuntimeStatus.UNAVAILABLE,
        EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
        reason,
        context.as_of,
        FORMULA_VERSIONS,
    )


def calculate_composite_explanation(
    context: ContextSnapshot, evidence: object | None
) -> CompositeExplanationResult:
    """Explain verified current facts without creating strategy or trade authority."""

    if not isinstance(context, ContextSnapshot):
        raise ValueError("NEWOW_COMPOSITE_INVALID_CONTEXT")
    if evidence is None:
        return CompositeExplanationResult(
            FeatureRuntimeStatus.EVIDENCE_REQUIRED,
            EvidenceStatus.EVIDENCE_REQUIRED,
            "NEWOW_COMPOSITE_EVIDENCE_REQUIRED",
            context.as_of,
        )
    if not isinstance(evidence, VerifiedCompositeEvidence):
        raise ValueError("NEWOW_COMPOSITE_INVALID_EVIDENCE")
    facts = (
        evidence.trend_weekly,
        evidence.trend_daily,
        evidence.trend_hourly,
        evidence.oscillation_weekly,
        evidence.oscillation_daily,
        evidence.oscillation_hourly,
    )
    if any(fact is None for fact in facts):
        return _unavailable(context, "NEWOW_COMPOSITE_MISSING_PERIOD")
    weekly = evidence.trend_weekly
    daily = evidence.trend_daily
    trend_hourly = evidence.trend_hourly
    oscillation_weekly = evidence.oscillation_weekly
    oscillation_daily = evidence.oscillation_daily
    oscillation_hourly = evidence.oscillation_hourly
    assert weekly is not None
    assert daily is not None
    assert trend_hourly is not None
    assert oscillation_weekly is not None
    assert oscillation_daily is not None
    assert oscillation_hourly is not None
    typed_facts: tuple[PageSignalFact | CompositeStatusFact, ...] = (
        weekly,
        daily,
        trend_hourly,
        oscillation_weekly,
        oscillation_daily,
        oscillation_hourly,
    )
    expected_frequencies = (
        ProductFrequency.WEEKLY,
        ProductFrequency.DAILY,
        ProductFrequency.HOURLY,
        ProductFrequency.WEEKLY,
        ProductFrequency.DAILY,
        ProductFrequency.HOURLY,
    )
    if any(
        fact.frequency is not frequency
        or not _matches_slot(fact, _slot(context, frequency))
        for fact, frequency in zip(typed_facts, expected_frequencies, strict=True)
    ):
        return _unavailable(context, "NEWOW_COMPOSITE_SOURCE_CONTEXT_MISMATCH")
    if not _daily_prefix_matches_context(evidence.daily_bars, context):
        return _unavailable(context, "NEWOW_COMPOSITE_DAILY_PREFIX_INVALID")

    biases = classify_composite_biases(
        weekly.value,
        daily.value,
        trend_hourly.value,
        oscillation_weekly.value,
        oscillation_daily.value,
        oscillation_hourly.value,
    )
    decision = select_composite_decision(biases.trend, biases.oscillation)
    direction = _direction(weekly.value, daily.value, trend_hourly.value)
    certainty = _certainty(
        weekly.value,
        daily.value,
        trend_hourly.value,
        oscillation_weekly.value,
        oscillation_daily.value,
        oscillation_hourly.value,
        biases,
        direction,
    )
    volatility = calculate_composite_volatility(evidence.daily_bars)
    first_action = calculate_first_action_principle(
        weekly.value,
        daily.value,
        oscillation_weekly.value,
        oscillation_daily.value,
        oscillation_hourly.value,
    )
    matrix = select_week_day_matrix(weekly.value, daily.value)
    value = CompositeExplanationValue(
        decision,
        direction,
        certainty,
        volatility,
        first_action,
        matrix,
        _subfeatures(volatility),
        typed_facts,
    )
    return CompositeExplanationResult(
        FeatureRuntimeStatus.READY,
        EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
        None,
        context.as_of,
        FORMULA_VERSIONS,
        _source_bars(context, evidence.daily_bars),
        value,
    )
