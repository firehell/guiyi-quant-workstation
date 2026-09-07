"""Evidence-gated, page-reference target and absorb display facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, localcontext
from enum import StrEnum
from math import isfinite
from typing import TypeGuard

from .context_alignment import ContextSlot, ContextSnapshot
from . import oscillation_channel
from .product_contracts import (
    EvidenceStatus,
    FeatureRuntimeStatus,
    FeatureStatus,
    ProductBar,
    ProductFrequency,
)
from .product_identity import utc_timestamp


PAGE_SELECTION_FORMULA_VERSION = "newow_target_absorb_display_selection_page_v2"
PRICE_GUARD_FORMULA_VERSION = "newow_price_guard_page_v3_1_6"
FUTURES_ADAPTER_VERSION = "guiyi_newow_target_absorb_segment_adapter_v1"
EVIDENCE_MANIFEST_SHA256 = (
    "279aa0c3a88b6e6c5413387a57085dfe4c4d23a34befa751d95ced4c03be962f"
)
STRATEGY_CALC_SHA256 = (
    "80dcfa39afe5511b073ec66858e697243a3e4e994cd610a00568e602610a6192"
)
FROZEN_RESULTS_SHA256 = (
    "163337b4b425241189ae348814610c29b3ff3b24a3c4b03a95da10864efbab3e"
)
_BASE_FORMULAS = (
    PAGE_SELECTION_FORMULA_VERSION,
    PRICE_GUARD_FORMULA_VERSION,
    FUTURES_ADAPTER_VERSION,
)
_ZERO = Decimal("0")
_DISPLAY_QUANTUM = Decimal("0.01")
_JS_TO_FIXED_ABS_LIMIT = 1e21


class PageSelectionPeriod(StrEnum):
    DAY = "day"
    WEEK = "week"
    BEST_AVAILABLE = "best_available"


class PageDisplaySurface(StrEnum):
    SHARED_FUNCTION = "shared_function"
    STATUS_CARD = "status_card"


class PageSignalState(StrEnum):
    WAIT = "wait"
    SELL = "sell"
    BUY = "buy"
    HOLD = "hold"


def _text(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("NEWOW_TARGET_ABSORB_INVALID_TEXT")


def _positive(value: Decimal | None) -> TypeGuard[Decimal]:
    return isinstance(value, Decimal) and value.is_finite() and value > _ZERO


def _nonnegative(value: Decimal | None) -> TypeGuard[Decimal]:
    return isinstance(value, Decimal) and value.is_finite() and value >= _ZERO


def _finite_js_number(value: Decimal | None) -> float | None:
    if value is None:
        return None
    if not isinstance(value, Decimal):
        raise ValueError("NEWOW_TARGET_ABSORB_INVALID_PAGE_NUMBER")
    if not value.is_finite():
        return None
    number = float(value)
    if not isfinite(number):
        return None
    if abs(number) >= _JS_TO_FIXED_ABS_LIMIT:
        raise ValueError("NEWOW_TARGET_ABSORB_PAGE_NUMBER_OUT_OF_SAFE_DOMAIN")
    return number


def _js_number_to_fixed_2(number: float) -> Decimal:
    """Round the binary Number value with the page's toFixed tie direction."""

    with localcontext() as context:
        context.prec = 64
        context.rounding = ROUND_HALF_UP
        return Decimal.from_float(number).quantize(_DISPLAY_QUANTUM)


def guard_page_price(value: Decimal | None, previous_close: Decimal | None) -> Decimal:
    """Page-only JS Number/toFixed guard; previous-close provenance stays unresolved."""

    number = _finite_js_number(value)
    if number is None:
        return _ZERO
    baseline = _finite_js_number(previous_close)
    if baseline is None or baseline <= 0:
        return _js_number_to_fixed_2(number) if number > 0 else _ZERO
    guarded = min(max(number, baseline * 0.5), baseline * 2.0)
    return _js_number_to_fixed_2(guarded)


