"""Pure step over owned process-local state. Persist identity, then rebuild from verified Bars."""

from dataclasses import dataclass, field, replace
from datetime import datetime

import numpy as np

from .contracts import (
    EMPTY_PREFIX_DIGEST,
    STATE_SCHEMA_VERSION,
    BarSeries,
    CompletedBar,
    FeaturePoint,
    SeriesIdentity,
    Status,
    extend_prefix_digest,
)
from .generic import _point, _volume_ratio, open_stream, require_talib_defaults
from .registry import ComputeRegistry, FeatureRequest, IndicatorDefinition, input_problem


@dataclass(frozen=True, slots=True)
class IncrementalState:
    identity: SeriesIdentity
    request: FeatureRequest
    formula_version: str
    backend_version: str
    mode: str
    use: str
    bar_count: int = 0
    last_bar: CompletedBar | None = None
    last_point: FeaturePoint | None = None
    prefix_digest: str = EMPTY_PREFIX_DIGEST
    state_schema_version: str = STATE_SCHEMA_VERSION
    _last_bar_digest: str | None = field(default=None, repr=False)
    _warm_rows: tuple[tuple[float, ...], ...] = field(default=(), repr=False)
    _stream: object | None = field(default=None, repr=False, compare=False)
    _interrupted: bool = field(default=False, repr=False)


def _definition(registry, identity, request, mode, use) -> IndicatorDefinition:
    definition = registry.definition(request.feature_id)
    if (
        definition.category != "generic" or mode not in ("incremental", "live")
        or mode not in definition.modes or use not in definition.allowed_uses
        or (mode == "live" and use != "simulation")
        or identity.frequency not in definition.supported_frequencies
    ):
        raise ValueError(f"FEATURE_USE_NOT_ALLOWED: {definition.feature_id}")
    return definition


def open_incremental(
    registry: ComputeRegistry, series: BarSeries, request: FeatureRequest, *, as_of: datetime,
    mode: str, use: str,
) -> IncrementalState:
    definition = _definition(registry, series.identity, request, mode, use)
    params = definition.resolve(request)
    state = IncrementalState(
        series.identity, FeatureRequest(request.feature_id, params),
        definition.formula_version, definition.backend_version, mode, use,
    )
    count = series.available_count(as_of)
    if not count:
        return state

    # Seed the stream once from the whole verified prefix. Keep only the exact
    # warm-up rows or the Volume Ratio lookback when the indicator needs them.
    invalid_at = None
    columns = tuple(np.empty(count, dtype=np.float64) for _ in definition.input_fields)
    for index, bar in enumerate(series.bars[:count]):
        if invalid_at is not None:
            continue
        values = tuple(getattr(bar, name) for name in definition.input_fields)
        if input_problem(bar, definition.input_fields):
            invalid_at = index
            continue
        for column, value in zip(columns, values, strict=True):
            column[index] = value
    last = series.bars[count - 1]
    at = series.point_availability(count)[-1]
    warm_rows = ()
    handle = None
    if invalid_at is not None:
        problem = input_problem(last, definition.input_fields)
        status, reason = problem or (Status.UNKNOWN, "INPUT_PREFIX_INTERRUPTED")
        point = FeaturePoint(last.bar_end, at, status, diagnostic=reason)
    elif count <= definition.lookback(params):
        warm_rows = tuple(zip(*columns, strict=True))
        point = FeaturePoint(last.bar_end, at, Status.WARMING, diagnostic="LOOKBACK_REQUIRED")
    elif definition.feature_id == "volume_ratio":
        period = int(params["period"])
        recent_volume = columns[0][-(period + 1):]
        warm_rows = tuple((value,) for value in recent_volume[1:])
        output = float(_volume_ratio((recent_volume,), params)[0][-1])
        point = _point(last, at, output, definition.outputs, volume_ratio=True)
    else:
        handle = open_stream(definition.feature_id, params, columns)
        point = _point(last, at, handle.value, definition.outputs)
    return replace(
        state, bar_count=count, last_bar=last, last_point=point, prefix_digest=series.prefix_digest(count),
        _last_bar_digest=extend_prefix_digest(EMPTY_PREFIX_DIGEST, last),
        _warm_rows=warm_rows, _stream=handle, _interrupted=invalid_at is not None,
    )


