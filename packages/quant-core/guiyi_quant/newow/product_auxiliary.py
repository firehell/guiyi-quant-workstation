"""Bounded product wrappers for existing Newow auxiliary primitives."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Generic, TypeVar

from .cup_handle import (
    CupReadyWitness,
    calculate_cup_handle_series,
    cup_evaluation_ready,
)
from .models import NewowDailyBar
from .product_contracts import (
    EvidenceStatus,
    FeatureRuntimeStatus,
    FeatureStatus,
    ProductBar,
    ProductFrequency,
    ProductIdentity,
    ProductStrategy,
)
from .product_identity import utc_timestamp
from .profile import NEWOW_TREND_D1_V1
from .subplots import (
    MAIN_FORCE_CONTROL_FORMULA_VERSION,
    UP_DOWN_ENERGY_FORMULA_VERSION,
    ZHAOYAO_MIRROR_FORMULA_VERSION,
    MainForceControlResult,
    UpDownEnergyResult,
    ZhaoyaoMirrorResult,
    calculate_main_force_control,
    calculate_up_down_energy,
    calculate_zhaoyao_mirror,
)


_ACTIVE = EvidenceStatus.ACTIVE_CODE_VERIFIED
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class AuxiliarySegment(Generic[_T]):
    """One calculation bounded to an exact physical owner segment."""

    physical_contract: str
    segment_id: str
    bar_ends: tuple[datetime, ...]
    status: FeatureStatus
    value: _T | None

    def __post_init__(self) -> None:
        if (
            not self.physical_contract
            or not self.segment_id
            or not isinstance(self.status, FeatureStatus)
        ):
            raise ValueError("NEWOW_AUXILIARY_INVALID_SEGMENT")
        ends = tuple(utc_timestamp(value) for value in self.bar_ends)
        if any(left >= right for left, right in zip(ends, ends[1:], strict=False)):
            raise ValueError("NEWOW_AUXILIARY_INVALID_SEGMENT")
        object.__setattr__(self, "bar_ends", ends)


@dataclass(frozen=True, slots=True)
class AuxiliaryLayer(Generic[_T]):
    """Typed feature layer with aggregate and per-segment availability."""

    name: str
    formula_version: str
    availability: FeatureStatus
    segments: tuple[AuxiliarySegment[_T], ...]
    repainting: bool
    formal_signal_eligible: bool
    page_parity: bool

    def __post_init__(self) -> None:
        if (
            not self.name
            or not self.formula_version
            or not isinstance(self.availability, FeatureStatus)
            or type(self.repainting) is not bool
            or type(self.formal_signal_eligible) is not bool
            or type(self.page_parity) is not bool
        ):
            raise ValueError("NEWOW_AUXILIARY_INVALID_LAYER")
        segments = tuple(self.segments)
        if not all(isinstance(segment, AuxiliarySegment) for segment in segments):
            raise ValueError("NEWOW_AUXILIARY_INVALID_LAYER")
        object.__setattr__(self, "segments", segments)

    @property
    def status(self) -> FeatureRuntimeStatus:
        return self.availability.status

    @property
    def evidence_status(self) -> EvidenceStatus:
        return self.availability.evidence_status


@dataclass(frozen=True, slots=True)
class AuxiliaryResult:
    """Auxiliary display facts; this type deliberately owns no strategy events."""

    identity: ProductIdentity
    as_of: datetime
    main_force_control: AuxiliaryLayer[MainForceControlResult]
    up_down_energy: AuxiliaryLayer[UpDownEnergyResult]
    retrospective_layers: tuple[AuxiliaryLayer[ZhaoyaoMirrorResult], ...]
    cup_handle: AuxiliaryLayer[tuple[CupReadyWitness, ...]]

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ProductIdentity):
            raise ValueError("NEWOW_AUXILIARY_INVALID_IDENTITY")
        object.__setattr__(self, "as_of", utc_timestamp(self.as_of))
        retrospective_layers = tuple(self.retrospective_layers)
        if (
            len(retrospective_layers) != 1
            or not isinstance(retrospective_layers[0], AuxiliaryLayer)
            or retrospective_layers[0].name != "zhaoyao_mirror"
            or retrospective_layers[0].repainting is not True
            or retrospective_layers[0].formal_signal_eligible is not False
        ):
            raise ValueError("NEWOW_AUXILIARY_MIRROR_AUTHORITY")
        object.__setattr__(self, "retrospective_layers", retrospective_layers)

    @property
    def actions(self) -> tuple[()]:
        return ()

    @property
    def hints(self) -> tuple[()]:
        return ()


@dataclass(frozen=True, slots=True)
class _OwnerSegment:
    physical_contract: str
    segment_id: str
    bars: tuple[NewowDailyBar, ...]


def _status(
    runtime: FeatureRuntimeStatus, reason_code: str | None = None
) -> FeatureStatus:
    return FeatureStatus(runtime, _ACTIVE, reason_code)


def _validated_segments(
    identity: ProductIdentity,
    bars: tuple[ProductBar, ...],
    as_of: datetime,
) -> tuple[_OwnerSegment, ...]:
    if not isinstance(identity, ProductIdentity):
        raise ValueError("NEWOW_AUXILIARY_INVALID_IDENTITY")

    seen_segments: set[str] = set()
    current_segment: str | None = None
    current_contract: str | None = None
    previous: NewowDailyBar | None = None
    grouped: list[tuple[str, str, list[NewowDailyBar]]] = []
    for product_bar in bars:
        if (
            not isinstance(product_bar, ProductBar)
            or product_bar.bar.product != identity.product
            or product_bar.frequency != identity.frequency
            or product_bar.series_kind != identity.series_kind
        ):
            raise ValueError("NEWOW_AUXILIARY_INPUT_IDENTITY_INVALID")
        bar = product_bar.bar
        if bar.segment_id != current_segment:
            if bar.segment_id in seen_segments:
                raise ValueError("NEWOW_AUXILIARY_INPUT_ORDER")
            if current_segment is not None:
                seen_segments.add(current_segment)
            current_segment = bar.segment_id
            current_contract = bar.physical_contract
            previous = None
            grouped.append((bar.physical_contract, bar.segment_id, []))
        elif bar.physical_contract != current_contract:
            raise ValueError("NEWOW_AUXILIARY_INPUT_IDENTITY_INVALID")
        if previous is not None and (
            bar.bar_end <= previous.bar_end or bar.trading_day < previous.trading_day
        ):
            raise ValueError("NEWOW_AUXILIARY_INPUT_ORDER")
        previous = bar
        if bar.bar_end <= as_of:
            grouped[-1][2].append(bar)

    return tuple(
        _OwnerSegment(contract, segment_id, tuple(segment_bars))
        for contract, segment_id, segment_bars in grouped
        if segment_bars
    )


def _layer_availability(
    segments: tuple[AuxiliarySegment[_T], ...], warming_code: str
) -> FeatureStatus:
    if segments and all(
        segment.status.status is FeatureRuntimeStatus.READY for segment in segments
    ):
        return _status(FeatureRuntimeStatus.READY)
    return _status(FeatureRuntimeStatus.WARMING, warming_code)


def _subplot_layer(
    *,
    name: str,
    formula_version: str,
    owners: tuple[_OwnerSegment, ...],
    calculator: Callable[[tuple[NewowDailyBar, ...]], _T | None],
    warming_code: str,
    repainting: bool,
) -> AuxiliaryLayer[_T]:
    values: list[AuxiliarySegment[_T]] = []
    for owner in owners:
        result = calculator(owner.bars)
        status = (
            _status(FeatureRuntimeStatus.READY)
            if result is not None
            else _status(FeatureRuntimeStatus.WARMING, warming_code)
        )
        values.append(
            AuxiliarySegment(
                owner.physical_contract,
                owner.segment_id,
                tuple(bar.bar_end for bar in owner.bars),
                status,
                result,
            )
        )
    segments = tuple(values)
    return AuxiliaryLayer(
        name=name,
        formula_version=formula_version,
        availability=_layer_availability(segments, warming_code),
        segments=segments,
        repainting=repainting,
        formal_signal_eligible=False,
        page_parity=True,
    )


def _cup_layer(
    identity: ProductIdentity, owners: tuple[_OwnerSegment, ...]
) -> AuxiliaryLayer[tuple[CupReadyWitness, ...]]:
    formula = NEWOW_TREND_D1_V1.cup_handle_formula
    applicable = (
        identity.strategy is ProductStrategy.TREND
        and identity.frequency is ProductFrequency.DAILY
    )
    if not applicable:
        unavailable = _status(
            FeatureRuntimeStatus.NOT_APPLICABLE,
            "NEWOW_CUP_HANDLE_NOT_APPLICABLE",
        )
        return AuxiliaryLayer(
            name="cup_handle",
            formula_version=formula,
            availability=unavailable,
            segments=tuple(
                AuxiliarySegment(
                    owner.physical_contract,
                    owner.segment_id,
                    tuple(bar.bar_end for bar in owner.bars),
                    unavailable,
                    None,
                )
                for owner in owners
            ),
            repainting=False,
            formal_signal_eligible=False,
            page_parity=False,
        )

    segment_results: list[AuxiliarySegment[tuple[CupReadyWitness, ...]]] = []
    for owner in owners:
        steps = calculate_cup_handle_series(owner.bars, profile=NEWOW_TREND_D1_V1)
        witnesses: dict[str, CupReadyWitness] = {}
        for step in steps:
            witness = step.state.ready_witness
            if witness is not None:
                witnesses[witness.witness_id] = witness
        ready = bool(steps) and cup_evaluation_ready(
            steps[-1].state, profile=NEWOW_TREND_D1_V1
        )
        status = (
            _status(FeatureRuntimeStatus.READY)
            if ready
            else _status(
                FeatureRuntimeStatus.WARMING,
                "NEWOW_CUP_HANDLE_WARMING",
            )
        )
        segment_results.append(
            AuxiliarySegment(
                owner.physical_contract,
                owner.segment_id,
                tuple(bar.bar_end for bar in owner.bars),
                status,
                tuple(witnesses.values()),
            )
        )
    segments = tuple(segment_results)
    return AuxiliaryLayer(
        name="cup_handle",
        formula_version=formula,
        availability=_layer_availability(segments, "NEWOW_CUP_HANDLE_WARMING"),
        segments=segments,
        repainting=False,
        formal_signal_eligible=False,
        page_parity=False,
    )


def calculate_product_auxiliary(
    identity: ProductIdentity,
    bars: tuple[ProductBar, ...],
    *,
    as_of: datetime | None = None,
) -> AuxiliaryResult:
    """Calculate bounded auxiliary layers without changing strategy authority."""

    try:
        inputs = tuple(bars)
    except TypeError as error:
        raise ValueError("NEWOW_AUXILIARY_INVALID_INPUT") from error
    if not isinstance(identity, ProductIdentity) or not all(
        isinstance(item, ProductBar) for item in inputs
    ):
        raise ValueError("NEWOW_AUXILIARY_INVALID_INPUT")
    cutoff = (
        utc_timestamp(as_of)
        if as_of is not None
        else max(
            (item.bar.bar_end for item in inputs),
            default=datetime.min.replace(tzinfo=UTC),
        )
    )
    owners = _validated_segments(identity, inputs, cutoff)
    control = _subplot_layer(
        name="main_force_control",
        formula_version=MAIN_FORCE_CONTROL_FORMULA_VERSION,
        owners=owners,
        calculator=calculate_main_force_control,
        warming_code="NEWOW_MAIN_FORCE_CONTROL_WARMING",
        repainting=False,
    )
    energy = _subplot_layer(
        name="up_down_energy",
        formula_version=UP_DOWN_ENERGY_FORMULA_VERSION,
        owners=owners,
        calculator=calculate_up_down_energy,
        warming_code="NEWOW_UP_DOWN_ENERGY_WARMING",
        repainting=False,
    )
    mirror = _subplot_layer(
        name="zhaoyao_mirror",
        formula_version=ZHAOYAO_MIRROR_FORMULA_VERSION,
        owners=owners,
        calculator=calculate_zhaoyao_mirror,
        warming_code="NEWOW_ZHAOYAO_MIRROR_WARMING",
        repainting=True,
    )
    return AuxiliaryResult(
        identity=identity,
        as_of=cutoff,
        main_force_control=control,
        up_down_energy=energy,
        retrospective_layers=(mirror,),
        cup_handle=_cup_layer(identity, owners),
    )