@dataclass(frozen=True, slots=True)
class PagePriceFact:
    """One page price candidate bound to a Guiyi context source."""

    value: Decimal
    frequency: ProductFrequency
    bar_end: datetime
    physical_contract: str
    segment_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            raise ValueError("NEWOW_TARGET_ABSORB_INVALID_PRICE_FACT")
        try:
            frequency = ProductFrequency(self.frequency)
            bar_end = utc_timestamp(self.bar_end)
        except (TypeError, ValueError) as error:
            raise ValueError("NEWOW_TARGET_ABSORB_INVALID_PRICE_FACT") from error
        _text(self.physical_contract)
        _text(self.segment_id)
        object.__setattr__(self, "frequency", frequency)
        object.__setattr__(self, "bar_end", bar_end)


@dataclass(frozen=True, slots=True)
class PageSignalFact:
    """One closed page signal bound to the matching Guiyi context source."""

    value: PageSignalState
    frequency: ProductFrequency
    bar_end: datetime
    physical_contract: str
    segment_id: str

    def __post_init__(self) -> None:
        try:
            value = PageSignalState(self.value)
            frequency = ProductFrequency(self.frequency)
            bar_end = utc_timestamp(self.bar_end)
        except (TypeError, ValueError) as error:
            raise ValueError("NEWOW_TARGET_ABSORB_INVALID_SIGNAL") from error
        _text(self.physical_contract)
        _text(self.segment_id)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "frequency", frequency)
        object.__setattr__(self, "bar_end", bar_end)


@dataclass(frozen=True, slots=True)
class PageCrossFact:
    """One weekly cross flag bound to the matching Guiyi context source."""

    value: bool
    frequency: ProductFrequency
    bar_end: datetime
    physical_contract: str
    segment_id: str

    def __post_init__(self) -> None:
        if type(self.value) is not bool:
            raise ValueError("NEWOW_TARGET_ABSORB_INVALID_CROSS_FACT")
        try:
            frequency = ProductFrequency(self.frequency)
            bar_end = utc_timestamp(self.bar_end)
        except (TypeError, ValueError) as error:
            raise ValueError("NEWOW_TARGET_ABSORB_INVALID_CROSS_FACT") from error
        _text(self.physical_contract)
        _text(self.segment_id)
        object.__setattr__(self, "frequency", frequency)
        object.__setattr__(self, "bar_end", bar_end)


def _usable(fact: PagePriceFact | None) -> TypeGuard[PagePriceFact]:
    return fact is not None and _positive(fact.value)


def _fact_value(fact: PagePriceFact | None) -> Decimal:
    if not _usable(fact):
        raise ValueError("NEWOW_TARGET_ABSORB_PRICE_UNAVAILABLE")
    return fact.value


@dataclass(frozen=True, slots=True)
class PageSelectionInputs:
    """Frozen page fields; no field is inferred from current-period bars."""

    signal_daily: PageSignalFact
    signal_weekly: PageSignalFact
    cross_weekly_buy: PageCrossFact
    current_price: PagePriceFact
    target_daily: PagePriceFact | None = None
    target_weekly: PagePriceFact | None = None
    target: PagePriceFact | None = None
    high: PagePriceFact | None = None
    cost_daily: PagePriceFact | None = None
    cost_weekly: PagePriceFact | None = None
    cost: PagePriceFact | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.signal_daily, PageSignalFact) or not isinstance(
            self.signal_weekly, PageSignalFact
        ):
            raise ValueError("NEWOW_TARGET_ABSORB_INVALID_SELECTION_INPUT")
        if not isinstance(self.cross_weekly_buy, PageCrossFact):
            raise ValueError("NEWOW_TARGET_ABSORB_INVALID_SELECTION_INPUT")
        if not isinstance(self.current_price, PagePriceFact):
            raise ValueError("NEWOW_TARGET_ABSORB_INVALID_SELECTION_INPUT")
        for value in (
            self.target_daily,
            self.target_weekly,
            self.target,
            self.high,
            self.cost_daily,
            self.cost_weekly,
            self.cost,
        ):
            if value is not None and not isinstance(value, PagePriceFact):
                raise ValueError("NEWOW_TARGET_ABSORB_INVALID_SELECTION_INPUT")


