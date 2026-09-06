"""Evidence-gated, page-reference target and absorb display facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, localcontext
from enum import StrEnum
from typing import TypeGuard

from .context_alignment import ContextSlot, ContextSnapshot
from .oscillation_channel import calculate_channel_series
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
_FORMULAS = (
    PAGE_SELECTION_FORMULA_VERSION,
    PRICE_GUARD_FORMULA_VERSION,
    FUTURES_ADAPTER_VERSION,
)
_ZERO = Decimal("0")
_DISPLAY_QUANTUM = Decimal("0.01")


class PageSelectionPeriod(StrEnum):
    DAY = "day"
    WEEK = "week"
    BEST_AVAILABLE = "best_available"


def _text(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("NEWOW_TARGET_ABSORB_INVALID_TEXT")


def _positive(value: Decimal | None) -> TypeGuard[Decimal]:
    return isinstance(value, Decimal) and value.is_finite() and value > _ZERO


def guard_page_price(value: Decimal | None, previous_close: Decimal | None) -> Decimal:
    """Reproduce the named page guard without resolving previous-close origin."""

    if not _positive(value):
        return _ZERO
    assert isinstance(value, Decimal)
    baseline = previous_close if _positive(previous_close) else None
    guarded = value
    if baseline is not None:
        guarded = min(max(value, baseline * Decimal("0.5")), baseline * Decimal("2"))
    with localcontext() as context:
        context.prec = 28
        context.rounding = ROUND_HALF_UP
        return guarded.quantize(_DISPLAY_QUANTUM)


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


def _usable(fact: PagePriceFact | None) -> TypeGuard[PagePriceFact]:
    return fact is not None and _positive(fact.value)


def _fact_value(fact: PagePriceFact | None) -> Decimal:
    if not _usable(fact):
        raise ValueError("NEWOW_TARGET_ABSORB_PRICE_UNAVAILABLE")
    return fact.value


@dataclass(frozen=True, slots=True)
class PageSelectionInputs:
    """Frozen page fields; no field is inferred from current-period bars."""

    signal_daily: str = "wait"
    signal_weekly: str = "wait"
    cross_weekly_buy: bool = False
    current_price: Decimal | None = None
    target_daily: PagePriceFact | None = None
    target_weekly: PagePriceFact | None = None
    target: PagePriceFact | None = None
    high: PagePriceFact | None = None
    cost_daily: PagePriceFact | None = None
    cost_weekly: PagePriceFact | None = None
    cost: PagePriceFact | None = None

    def __post_init__(self) -> None:
        for signal in (self.signal_daily, self.signal_weekly):
            _text(signal)
        if type(self.cross_weekly_buy) is not bool:
            raise ValueError("NEWOW_TARGET_ABSORB_INVALID_SELECTION_INPUT")
        if self.current_price is not None and not isinstance(
            self.current_price, Decimal
        ):
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
        object.__setattr__(self, "signal_daily", self.signal_daily.lower())
        object.__setattr__(self, "signal_weekly", self.signal_weekly.lower())


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
    inputs: PageSelectionInputs
    weekly_channel_bars: tuple[ProductBar, ...] = ()
    manifest_sha256: str = EVIDENCE_MANIFEST_SHA256
    strategy_calc_sha256: str = STRATEGY_CALC_SHA256
    frozen_results_sha256: str = FROZEN_RESULTS_SHA256

    def __post_init__(self) -> None:
        try:
            period = PageSelectionPeriod(self.period)
            frequency = ProductFrequency(self.view_frequency)
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
    day_above = inputs.signal_daily not in {"wait", "sell"}
    week_above = inputs.signal_weekly not in {"wait", "sell"} or inputs.cross_weekly_buy
    price = inputs.current_price

    if has_day or has_week:
        if day_above and week_above:
            if period is PageSelectionPeriod.WEEK and has_week:
                return _selected(week, "target_week_view")
            if inputs.signal_daily == "buy" and has_day:
                if has_week and _positive(price) and price >= _fact_value(day):
                    return _selected(week, "target_daily_breakout_weekly")
                return _selected(day, "target_daily_buy")
            if inputs.signal_weekly == "buy" and has_week:
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
            return _selected(
                week if week_above else day,
                "target_weekly_breakout" if week_above else "target_daily_breakout",
            )
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
    day_above = inputs.signal_daily not in {"wait", "sell"}
    week_above = inputs.signal_weekly not in {"wait", "sell"}
    allow_week = period is not PageSelectionPeriod.DAY

    if day_above and week_above:
        if period is PageSelectionPeriod.WEEK and _usable(week):
            return _selected(week, "absorb_week_view")
        if inputs.signal_daily == "buy" and _usable(day):
            return _selected(day, "absorb_daily_buy")
        if inputs.signal_weekly == "buy" and _usable(week):
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
        if not _positive(self.raw_value) or not _positive(self.display_value):
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
    subfeatures: tuple[TargetAbsorbSubfeature, ...]
    evidence_manifest_sha256: str = EVIDENCE_MANIFEST_SHA256
    inherited_frozen_results_sha256: str = FROZEN_RESULTS_SHA256

    def __post_init__(self) -> None:
        if not isinstance(self.target, TargetAbsorbDisplayPrice) or not isinstance(
            self.absorb, TargetAbsorbDisplayPrice
        ):
            raise ValueError("NEWOW_TARGET_ABSORB_INVALID_VALUE")
        features = tuple(self.subfeatures)
        if len({feature.name for feature in features}) != len(features):
            raise ValueError("NEWOW_TARGET_ABSORB_INVALID_VALUE")
        object.__setattr__(self, "subfeatures", features)


@dataclass(frozen=True, slots=True)
class TargetAbsorbResult:
    status: FeatureRuntimeStatus
    evidence_status: EvidenceStatus
    reason_code: str | None
    formula_versions: tuple[str, ...] = ()
    source_bars: tuple[PagePriceFact, ...] = ()
    value: TargetAbsorbValue | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", FeatureRuntimeStatus(self.status))
        object.__setattr__(
            self, "evidence_status", EvidenceStatus(self.evidence_status)
        )
        if self.status is not FeatureRuntimeStatus.READY:
            _text(self.reason_code)
        object.__setattr__(self, "formula_versions", tuple(self.formula_versions))
        object.__setattr__(self, "source_bars", tuple(self.source_bars))

    @property
    def actions(self) -> tuple[()]:
        return ()

    @property
    def hints(self) -> tuple[()]:
        return ()

    @property
    def reference_trades(self) -> tuple[()]:
        return ()


def _status(
    runtime: FeatureRuntimeStatus,
    evidence: EvidenceStatus,
    reason: str | None = None,
) -> FeatureStatus:
    return FeatureStatus(runtime, evidence, reason)


def _result(
    runtime: FeatureRuntimeStatus,
    evidence: EvidenceStatus,
    reason: str,
) -> TargetAbsorbResult:
    return TargetAbsorbResult(runtime, evidence, reason, _FORMULAS)


def _slot(context: ContextSnapshot, frequency: ProductFrequency) -> ContextSlot:
    return {
        ProductFrequency.WEEKLY: context.weekly,
        ProductFrequency.DAILY: context.daily,
        ProductFrequency.HOURLY: context.hourly,
    }[frequency]


def _fact_matches_slot(fact: PagePriceFact, slot: ContextSlot) -> bool:
    return (
        slot.status is FeatureRuntimeStatus.READY
        and slot.bar_end == fact.bar_end
        and slot.physical_contract == fact.physical_contract
        and slot.segment_id == fact.segment_id
        and slot.frequency is fact.frequency
    )


def _same_owner(fact: PagePriceFact, slot: ContextSlot) -> bool:
    return (
        slot.physical_contract == fact.physical_contract
        and slot.segment_id == fact.segment_id
    )


def _named_input_frequencies_are_valid(inputs: PageSelectionInputs) -> bool:
    expected = (
        (inputs.target_daily, ProductFrequency.DAILY),
        (inputs.cost_daily, ProductFrequency.DAILY),
        (inputs.target_weekly, ProductFrequency.WEEKLY),
        (inputs.cost_weekly, ProductFrequency.WEEKLY),
    )
    return all(
        fact is None or fact.frequency is frequency for fact, frequency in expected
    )


def _weekly_override(
    context: ContextSnapshot,
    evidence: VerifiedTargetAbsorbEvidence,
) -> PagePriceSelection | TargetAbsorbResult:
    bars = evidence.weekly_channel_bars
    if len(bars) < 10:
        return _result(
            FeatureRuntimeStatus.EVIDENCE_REQUIRED,
            EvidenceStatus.EVIDENCE_REQUIRED,
            "NEWOW_TARGET_ABSORB_WEEKLY_WARMUP_EVIDENCE_REQUIRED",
        )
    slot = context.weekly
    if slot.status is not FeatureRuntimeStatus.READY:
        return _result(
            FeatureRuntimeStatus.UNAVAILABLE,
            EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
            "NEWOW_TARGET_ABSORB_VIEW_CONTEXT_UNAVAILABLE",
        )
    if slot.identity is None or slot.bar_end is None:
        return _result(
            FeatureRuntimeStatus.UNAVAILABLE,
            EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
            "NEWOW_TARGET_ABSORB_VIEW_CONTEXT_UNAVAILABLE",
        )
    if (
        any(
            bar.frequency is not ProductFrequency.WEEKLY
            or bar.bar.product != slot.identity.product
            or bar.bar.series_kind != slot.identity.series_kind
            or bar.bar.physical_contract != slot.physical_contract
            or bar.bar.segment_id != slot.segment_id
            or bar.bar.bar_end > slot.bar_end
            for bar in bars
        )
        or bars[-1].bar.bar_end != slot.bar_end
    ):
        return _result(
            FeatureRuntimeStatus.UNAVAILABLE,
            EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
            "NEWOW_TARGET_ABSORB_SOURCE_CONTEXT_MISMATCH",
        )
    channel = calculate_channel_series(tuple(bar.bar for bar in bars), period=10)[-1]
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


def _subfeatures(period: PageSelectionPeriod) -> tuple[TargetAbsorbSubfeature, ...]:
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
        TargetAbsorbSubfeature("weekly_status_card_override", research_ready, True)
        if period is PageSelectionPeriod.WEEK
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
            value=None,
        )
    if not isinstance(evidence, VerifiedTargetAbsorbEvidence):
        raise ValueError("NEWOW_TARGET_ABSORB_INVALID_EVIDENCE")
    if not _named_input_frequencies_are_valid(evidence.inputs):
        return _result(
            FeatureRuntimeStatus.UNAVAILABLE,
            EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
            "NEWOW_TARGET_ABSORB_SOURCE_FREQUENCY_MISMATCH",
        )

    view_slot = _slot(context, evidence.view_frequency)
    if view_slot.status is not FeatureRuntimeStatus.READY:
        return _result(
            FeatureRuntimeStatus.UNAVAILABLE,
            EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
            "NEWOW_TARGET_ABSORB_VIEW_CONTEXT_UNAVAILABLE",
        )
    selected: PagePriceSelection | TargetAbsorbResult
    if evidence.period is PageSelectionPeriod.WEEK:
        selected = _weekly_override(context, evidence)
    else:
        selected = select_page_prices(evidence.inputs, evidence.period)
    if isinstance(selected, TargetAbsorbResult):
        return selected
    if selected.target is None or selected.absorb is None:
        return _result(
            FeatureRuntimeStatus.UNAVAILABLE,
            EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
            "NEWOW_TARGET_ABSORB_PRICE_UNAVAILABLE",
        )

    facts = (selected.target.fact, selected.absorb.fact)
    if any(
        not _fact_matches_slot(fact, _slot(context, fact.frequency))
        or not _same_owner(fact, view_slot)
        for fact in facts
    ):
        return _result(
            FeatureRuntimeStatus.UNAVAILABLE,
            EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
            "NEWOW_TARGET_ABSORB_SOURCE_CONTEXT_MISMATCH",
        )
    source_bars = tuple(dict.fromkeys(facts))
    value = TargetAbsorbValue(
        target=_display(selected.target),
        absorb=_display(selected.absorb),
        previous_close=None,
        subfeatures=_subfeatures(evidence.period),
    )
    return TargetAbsorbResult(
        status=FeatureRuntimeStatus.READY,
        evidence_status=EvidenceStatus.RESEARCH_EVIDENCE_ONLY,
        reason_code=None,
        formula_versions=_FORMULAS,
        source_bars=source_bars,
        value=value,
    )
