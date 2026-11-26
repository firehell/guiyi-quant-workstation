"""Read-only MACD display projection over the completed physical replay prefix."""

from dataclasses import dataclass
from datetime import datetime

from guiyi_quant.compute import (
    REGISTRY,
    BarSeries,
    CompletedBar,
    FeaturePoint,
    FeatureRequest,
    SeriesIdentity,
    Status,
)
from guiyi_quant.compute.contracts import ParameterValue, hash_parameters
from guiyi_quant.newow.product_adapters import label_calculation_segments
from guiyi_quant.newow.product_auxiliary import (
    AuxiliaryLayer,
    AuxiliarySegment,
    _layer_availability,
    _status,
    _validated_segments,
)
from guiyi_quant.newow.product_contracts import FeatureRuntimeStatus, ProductIdentity

from .product_reader import ProductReadSet

DISPLAY_ADAPTER_VERSION = "guiyi_newow_macd_display_v2"
_REQUEST = FeatureRequest("macd", {"fast": 12, "slow": 26, "signal": 9})
_DEFINITION = REGISTRY.definition(_REQUEST.feature_id)
_PARAMETERS = _DEFINITION.resolve(_REQUEST)
_PARAMETERS_HASH = hash_parameters(_PARAMETERS)
MACD_CACHE_IDENTITY = (
    _DEFINITION.formula_version,
    DISPLAY_ADAPTER_VERSION,
    _PARAMETERS_HASH,
    _DEFINITION.backend_version,
)
_WARMING_CODE = "NEWOW_MACD_WARMING"
_UNAVAILABLE_CODE = "NEWOW_MACD_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class MacdDisplayPoint:
    bar_end: datetime
    value: float | None
    ready: bool
    valid: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class MacdDisplayData:
    dif: tuple[MacdDisplayPoint, ...]
    dea: tuple[MacdDisplayPoint, ...]
    histogram: tuple[MacdDisplayPoint, ...]


@dataclass(frozen=True, slots=True)
class MacdDisplayLayer(AuxiliaryLayer[MacdDisplayData]):
    display_adapter_version: str
    parameters: dict[str, ParameterValue]
    parameters_hash: str


def _point(point: FeaturePoint, output: str) -> MacdDisplayPoint:
    if point.status is Status.READY:
        assert point.values is not None
        return MacdDisplayPoint(point.bar_end, float(point.values[output]), True, True, None)
    if point.status is Status.WARMING:
        return MacdDisplayPoint(point.bar_end, None, False, True, "warming_up")
    return MacdDisplayPoint(point.bar_end, None, False, False, point.diagnostic or _UNAVAILABLE_CODE)


def calculate_macd_display(
    identity: ProductIdentity, read: ProductReadSet, *, source_revision: str
) -> MacdDisplayLayer:
    owners = _validated_segments(
        identity,
        label_calculation_segments(identity, read.replay_bars, read.data_interruptions),
        read.as_of,
    )
    segments: list[AuxiliarySegment[MacdDisplayData]] = []
    for owner in owners:
        visible = tuple(
            index
            for index, bar in enumerate(owner.bars)
            if bar.observation_eligible
            and read.display_window.since
            <= bar.trading_day
            <= read.display_window.through
        )
        if not visible:
            continue
        series = BarSeries(
            SeriesIdentity(
                identity.product, owner.physical_contract, owner.segment_id,
                identity.frequency.value, source_revision,
            ),
            tuple(
                # Completed historical replay uses event time at the certified Bar end.
                # The reader supplies a trading day, with no exchange subsession or capture timestamp.
                CompletedBar(
                    owner.physical_contract, owner.segment_id, bar.trading_day,
                    f"historical:{bar.trading_day.isoformat()}",
                    bar.bar_end, bar.bar_end, bar.bar_end,
                    None, None, None, float(bar.close), None, "VALID",
                )
                for bar in owner.bars
            ),
        )
        (calculated,) = REGISTRY.calculate(series, (_REQUEST,), as_of=read.as_of, use="web")
        points = tuple(calculated.points[index] for index in visible)
        data = MacdDisplayData(
            tuple(_point(point, "dif") for point in points),
            tuple(_point(point, "dea") for point in points),
            tuple(_point(point, "histogram") for point in points),
        )
        match points[-1].status:
            case Status.READY:
                status = _status(FeatureRuntimeStatus.READY)
            case Status.WARMING:
                status = _status(FeatureRuntimeStatus.WARMING, _WARMING_CODE)
            case _:
                status = _status(FeatureRuntimeStatus.UNAVAILABLE, _UNAVAILABLE_CODE)
        segments.append(
            AuxiliarySegment(
                owner.physical_contract,
                owner.segment_id,
                tuple(point.bar_end for point in points),
                status,
                data,
            )
        )
    values = tuple(segments)
    availability = (
        _status(FeatureRuntimeStatus.UNAVAILABLE, _UNAVAILABLE_CODE)
        if any(segment.status.status is FeatureRuntimeStatus.UNAVAILABLE for segment in values)
        else _layer_availability(values, _WARMING_CODE)
    )
    return MacdDisplayLayer(
        name="macd",
        formula_version=_DEFINITION.formula_version,
        availability=availability,
        segments=values,
        repainting=False,
        formal_signal_eligible=False,
        page_parity=False,
        display_adapter_version=DISPLAY_ADAPTER_VERSION,
        parameters=dict(_PARAMETERS),
        parameters_hash=_PARAMETERS_HASH,
    )