@dataclass(frozen=True, slots=True)
class SelectedPagePrice:
    fact: PagePriceFact
    branch: str

    def __post_init__(self) -> None:
        if not isinstance(self.fact, PagePriceFact) or not _usable(self.fact):
            raise ValueError("NEWOW_TARGET_ABSORB_INVALID_SELECTION")
        _text(self.branch)


@dataclass(frozen=True, slots=True)
class PagePriceSelection:
    target: SelectedPagePrice | None
    absorb: SelectedPagePrice | None


@dataclass(frozen=True, slots=True)
class VerifiedTargetAbsorbEvidence:
    """Exact identities for the frozen page evidence, plus caller-supplied facts."""

    period: PageSelectionPeriod
    view_frequency: ProductFrequency
    display_surface: PageDisplaySurface
    inputs: PageSelectionInputs
    weekly_channel_bars: tuple[ProductBar, ...] = ()
    manifest_sha256: str = EVIDENCE_MANIFEST_SHA256
    strategy_calc_sha256: str = STRATEGY_CALC_SHA256
    frozen_results_sha256: str = FROZEN_RESULTS_SHA256

    def __post_init__(self) -> None:
        try:
            period = PageSelectionPeriod(self.period)
            frequency = ProductFrequency(self.view_frequency)
            display_surface = PageDisplaySurface(self.display_surface)
        except (TypeError, ValueError) as error:
            raise ValueError("NEWOW_TARGET_ABSORB_INVALID_EVIDENCE") from error
        if not isinstance(self.inputs, PageSelectionInputs):
            raise ValueError("NEWOW_TARGET_ABSORB_INVALID_EVIDENCE")
        expected_frequency = {
            PageSelectionPeriod.DAY: ProductFrequency.DAILY,
            PageSelectionPeriod.WEEK: ProductFrequency.WEEKLY,
        }.get(period)
        if expected_frequency is not None and frequency is not expected_frequency:
            raise ValueError("NEWOW_TARGET_ABSORB_INVALID_EVIDENCE")
        if (
            self.manifest_sha256 != EVIDENCE_MANIFEST_SHA256
            or self.strategy_calc_sha256 != STRATEGY_CALC_SHA256
            or self.frozen_results_sha256 != FROZEN_RESULTS_SHA256
        ):
            raise ValueError("NEWOW_TARGET_ABSORB_EVIDENCE_IDENTITY")
        bars = tuple(self.weekly_channel_bars)
        if not all(isinstance(bar, ProductBar) for bar in bars):
            raise ValueError("NEWOW_TARGET_ABSORB_INVALID_EVIDENCE")
        object.__setattr__(self, "period", period)
        object.__setattr__(self, "view_frequency", frequency)
        object.__setattr__(self, "display_surface", display_surface)
        object.__setattr__(self, "weekly_channel_bars", bars)


def _selected(fact: PagePriceFact | None, branch: str) -> SelectedPagePrice | None:
    return SelectedPagePrice(fact, branch) if _usable(fact) else None


