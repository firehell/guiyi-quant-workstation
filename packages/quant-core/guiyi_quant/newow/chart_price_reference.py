"""Versioned projection of a chart channel point; it never recomputes HHV/LLV."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .product_contracts import EvidenceStatus, FeatureRuntimeStatus, FeatureStatus, ProductBar, ProductFrequency
from .product_identity import utc_timestamp
from .trend_channel_display import TrendChannelLayer, TrendChannelPoint


CHART_PRICE_REFERENCE_FORMULA_VERSION = "newow_chart_legend_hhv_llv10_page_v1"
CHART_PRICE_REFERENCE_ADAPTER_VERSION = "newow_chart_price_projection_v1"


def _text(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("NEWOW_CHART_PRICE_INVALID_IDENTITY")


def _status(status: FeatureRuntimeStatus, reason: str | None = None) -> FeatureStatus:
    return FeatureStatus(status, EvidenceStatus.ACTIVE_CODE_VERIFIED, reason)


@dataclass(frozen=True, slots=True)
class ChartPriceValue:
    raw: Decimal | None
    display: str | None
    status: FeatureStatus

    def __post_init__(self) -> None:
        ready = self.status.status is FeatureRuntimeStatus.READY
        if ready != (isinstance(self.raw, Decimal) and self.raw.is_finite() and self.raw > 0 and isinstance(self.display, str) and bool(self.display)):
            raise ValueError("NEWOW_CHART_PRICE_VALUE_STATUS_CONFLICT")


@dataclass(frozen=True, slots=True)
class ChartPriceReference:
    surface: str
    frequency: ProductFrequency
    as_of: datetime
    anchor_bar_end: datetime
    physical_contract: str
    segment_id: str
    calculation_segment_id: str
    input_sha256: str
    formula_version: str
    adapter_version: str
    target: ChartPriceValue
    absorb: ChartPriceValue

    def __post_init__(self) -> None:
        if self.surface != "chart_legend":
            raise ValueError("NEWOW_CHART_PRICE_INVALID_SURFACE")
        object.__setattr__(self, "frequency", ProductFrequency(self.frequency))
        object.__setattr__(self, "as_of", utc_timestamp(self.as_of))
        object.__setattr__(self, "anchor_bar_end", utc_timestamp(self.anchor_bar_end))
        for value in (self.physical_contract, self.segment_id, self.calculation_segment_id, self.formula_version, self.adapter_version):
            _text(value)
        if self.physical_contract != self.physical_contract.upper() or self.as_of < self.anchor_bar_end:
            raise ValueError("NEWOW_CHART_PRICE_INVALID_IDENTITY")
        if len(self.input_sha256) != 64 or any(char not in "0123456789abcdef" for char in self.input_sha256):
            raise ValueError("NEWOW_CHART_PRICE_INVALID_INPUT_HASH")


def _display(value: Decimal) -> str:
    """The current public chart legend uses a two-decimal display boundary."""
    return f"{value:.2f}"


def _unavailable(anchor: ProductBar, as_of: datetime, input_sha256: str, reason: str) -> ChartPriceReference:
    value = ChartPriceValue(None, None, _status(FeatureRuntimeStatus.UNAVAILABLE, reason))
    return ChartPriceReference(
        "chart_legend", anchor.frequency, as_of, anchor.bar.bar_end,
        anchor.bar.physical_contract, anchor.bar.segment_id, anchor.calculation_segment_id,
        input_sha256, CHART_PRICE_REFERENCE_FORMULA_VERSION,
        CHART_PRICE_REFERENCE_ADAPTER_VERSION, value, value,
    )


def project_chart_price_reference(
    layer: TrendChannelLayer,
    anchor: ProductBar,
    *,
    as_of: datetime,
    input_sha256: str,
) -> ChartPriceReference:
    """Return only an exact, ready anchor point from the supplied full-prefix layer."""
    if not isinstance(layer, TrendChannelLayer) or not isinstance(anchor, ProductBar):
        raise ValueError("NEWOW_CHART_PRICE_INVALID_INPUT")
    normalized_as_of = utc_timestamp(as_of)
    if normalized_as_of < anchor.bar.bar_end:
        return _unavailable(anchor, normalized_as_of, input_sha256, "NEWOW_CHART_PRICE_ANCHOR_AFTER_AS_OF")
    matches = tuple(
        point for point in layer.points
        if point.bar_end == anchor.bar.bar_end
        and point.physical_contract == anchor.bar.physical_contract
        and point.segment_id == anchor.bar.segment_id
        and point.source_identity == anchor.bar.source_identity
        and point.calculation_segment_id == anchor.calculation_segment_id
    )
    if len(matches) != 1:
        return _unavailable(anchor, normalized_as_of, input_sha256, "NEWOW_CHART_PRICE_ANCHOR_MISSING")
    point: TrendChannelPoint = matches[0]
    if point.availability.status is not FeatureRuntimeStatus.READY:
        return _unavailable(anchor, normalized_as_of, input_sha256, point.availability.reason_code or "NEWOW_CHART_PRICE_UNAVAILABLE")
    target = ChartPriceValue(point.upper, _display(point.upper), _status(FeatureRuntimeStatus.READY))
    absorb = ChartPriceValue(point.lower, _display(point.lower), _status(FeatureRuntimeStatus.READY))
    return ChartPriceReference(
        "chart_legend", anchor.frequency, normalized_as_of, anchor.bar.bar_end,
        anchor.bar.physical_contract, anchor.bar.segment_id, anchor.calculation_segment_id,
        input_sha256, CHART_PRICE_REFERENCE_FORMULA_VERSION,
        CHART_PRICE_REFERENCE_ADAPTER_VERSION, target, absorb,
    )
