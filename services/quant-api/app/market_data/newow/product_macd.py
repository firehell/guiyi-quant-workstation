"""Read-only MACD display projection over the existing physical replay prefix."""

from dataclasses import dataclass

from guiyi_quant.indicators.macd import MACD_VERSION, macd_series
from guiyi_quant.indicators.models import IndicatorPoint
from guiyi_quant.newow.product_auxiliary import (
    AuxiliaryLayer,
    AuxiliarySegment,
    _layer_availability,
    _status,
    _validated_segments,
)
from guiyi_quant.newow.product_contracts import FeatureRuntimeStatus, ProductIdentity

from .product_reader import ProductReadSet

DISPLAY_ADAPTER_VERSION = "guiyi_newow_macd_display_v1"
_PROFILE = macd_series(
    (), 12, 26, 9, ema_seed_policy="sma_window", histogram_scale=2, round_digits=6
)
MACD_CACHE_IDENTITY = (MACD_VERSION, DISPLAY_ADAPTER_VERSION, _PROFILE.parameters_hash)


@dataclass(frozen=True, slots=True)
class MacdDisplayData:
    dif: tuple[IndicatorPoint, ...]
    dea: tuple[IndicatorPoint, ...]
    histogram: tuple[IndicatorPoint, ...]


@dataclass(frozen=True, slots=True)
class MacdDisplayLayer(AuxiliaryLayer[MacdDisplayData]):
    display_adapter_version: str
    parameters: dict[str, int | str]
    parameters_hash: str


def calculate_macd_display(
    identity: ProductIdentity, read: ProductReadSet
) -> MacdDisplayLayer:
    # Share the auxiliary identity/order/owner seam; never seed from a viewport.
    owners = _validated_segments(identity, read.replay_bars, read.as_of)
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
        calculated = macd_series(
            [float(bar.close) for bar in owner.bars],
            12,
            26,
            9,
            ema_seed_policy="sma_window",
            histogram_scale=2,
            round_digits=6,
            bar_ends=[bar.bar_end.isoformat() for bar in owner.bars],
        )
        data = MacdDisplayData(
            tuple(calculated.dif.points[index] for index in visible),
            tuple(calculated.dea.points[index] for index in visible),
            tuple(calculated.histogram.points[index] for index in visible),
        )
        ready = all(
            points[-1].ready and points[-1].valid
            for points in (data.dif, data.dea, data.histogram)
        )
        status = (
            _status(FeatureRuntimeStatus.READY)
            if ready
            else _status(FeatureRuntimeStatus.WARMING, "NEWOW_MACD_WARMING")
        )
        segments.append(
            AuxiliarySegment(
                owner.physical_contract,
                owner.segment_id,
                tuple(owner.bars[index].bar_end for index in visible),
                status,
                data,
            )
        )
    values = tuple(segments)
    return MacdDisplayLayer(
        name="macd",
        formula_version=MACD_VERSION,
        availability=_layer_availability(values, "NEWOW_MACD_WARMING"),
        segments=values,
        repainting=False,
        formal_signal_eligible=False,
        page_parity=False,
        display_adapter_version=DISPLAY_ADAPTER_VERSION,
        parameters=dict(_PROFILE.parameters),
        parameters_hash=_PROFILE.parameters_hash,
    )