def _select_target(
    inputs: PageSelectionInputs, period: PageSelectionPeriod
) -> SelectedPagePrice | None:
    day = inputs.target_daily
    week = inputs.target_weekly
    generic = inputs.target
    has_day = _usable(day)
    has_week = _usable(week)
    daily_signal = inputs.signal_daily.value
    weekly_signal = inputs.signal_weekly.value
    day_above = daily_signal not in {PageSignalState.WAIT, PageSignalState.SELL}
    week_above = (
        weekly_signal
        not in {
            PageSignalState.WAIT,
            PageSignalState.SELL,
        }
        or inputs.cross_weekly_buy.value
    )
    price = (
        inputs.current_price.value if _positive(inputs.current_price.value) else None
    )

    if has_day or has_week:
        if day_above and week_above:
            if period is PageSelectionPeriod.WEEK and has_week:
                return _selected(week, "target_week_view")
            if daily_signal is PageSignalState.BUY and has_day:
                if has_week and _positive(price) and price >= _fact_value(day):
                    return _selected(week, "target_daily_breakout_weekly")
                return _selected(day, "target_daily_buy")
            if weekly_signal is PageSignalState.BUY and has_week:
                return _selected(week, "target_weekly_buy")
            if period is PageSelectionPeriod.DAY:
                return _selected(day, "target_daily_hold") or _selected(
                    week, "target_weekly_fallback"
                )
            if has_week:
                return _selected(week, "target_weekly_hold")
            if (
                week_above
                and _usable(generic)
                and (not has_day or generic.value > _fact_value(day))
            ):
                return _selected(generic, "target_generic_weekly_fallback")
            return _selected(day, "target_daily_fallback") or _selected(
                generic, "target_generic_fallback"
            )
        if day_above and has_day:
            if has_week and _positive(price) and price >= _fact_value(day):
                return _selected(week, "target_daily_breakout_weekly")
            return _selected(day, "target_daily_positive")
        if week_above and has_week:
            return _selected(week, "target_weekly_positive")
        if (
            not day_above
            and has_day
            and has_week
            and _positive(price)
            and price >= _fact_value(day)
        ):
            return _selected(day, "target_daily_breakout")
        if has_day:
            return _selected(day, "target_daily_flat")
        if period is not PageSelectionPeriod.DAY and has_week:
            return _selected(week, "target_weekly_fallback")
        return None

    if _usable(inputs.high) and _positive(price) and inputs.high.value > price:
        return _selected(inputs.high, "target_high_fallback")
    return _selected(generic, "target_generic_fallback")


def _select_absorb(
    inputs: PageSelectionInputs, period: PageSelectionPeriod
) -> SelectedPagePrice | None:
    day = inputs.cost_daily
    week = inputs.cost_weekly
    daily_signal = inputs.signal_daily.value
    weekly_signal = inputs.signal_weekly.value
    day_above = daily_signal not in {PageSignalState.WAIT, PageSignalState.SELL}
    week_above = weekly_signal not in {
        PageSignalState.WAIT,
        PageSignalState.SELL,
    }
    allow_week = period is not PageSelectionPeriod.DAY

    if day_above and week_above:
        if period is PageSelectionPeriod.WEEK and _usable(week):
            return _selected(week, "absorb_week_view")
        if daily_signal is PageSignalState.BUY and _usable(day):
            return _selected(day, "absorb_daily_buy")
        if weekly_signal is PageSignalState.BUY and _usable(week):
            return _selected(week, "absorb_weekly_buy")
        return _selected(day, "absorb_daily_hold") or (
            _selected(week, "absorb_weekly_fallback") if allow_week else None
        )
    if day_above:
        return _selected(day, "absorb_daily_positive") or (
            _selected(week, "absorb_weekly_fallback") if allow_week else None
        )
    if week_above:
        return (
            _selected(day, "absorb_daily_sensitive")
            or _selected(week, "absorb_weekly_positive")
            or _selected(inputs.cost, "absorb_generic_fallback")
        )
    if allow_week and _usable(week):
        return _selected(week, "absorb_weekly_flat")
    return _selected(day, "absorb_daily_flat")


def select_page_prices(
    inputs: PageSelectionInputs, period: PageSelectionPeriod
) -> PagePriceSelection:
    """Reproduce the verified page selection branches before UI fallback/guard."""

    if not isinstance(inputs, PageSelectionInputs):
        raise ValueError("NEWOW_TARGET_ABSORB_INVALID_SELECTION_INPUT")
    try:
        selected_period = PageSelectionPeriod(period)
    except (TypeError, ValueError) as error:
        raise ValueError("NEWOW_TARGET_ABSORB_INVALID_SELECTION_INPUT") from error
    return PagePriceSelection(
        target=_select_target(inputs, selected_period),
        absorb=_select_absorb(inputs, selected_period),
    )


@dataclass(frozen=True, slots=True)
class TargetAbsorbSubfeature:
    name: str
    status: FeatureStatus
    value: object | None

    def __post_init__(self) -> None:
        _text(self.name)
        if not isinstance(self.status, FeatureStatus):
            raise ValueError("NEWOW_TARGET_ABSORB_INVALID_SUBFEATURE")


