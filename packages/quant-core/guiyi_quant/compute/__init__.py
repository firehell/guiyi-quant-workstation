"""Public, framework-free Quant Core calculation API."""

from datetime import datetime

from . import incremental as _incremental
from .contracts import (
    RESULT_SCHEMA_VERSION as RESULT_SCHEMA_VERSION,
    STATE_SCHEMA_VERSION as STATE_SCHEMA_VERSION,
    BarSeries as BarSeries,
    CompletedBar as CompletedBar,
    FeatureIdentity as FeatureIdentity,
    FeatureMarker as FeatureMarker,
    FeaturePoint as FeaturePoint,
    FeatureResult as FeatureResult,
    SeriesIdentity as SeriesIdentity,
    Status as Status,
)
from .generic import GENERIC_DEFINITIONS
from .price_action import PRICE_ACTION_DEFINITIONS
from .trend import TREND_DEFINITION
from .registry import (
    ComputeRegistry as ComputeRegistry,
    FeatureRequest as FeatureRequest,
    IndicatorDefinition as IndicatorDefinition,
)

REGISTRY = ComputeRegistry((*GENERIC_DEFINITIONS, TREND_DEFINITION, *PRICE_ACTION_DEFINITIONS))

IncrementalState = _incremental.IncrementalState
rebind_incremental = _incremental.rebind_incremental


def open_incremental(
    series: BarSeries, request: FeatureRequest, *, as_of: datetime, mode: str, use: str,
) -> IncrementalState:
    return _incremental.open_incremental(REGISTRY, series, request, as_of=as_of, mode=mode, use=use)


def advance(
    state: IncrementalState, identity: SeriesIdentity, bar: CompletedBar,
) -> tuple[IncrementalState, FeaturePoint]:
    return _incremental.advance(REGISTRY, state, identity, bar)