def advance(
    registry: ComputeRegistry, state: IncrementalState, identity: SeriesIdentity, bar: CompletedBar,
) -> tuple[IncrementalState, FeaturePoint]:
    if state.state_schema_version != STATE_SCHEMA_VERSION:
        raise ValueError("STATE_SCHEMA_INCOMPATIBLE")
    definition = _definition(registry, identity, state.request, state.mode, state.use)
    if (definition.formula_version, definition.backend_version) != (state.formula_version, state.backend_version):
        raise ValueError("STATE_FORMULA_INCOMPATIBLE")
    if identity != state.identity or (bar.physical_contract, bar.segment_id) != (
        identity.physical_contract, identity.segment_id
    ):
        raise ValueError("STATE_SOURCE_CHANGED")
    bar_digest = extend_prefix_digest(EMPTY_PREFIX_DIGEST, bar)
    if state.last_bar is not None and bar.bar_end <= state.last_bar.bar_end:
        if state._last_bar_digest == bar_digest:
            return state, state.last_point
        raise ValueError("STATE_INPUT_OUT_OF_ORDER_OR_REVISED")
    at = max(bar.available_at, state.last_point.available_at) if state.last_point else bar.available_at
    params = state.request.parameters
    values = tuple(getattr(bar, name) for name in definition.input_fields)
    problem = input_problem(bar, definition.input_fields)
    interrupted = state._interrupted or problem is not None
    count = state.bar_count + 1
    handle = None
    warm_rows = ()
    if interrupted:
        status, reason = problem or (Status.UNKNOWN, "INPUT_PREFIX_INTERRUPTED")
        point = FeaturePoint(bar.bar_end, at, status, diagnostic=reason)
    elif count <= definition.lookback(params):
        warm_rows = (*state._warm_rows, values)
        point = FeaturePoint(bar.bar_end, at, Status.WARMING, diagnostic="LOOKBACK_REQUIRED")
    elif definition.feature_id == "volume_ratio":
        rows = (*state._warm_rows, values)
        volumes = np.fromiter((row[0] for row in rows), dtype=np.float64, count=len(rows))
        warm_rows = rows[1:]
        output = float(_volume_ratio((volumes,), params)[0][-1])
        point = _point(bar, at, output, definition.outputs, volume_ratio=True)
    else:
        if state._stream is None:
            rows = (*state._warm_rows, values)
            columns = tuple(np.asarray(col, dtype=np.float64) for col in zip(*rows, strict=True))
            handle = open_stream(definition.feature_id, params, columns)
            output = handle.value
        else:
            require_talib_defaults()
            handle = state._stream.copy()
            output = handle.update(*values)
        point = _point(bar, at, output, definition.outputs)
    return replace(
        state, bar_count=count, last_bar=bar, last_point=point,
        prefix_digest=extend_prefix_digest(state.prefix_digest, bar), _last_bar_digest=bar_digest,
        _warm_rows=warm_rows, _stream=handle, _interrupted=interrupted,
    ), point


def rebind_incremental(
    state: IncrementalState, verified_prefix: BarSeries, *, prefix_count: int | None = None,
) -> IncrementalState:
    source = verified_prefix.identity
    if replace(source, source_revision=state.identity.source_revision) != state.identity:
        raise ValueError("STATE_SOURCE_CHANGED")
    count = len(verified_prefix.bars) if prefix_count is None else prefix_count
    if (
        count != state.bar_count or count > len(verified_prefix.bars)
        or verified_prefix.prefix_digest(count) != state.prefix_digest
    ):
        raise ValueError("STATE_PREFIX_CHANGED")
    return replace(state, identity=source)