@dataclass(frozen=True, slots=True)
class TargetAbsorbDisplayPrice:
    raw_value: Decimal
    display_value: Decimal
    branch: str
    source_frequency: ProductFrequency
    bar_end: datetime
    physical_contract: str
    segment_id: str

    def __post_init__(self) -> None:
        if not _positive(self.raw_value) or not _nonnegative(self.display_value):
            raise ValueError("NEWOW_TARGET_ABSORB_INVALID_DISPLAY")
        _text(self.branch)
        _text(self.physical_contract)
        _text(self.segment_id)
        object.__setattr__(
            self, "source_frequency", ProductFrequency(self.source_frequency)
        )
        object.__setattr__(self, "bar_end", utc_timestamp(self.bar_end))


@dataclass(frozen=True, slots=True)
class TargetAbsorbValue:
    target: TargetAbsorbDisplayPrice
    absorb: TargetAbsorbDisplayPrice
    previous_close: None
    display_surface: PageDisplaySurface
    subfeatures: tuple[TargetAbsorbSubfeature, ...]
    evidence_manifest_sha256: str = EVIDENCE_MANIFEST_SHA256
    inherited_frozen_results_sha256: str = FROZEN_RESULTS_SHA256

    def __post_init__(self) -> None:
        if not isinstance(self.target, TargetAbsorbDisplayPrice) or not isinstance(
            self.absorb, TargetAbsorbDisplayPrice
        ):
            raise ValueError("NEWOW_TARGET_ABSORB_INVALID_VALUE")
        object.__setattr__(
            self, "display_surface", PageDisplaySurface(self.display_surface)
        )
        features = tuple(self.subfeatures)
        if len({feature.name for feature in features}) != len(features):
            raise ValueError("NEWOW_TARGET_ABSORB_INVALID_VALUE")
        object.__setattr__(self, "subfeatures", features)


@dataclass(frozen=True, slots=True)
class TargetAbsorbResult:
    status: FeatureRuntimeStatus
    evidence_status: EvidenceStatus
    reason_code: str | None
    as_of: datetime
    display_surface: PageDisplaySurface | None
    formula_versions: tuple[str, ...] = ()
    source_bars: tuple[PagePriceFact, ...] = ()
    decision_facts: tuple[PagePriceFact | PageSignalFact | PageCrossFact, ...] = ()
    value: TargetAbsorbValue | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", FeatureRuntimeStatus(self.status))
        object.__setattr__(
            self, "evidence_status", EvidenceStatus(self.evidence_status)
        )
        object.__setattr__(self, "as_of", utc_timestamp(self.as_of))
        if self.display_surface is not None:
            object.__setattr__(
                self,
                "display_surface",
                PageDisplaySurface(self.display_surface),
            )
        if self.status is not FeatureRuntimeStatus.READY:
            _text(self.reason_code)
        object.__setattr__(self, "formula_versions", tuple(self.formula_versions))
        object.__setattr__(self, "source_bars", tuple(self.source_bars))
        object.__setattr__(self, "decision_facts", tuple(self.decision_facts))


def _status(
    runtime: FeatureRuntimeStatus,
    evidence: EvidenceStatus,
    reason: str | None = None,
) -> FeatureStatus:
    return FeatureStatus(runtime, evidence, reason)


def _result(
    context: ContextSnapshot,
    display_surface: PageDisplaySurface,
    runtime: FeatureRuntimeStatus,
    evidence: EvidenceStatus,
    reason: str,
    formula_versions: tuple[str, ...],
) -> TargetAbsorbResult:
    return TargetAbsorbResult(
        runtime,
        evidence,
        reason,
        context.as_of,
        display_surface,
        formula_versions,
    )


def _slot(context: ContextSnapshot, frequency: ProductFrequency) -> ContextSlot:
    return {
        ProductFrequency.WEEKLY: context.weekly,
        ProductFrequency.DAILY: context.daily,
        ProductFrequency.HOURLY: context.hourly,
    }[frequency]


ContextBoundFact = PagePriceFact | PageSignalFact | PageCrossFact


def _fact_matches_slot(fact: ContextBoundFact, slot: ContextSlot) -> bool:
    return (
        slot.status is FeatureRuntimeStatus.READY
        and slot.bar_end == fact.bar_end
        and slot.physical_contract == fact.physical_contract
        and slot.segment_id == fact.segment_id
        and slot.frequency is fact.frequency
    )


def _same_owner(fact: ContextBoundFact, slot: ContextSlot) -> bool:
    return (
        slot.physical_contract == fact.physical_contract
        and slot.segment_id == fact.segment_id
    )


def _named_input_frequencies_are_valid(
    inputs: PageSelectionInputs,
    view_frequency: ProductFrequency,
) -> bool:
    expected = (
        (inputs.signal_daily, ProductFrequency.DAILY),
        (inputs.signal_weekly, ProductFrequency.WEEKLY),
        (inputs.cross_weekly_buy, ProductFrequency.WEEKLY),
        (inputs.current_price, view_frequency),
        (inputs.target_daily, ProductFrequency.DAILY),
        (inputs.cost_daily, ProductFrequency.DAILY),
        (inputs.target_weekly, ProductFrequency.WEEKLY),
        (inputs.cost_weekly, ProductFrequency.WEEKLY),
    )
    return all(
        fact is None or fact.frequency is frequency for fact, frequency in expected
    )


def _input_facts(inputs: PageSelectionInputs) -> tuple[ContextBoundFact, ...]:
    prices = (
        inputs.current_price,
        inputs.target_daily,
        inputs.target_weekly,
        inputs.target,
        inputs.high,
        inputs.cost_daily,
        inputs.cost_weekly,
        inputs.cost,
    )
    return (
        inputs.signal_daily,
        inputs.signal_weekly,
        inputs.cross_weekly_buy,
        *(price for price in prices if price is not None),
    )


def _formulas(evidence: VerifiedTargetAbsorbEvidence) -> tuple[str, ...]:
    if (
        evidence.display_surface is PageDisplaySurface.STATUS_CARD
        and evidence.period is PageSelectionPeriod.WEEK
    ):
        return (*_BASE_FORMULAS, oscillation_channel.CHANNEL_FORMULA_VERSION)
    return _BASE_FORMULAS


def _weekly_override(
    context: ContextSnapshot,
    evidence: VerifiedTargetAbsorbEvidence,
) -> PagePriceSelection | TargetAbsorbResult:
    bars = evidence.weekly_channel_bars
    formulas = _formulas(evidence)
    if len(bars) < 10:
        return _result(
            context,
            evidence.display_surface,
            FeatureRuntimeStatus.EVIDENCE_REQUIRED,
            EvidenceStatus.EVIDENCE_REQUIRED,
            "NEWOW_TARGET_ABSORB_WEEKLY_WARMUP_EVIDENCE_REQUIRED",
            formulas,
        )
    slot = context.weekly
    if slot.status is not FeatureRuntimeStatus.READY:
        return _result(
            context,
            evidence.display_surface,
            FeatureRuntimeStatus.UNAVAILABLE,
            EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
            "NEWOW_TARGET_ABSORB_VIEW_CONTEXT_UNAVAILABLE",
            formulas,
        )
    if (
        slot.identity is None
        or slot.frame is None
        or slot.bar_end is None
        or slot.physical_contract is None
        or slot.segment_id is None
    ):
        return _result(
            context,
            evidence.display_surface,
            FeatureRuntimeStatus.UNAVAILABLE,
            EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
            "NEWOW_TARGET_ABSORB_VIEW_CONTEXT_UNAVAILABLE",
            formulas,
        )
    bar_ends = tuple(bar.bar.bar_end for bar in bars)
    trading_days = tuple(bar.bar.trading_day for bar in bars)
    if (
        any(
            bar.frequency is not ProductFrequency.WEEKLY
            or bar.bar.product != slot.identity.product
            or bar.bar.series_kind != slot.identity.series_kind
            or bar.bar.physical_contract != slot.physical_contract
            or bar.bar.segment_id != slot.segment_id
            or bar.bar.bar_end > slot.bar_end
            or bar.bar.bar_end > context.as_of
            for bar in bars
        )
        or any(current <= previous for previous, current in zip(bar_ends, bar_ends[1:]))
        or any(
            current < previous
            for previous, current in zip(trading_days, trading_days[1:])
        )
        or bars[-1].bar.bar_end != slot.bar_end
        or bars[-1] != slot.frame.bar
    ):
        return _result(
            context,
            evidence.display_surface,
            FeatureRuntimeStatus.UNAVAILABLE,
            EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
            "NEWOW_TARGET_ABSORB_SOURCE_CONTEXT_MISMATCH",
            formulas,
        )
    channel = oscillation_channel.calculate_channel_series(
        tuple(bar.bar for bar in bars), period=10
    )[-1]
    target_fact = PagePriceFact(
        channel.upper,
        slot.frequency,
        slot.bar_end,
        slot.physical_contract,
        slot.segment_id,
    )
    absorb_fact = PagePriceFact(
        channel.lower,
        slot.frequency,
        slot.bar_end,
        slot.physical_contract,
        slot.segment_id,
    )
    return PagePriceSelection(
        SelectedPagePrice(target_fact, "weekly_channel_override"),
        SelectedPagePrice(absorb_fact, "weekly_channel_override"),
    )


def _display(selection: SelectedPagePrice) -> TargetAbsorbDisplayPrice:
    fact = selection.fact
    return TargetAbsorbDisplayPrice(
        raw_value=fact.value,
        display_value=guard_page_price(fact.value, None),
        branch=selection.branch,
        source_frequency=fact.frequency,
        bar_end=fact.bar_end,
        physical_contract=fact.physical_contract,
        segment_id=fact.segment_id,
    )


def _subfeatures(
    period: PageSelectionPeriod,
    display_surface: PageDisplaySurface,
) -> tuple[TargetAbsorbSubfeature, ...]:
    research_ready = _status(
        FeatureRuntimeStatus.READY, EvidenceStatus.RESEARCH_EVIDENCE_ONLY
    )
    active_ready = _status(
        FeatureRuntimeStatus.READY, EvidenceStatus.ACTIVE_CODE_VERIFIED
    )
    required = (
        ("previous_close_activation", "NEWOW_PREVIOUS_CLOSE_SOURCE_EVIDENCE_REQUIRED"),
        (
            "unified_short_history_warmup",
            "NEWOW_TARGET_ABSORB_WARMUP_EVIDENCE_REQUIRED",
        ),
        ("original_page_timing", "NEWOW_TARGET_ABSORB_TIMING_EVIDENCE_REQUIRED"),
        (
            "futures_cross_segment_parity",
            "NEWOW_TARGET_ABSORB_FUTURES_SEGMENT_EVIDENCE_REQUIRED",
        ),
    )
    weekly = (
        TargetAbsorbSubfeature(
            "weekly_status_card_override",
            research_ready,
            oscillation_channel.CHANNEL_FORMULA_VERSION,
        )
        if (
            period is PageSelectionPeriod.WEEK
            and display_surface is PageDisplaySurface.STATUS_CARD
        )
        else TargetAbsorbSubfeature(
            "weekly_status_card_override",
            _status(
                FeatureRuntimeStatus.NOT_APPLICABLE,
                EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
                "NEWOW_WEEKLY_OVERRIDE_NOT_APPLICABLE",
            ),
            None,
        )
    )
    return (
        TargetAbsorbSubfeature(
            "page_selection", research_ready, PAGE_SELECTION_FORMULA_VERSION
        ),
        TargetAbsorbSubfeature("display_surface", research_ready, display_surface),
        weekly,
        TargetAbsorbSubfeature(
            "price_guard_algorithm", research_ready, PRICE_GUARD_FORMULA_VERSION
        ),
        TargetAbsorbSubfeature(
            "current_context_segment_adapter", active_ready, FUTURES_ADAPTER_VERSION
        ),
        *(
            TargetAbsorbSubfeature(
                name,
                _status(
                    FeatureRuntimeStatus.EVIDENCE_REQUIRED,
                    EvidenceStatus.EVIDENCE_REQUIRED,
                    reason,
                ),
                None,
            )
            for name, reason in required
        ),
    )


def calculate_target_absorb(
    context: ContextSnapshot, evidence: object | None
) -> TargetAbsorbResult:
    """Select page display facts without inferring missing evidence or owners."""

    if not isinstance(context, ContextSnapshot):
        raise ValueError("NEWOW_TARGET_ABSORB_INVALID_CONTEXT")
    if evidence is None:
        return TargetAbsorbResult(
            status=FeatureRuntimeStatus.EVIDENCE_REQUIRED,
            evidence_status=EvidenceStatus.EVIDENCE_REQUIRED,
            reason_code="NEWOW_TARGET_ABSORB_EVIDENCE_REQUIRED",
            as_of=context.as_of,
            display_surface=None,
            value=None,
        )
    if not isinstance(evidence, VerifiedTargetAbsorbEvidence):
        raise ValueError("NEWOW_TARGET_ABSORB_INVALID_EVIDENCE")
    formulas = _formulas(evidence)
    if not _named_input_frequencies_are_valid(evidence.inputs, evidence.view_frequency):
        return _result(
            context,
            evidence.display_surface,
            FeatureRuntimeStatus.UNAVAILABLE,
            EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
            "NEWOW_TARGET_ABSORB_SOURCE_FREQUENCY_MISMATCH",
            formulas,
        )

    view_slot = _slot(context, evidence.view_frequency)
    if view_slot.status is not FeatureRuntimeStatus.READY:
        return _result(
            context,
            evidence.display_surface,
            FeatureRuntimeStatus.UNAVAILABLE,
            EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
            "NEWOW_TARGET_ABSORB_VIEW_CONTEXT_UNAVAILABLE",
            formulas,
        )
    if any(
        fact.bar_end > context.as_of
        or not _fact_matches_slot(fact, _slot(context, fact.frequency))
        or not _same_owner(fact, view_slot)
        for fact in _input_facts(evidence.inputs)
    ):
        return _result(
            context,
            evidence.display_surface,
            FeatureRuntimeStatus.UNAVAILABLE,
            EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
            "NEWOW_TARGET_ABSORB_SOURCE_CONTEXT_MISMATCH",
            formulas,
        )
    selected: PagePriceSelection | TargetAbsorbResult
    if (
        evidence.period is PageSelectionPeriod.WEEK
        and evidence.display_surface is PageDisplaySurface.STATUS_CARD
    ):
        selected = _weekly_override(context, evidence)
    else:
        selected = select_page_prices(evidence.inputs, evidence.period)
    if isinstance(selected, TargetAbsorbResult):
        return selected
    if selected.target is None or selected.absorb is None:
        return _result(
            context,
            evidence.display_surface,
            FeatureRuntimeStatus.UNAVAILABLE,
            EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
            "NEWOW_TARGET_ABSORB_PRICE_UNAVAILABLE",
            formulas,
        )

    facts = (selected.target.fact, selected.absorb.fact)
    if any(
        not _fact_matches_slot(fact, _slot(context, fact.frequency))
        or not _same_owner(fact, view_slot)
        for fact in facts
    ):
        return _result(
            context,
            evidence.display_surface,
            FeatureRuntimeStatus.UNAVAILABLE,
            EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
            "NEWOW_TARGET_ABSORB_SOURCE_CONTEXT_MISMATCH",
            formulas,
        )
    source_bars = tuple(dict.fromkeys(facts))
    value = TargetAbsorbValue(
        target=_display(selected.target),
        absorb=_display(selected.absorb),
        previous_close=None,
        display_surface=evidence.display_surface,
        subfeatures=_subfeatures(evidence.period, evidence.display_surface),
    )
    return TargetAbsorbResult(
        status=FeatureRuntimeStatus.READY,
        evidence_status=EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
        reason_code=None,
        as_of=context.as_of,
        display_surface=evidence.display_surface,
        formula_versions=formulas,
        source_bars=source_bars,
        decision_facts=_input_facts(evidence.inputs),
        value=value,
    )
