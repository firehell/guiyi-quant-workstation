"""Read-only Newow actual-dominant D1 detail endpoint."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from math import isfinite
from typing import Literal
from collections.abc import Mapping

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from guiyi_quant.newow.models import CupPivot, NewowCupHandleOverlay, NewowMainMarker
from guiyi_quant.newow.product_contracts import ProductFrequency, ProductStrategy
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market_data.composition import (
    build_database_coverage_source,
    build_market_data_service,
)
from app.market_data.newow.product_reader import (
    NewowProductReadError,
    NewowProductReader,
)
from app.market_data.newow.product_service import (
    NewowProductResult,
    NewowProductService,
    NewowProductServiceError,
    ProductServiceQuery,
    ProductSection,
    AuxiliaryComponent,
)
from app.market_data.newow.resource_gate import HeavyResourceGate, NewowResourceBusy
from app.market_data.newow.snapshot_cache import SnapshotCache
from app.market_data.operational_universe import (
    ActiveUniverseError,
    load_active_products,
)
from app.market_data.newow.trend_detail_query import NewowTrendDetailQuery
from app.market_data.newow.trend_detail_service import (
    NewowTrendDetailError,
    NewowTrendDetailResult,
    NewowTrendDetailService,
)
from app.market_data.product_taxonomy import ProductTaxonomyError, load_product_taxonomy
from app.schemas.market_newow import (
    NewowBarOut,
    NewowCupHandleOut,
    NewowCupPivotOut,
    NewowInstrumentOut,
    NewowMarkerOut,
    NewowMetaOut,
    NewowRolloverSeamOut,
    NewowTrendBandOut,
    NewowTrendDetailResponse,
)
from app.schemas.market_newow_product import NewowProductResponse

router = APIRouter(prefix="/api/v1/market/newow", tags=["market"])

_CLIENT_ERRORS = frozenset(
    {"NEWOW_INVALID_PRODUCT", "NEWOW_INVALID_RANGE", "NEWOW_RANGE_TOO_LARGE"}
)
_TREND_MARKERS = frozenset({"BUILD", "CLEAR"})
_ESCAPE_MARKERS = frozenset({"NEWOW_ESCAPE_D1", "NEWOW_ESCAPE_D2", "NEWOW_ESCAPE_D3"})
_CUP_MARKERS = frozenset(
    {
        "CUP_HANDLE_READY",
        "CUP_HANDLE_BREAKOUT",
        "CUP_HANDLE_WEAKENED",
        "CUP_HANDLE_INVALIDATED",
        "CUP_HANDLE_EXPIRED",
    }
)
_PRODUCT_CACHE = SnapshotCache()
_PRODUCT_GATE = HeavyResourceGate()
_PRODUCT_QUERY_FIELDS = frozenset(
    {
        "product",
        "strategy",
        "frequency",
        "series_kind",
        "section",
        "from",
        "through",
        "performance_since",
        "performance_through",
        "as_of",
        "chart_limit",
        "chart_before",
        "component",
        "history_limit",
        "history_before",
        "snapshot_token",
    }
)


@router.get("/trend-detail", response_model=NewowTrendDetailResponse)
def newow_trend_detail(
    product: str = Query(...),
    from_: date = Query(..., alias="from"),
    through: date = Query(...),
    frequency: Literal["1d"] = Query(default="1d"),
    series_kind: Literal["actual_dominant"] = Query(default="actual_dominant"),
    session: Session = Depends(get_db),
) -> NewowTrendDetailResponse:
    del frequency, series_kind
    try:
        result = NewowTrendDetailService(
            build_market_data_service(session), taxonomy=load_product_taxonomy()
        ).query(NewowTrendDetailQuery(product, from_, through))
        return _response(result)
    except NewowTrendDetailError as exc:
        raise HTTPException(
            status_code=422 if exc.code in _CLIENT_ERRORS else 409,
            detail={"code": exc.code},
        ) from exc
    except ProductTaxonomyError as exc:
        raise HTTPException(
            status_code=409, detail={"code": "NEWOW_DATA_UNAVAILABLE"}
        ) from exc
    except ValueError as exc:
        code = str(exc)
        if code not in _CLIENT_ERRORS:
            code = "NEWOW_DATA_UNAVAILABLE"
        raise HTTPException(status_code=422, detail={"code": code}) from exc


def _build_product_service(session: Session) -> NewowProductService:
    market_data = build_market_data_service(session)
    coverage = build_database_coverage_source(session)
    active = load_active_products()

    def reader_factory(context, cancelled):
        return NewowProductReader(
            market_data,
            coverage=coverage,
            active_products=active,
            context_frequencies=context,
            cancelled=cancelled,
        )

    return NewowProductService(
        reader_factory,
        cache=_PRODUCT_CACHE,
        heavy_gate=_PRODUCT_GATE,
    )


@router.get("/strategy-detail", response_model=NewowProductResponse)
def newow_strategy_detail(
    request: Request,
    product: str = Query(...),
    strategy: Literal["trend", "oscillation", "main_rise"] = Query(...),
    frequency: Literal["1w", "1d", "60m"] = Query(...),
    series_kind: Literal["actual_dominant"] = Query("actual_dominant"),
    section: Literal[
        "chart", "auxiliary", "reference", "explanation", "comparator"
    ] = Query("chart"),
    from_: date | None = Query(None, alias="from"),
    through: date | None = Query(None),
    performance_since: date | None = Query(None),
    performance_through: date | None = Query(None),
    as_of: datetime | None = Query(None),
    chart_limit: int = Query(500, ge=1, le=2000),
    chart_before: str | None = Query(None, min_length=1, max_length=2048),
    component: Literal[
        "main_force_control", "up_down_energy", "zhaoyao_mirror", "cup_handle"
    ]
    | None = Query(None),
    history_limit: int = Query(50, ge=1, le=200),
    history_before: str | None = Query(None, min_length=1, max_length=2048),
    snapshot_token: str | None = Query(None, min_length=1, max_length=256),
    session: Session = Depends(get_db),
) -> NewowProductResponse:
    unknown = set(request.query_params) - _PRODUCT_QUERY_FIELDS
    duplicates = {
        key
        for key in request.query_params
        if len(request.query_params.getlist(key)) != 1
    }
    if (
        unknown
        or duplicates
        or (as_of is not None and as_of.utcoffset() is None)
        or (as_of is not None and as_of.astimezone(UTC) > datetime.now(UTC))
    ):
        raise HTTPException(status_code=422, detail={"code": "NEWOW_INVALID_QUERY"})
    try:
        product_query = ProductServiceQuery(
            product=product,
            strategy=ProductStrategy(strategy),
            frequency=ProductFrequency(frequency),
            section=ProductSection(section),
            since=from_,
            through=through,
            performance_since=performance_since,
            performance_through=performance_through,
            as_of=as_of,
            series_kind=series_kind,
            chart_limit=chart_limit,
            chart_before=chart_before,
            component=AuxiliaryComponent(component) if component is not None else None,
            history_limit=history_limit,
            history_before=history_before,
            snapshot_token=snapshot_token,
        )
        result = _build_product_service(session).query(product_query)
        return _product_response(result)
    except NewowResourceBusy as exc:
        raise HTTPException(status_code=429, detail={"code": exc.code}) from exc
    except NewowProductServiceError as exc:
        status = 409 if "CONFLICT" in exc.code else 422
        raise HTTPException(status_code=status, detail={"code": exc.code}) from exc
    except NewowProductReadError as exc:
        status = 422 if exc.code.startswith("NEWOW_INVALID_") else 409
        raise HTTPException(status_code=status, detail={"code": exc.code}) from exc
    except (ActiveUniverseError, ProductTaxonomyError) as exc:
        raise HTTPException(
            status_code=409, detail={"code": "NEWOW_DATA_UNAVAILABLE"}
        ) from exc
    except ValueError as exc:
        code = str(exc)
        status = (
            422
            if code.startswith("NEWOW_INVALID_")
            or "REQUIRED" in code
            or "PARAMETER" in code
            else 409
        )
        raise HTTPException(status_code=status, detail={"code": code}) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail={"code": "NEWOW_INTERNAL_ERROR"}
        ) from exc


def _status(value) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "status": value.status.value,
        "evidence_status": value.evidence_status.value,
        "reason_code": value.reason_code,
    }


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
        return format(value, "f")
    if isinstance(value, Fraction):
        return f"{value.numerator}/{value.denominator}"
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    raise ValueError("NEWOW_DATA_IDENTITY_INVALID")


def _bar(item) -> dict[str, object]:
    bar = item.bar
    return {
        "bar_end": bar.bar_end,
        "trading_day": bar.trading_day,
        "open": _decimal(bar.open),
        "high": _decimal(bar.high),
        "low": _decimal(bar.low),
        "close": _decimal(bar.close),
        "volume": bar.volume,
        "open_interest": bar.open_interest,
        "physical_contract": bar.physical_contract,
        "segment_id": bar.segment_id,
        "source_identity": bar.source_identity,
        "observation_eligible": bar.observation_eligible,
        "completed": True,
    }


def _trade(item) -> dict[str, object]:
    return {
        field.name: (
            _decimal(value)
            if isinstance(value, Decimal)
            else value.value
            if isinstance(value, Enum)
            else list(value)
            if field.name in {"formula_versions", "hint_ids"}
            else value
        )
        for field in fields(item)
        if (value := getattr(item, field.name)) is not None
        or field.name
        in {
            "exit_signal_id",
            "exit_bar_end",
            "exit_trading_day",
            "exit_reference_price",
            "reference_return_pct",
            "mark_bar_end",
            "mark_reference_price",
            "mark_change_pct",
            "interrupted_at",
            "interruption_reason",
            "statistics_membership",
        }
    }


def _delivery(value, serializer) -> dict[str, object]:
    return {
        "delivery": value.delivery,
        "status": _status(value.status),
        "value": None if value.value is None else serializer(value.value),
    }


def _product_response(result: NewowProductResult) -> NewowProductResponse:
    meta = result.meta
    identity = meta.identity
    chart = _delivery(
        result.chart,
        lambda value: {
            "bars": [_bar(item) for item in value.bars],
            "frames": [
                {
                    "bar_end": frame.bar.bar.bar_end,
                    "main_state": frame.main_state.value,
                    "main_values": {
                        key: _decimal(item) for key, item in frame.main_values
                    },
                    "status": _status(frame.availability),
                    "action_ids": [action.signal_id for action in frame.actions],
                    "hint_ids": [hint.hint_id for hint in frame.hints],
                }
                for frame in value.replay.frames
            ],
            "actions": [
                {
                    "signal_id": item.signal_id,
                    "kind": item.kind.value,
                    "bar_end": item.bar_end,
                    "trading_day": item.trading_day,
                    "reference_price": _decimal(item.reference_price),
                    "physical_contract": item.physical_contract,
                    "segment_id": item.segment_id,
                    "related_build_id": item.related_build_id,
                    "trade_eligibility": item.trade_eligibility.value,
                }
                for item in value.replay.actions
            ],
            "hints": [
                {
                    "hint_id": item.hint_id,
                    "kind": item.kind,
                    "bar_end": item.bar_end,
                    "known_at": item.known_at,
                    "anchor_price": _decimal(item.anchor_price),
                    "physical_contract": item.physical_contract,
                    "segment_id": item.segment_id,
                    "retrospective": False,
                    "quantity_effect": "none",
                }
                for item in value.replay.hints
            ],
            "diagnostics": list(value.diagnostics),
            "next_before": value.next_before,
            "repainting": False,
            "formal_signal_eligible": True,
            "allowed_uses": ["product_chart", "reference_input"],
        },
    )
    reference = _delivery(
        result.reference,
        lambda value: {
            "performance_since": value.requested_window.since,
            "performance_through": value.requested_window.through,
            "actual_available_through": value.actual_available_through,
            "reference_cutoff": value.reference_cutoff,
            "reference_input_sha256": value.reference_input_sha256,
            "summary": {
                "membership_policy": value.summary.membership_policy,
                "closed_count": value.summary.closed_count,
                "win_count": value.summary.win_count,
                "loss_count": value.summary.loss_count,
                "flat_count": value.summary.flat_count,
                "win_rate_pct": _decimal(value.summary.win_rate_pct),
                "mean_return_pct": _decimal(value.summary.mean_return_pct),
                "sum_return_percentage_points": _decimal(
                    value.summary.sum_return_percentage_points
                ),
                "open_count": value.summary.open_count,
                "interrupted_count": value.summary.interrupted_count,
                "initial_count": value.summary.initial_count,
            },
            "items": [_trade(item) for item in value.items],
            "next_before": value.next_before,
            "executable": False,
            "auto_order": False,
            "allowed_uses": ["page_parity_reference", "research_display"],
        },
    )
    auxiliary = _delivery(
        result.auxiliary,
        lambda value: {
            "component": value.name,
            "formula_version": value.formula_version,
            "segments": [
                {
                    "physical_contract": segment.physical_contract,
                    "segment_id": segment.segment_id,
                    "bar_ends": list(segment.bar_ends),
                    "status": _status(segment.status),
                    "data": _json_value(segment.value),
                }
                for segment in value.segments
            ],
            "repainting": value.repainting,
            "formal_signal_eligible": value.formal_signal_eligible,
            "page_parity": value.page_parity,
            "source_category": "guiyi_product_auxiliary_adapter",
            "allowed_uses": ["retrospective_display"]
            if value.repainting
            else ["product_display"],
        },
    )
    explanation = _delivery(
        result.explanation,
        lambda value: {
            "context": _json_value(value.context),
            "composite": _json_value(value.composite),
            "target_absorb": _json_value(value.target_absorb),
            "sources": [_json_value(source) for source in value.sources],
            "page_parity": False,
            "allowed_uses": ["research_explanation", "product_display"],
        },
    )
    comparator = _delivery(
        result.comparator,
        lambda value: {
            "result": _json_value(value),
            "executable": False,
            "page_parity": False,
            "synthetic_terminal_is_reference_exit": False,
            "allowed_uses": ["in_sample_comparison"],
        },
    )
    payload = {
        "meta": {
            "schema_version": meta.schema_version,
            "identity": {
                "product": identity.product,
                "strategy": identity.strategy.value,
                "frequency": identity.frequency.value,
                "series_kind": identity.series_kind,
                "profile_id": identity.profile_id,
                "formula_versions": list(identity.formula_versions),
            },
            "as_of": meta.as_of,
            "read_at": meta.read_at,
            "input_content_sha256": meta.input_content_sha256,
            "data_revision_identity": None,
            "snapshot_token": meta.snapshot_token,
            "reference_model_version": meta.reference_model_version,
            "futures_adaptation_version": meta.futures_adaptation_version,
        },
        "section": result.section.value,
        "chart": chart,
        "auxiliary": auxiliary,
        "reference": reference,
        "explanation": explanation,
        "comparator": comparator,
    }
    return NewowProductResponse.model_validate(payload)


def _response(result: NewowTrendDetailResult) -> NewowTrendDetailResponse:
    markers = tuple(_marker(marker) for marker in result.markers)
    return NewowTrendDetailResponse(
        meta=NewowMetaOut(
            strategy_code="newow_trend_v1",
            profile_id=result.instrument.profile_id,
            frequency=result.instrument.frequency,
            series_kind=result.instrument.series_kind,
            calculation_identity=result.calculation_identity,
            data_revision_identity=result.data_revision_identity,
            request_identity=result.request_identity,
        ),
        instrument=NewowInstrumentOut(
            product=result.instrument.product,
            display_name=result.instrument.display_name,
            last_visible_physical_contract=result.instrument.last_visible_physical_contract,
        ),
        bars=[
            NewowBarOut(
                bar_end=bar.bar_end,
                trading_day=bar.trading_day,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                open_interest=bar.open_interest,
                physical_contract=bar.physical_contract,
                segment_id=bar.segment_id,
                source_identity=bar.source_identity,
            )
            for bar in result.bars
        ],
        bar_policy="completed_only",
        trend_band=[
            NewowTrendBandOut(
                bar_end=frame.bar.bar_end,
                b_value=frame.trend_band.b_value,
                c_value=frame.trend_band.c_value,
                state=frame.trend_band.state.value,
                state_before=(
                    frame.trend_band.state_before.value
                    if frame.trend_band.state_before is not None
                    else None
                ),
                transition=(
                    frame.trend_band.transition.value
                    if frame.trend_band.transition is not None
                    else None
                ),
            )
            for frame in result.frames
        ],
        trend_markers=[item for item in markers if item.marker_type in _TREND_MARKERS],
        escape_markers=[
            item for item in markers if item.marker_type in _ESCAPE_MARKERS
        ],
        cup_markers=[item for item in markers if item.marker_type in _CUP_MARKERS],
        cup_handles=[_cup_handle(item) for item in result.cup_handles],
        rollover_seams=[
            NewowRolloverSeamOut(
                trading_day=item.trading_day,
                previous_contract=item.previous_contract,
                next_contract=item.next_contract,
                previous_bar_end=item.previous_bar_end,
                next_bar_end=item.next_bar_end,
                previous_segment_id=item.previous_segment_id,
                next_segment_id=item.next_segment_id,
            )
            for item in result.rollover_seams
        ],
        legend={
            "BUILD": "trend build",
            "CLEAR": "trend clear",
            "D1": "escape D1",
            "D2": "escape D2",
            "D3": "escape D3",
        },
        formula_descriptions={
            "trend_band": result.instrument.formula_versions[0],
            "escape": result.instrument.formula_versions[1],
            "cup_handle": result.instrument.formula_versions[2],
        },
        warnings=list(result.warnings),
    )


def _marker(marker: NewowMainMarker) -> NewowMarkerOut:
    return NewowMarkerOut(
        marker_id=marker.marker_id,
        marker_type=marker.marker_type.value,
        bar_end=marker.bar_end,
        price=marker.price,
        label=marker.label,
        color_token=marker.color_token,
        priority=marker.priority,
        related_marker_ids=tuple(marker.related_marker_ids),
        trigger_facts=_safe_mapping(marker.trigger_facts),
        formula_version=marker.formula_version,
    )


def _pivot(pivot: CupPivot) -> NewowCupPivotOut:
    return NewowCupPivotOut(
        pivot_at=pivot.pivot_at,
        confirmed_at=pivot.confirmed_at,
        price=pivot.price,
    )


def _cup_handle(value: NewowCupHandleOverlay) -> NewowCupHandleOut:
    return NewowCupHandleOut(
        candidate_id=value.candidate_id,
        direction=value.direction.value,
        state=value.state.value,
        left_rim=_pivot(value.left_rim),
        bottom=_pivot(value.bottom),
        right_rim=_pivot(value.right_rim),
        handle_start_at=value.handle_start_at,
        handle_extreme=_pivot(value.handle_extreme) if value.handle_extreme else None,
        pivot_price=value.pivot_price,
        pivot_frozen_at=value.pivot_frozen_at,
        confirmed_at=value.confirmed_at,
        first_seen_at=value.first_seen_at,
        state_changed_at=value.state_changed_at,
        score=value.score,
        score_breakdown=_safe_float_mapping(value.score_breakdown),
        hard_failures=_safe_strings(value.hard_failures),
        diagnostics=_safe_strings(value.diagnostics),
        volume_facts=_safe_float_mapping(value.volume_facts),
        formula_version=value.formula_version,
    )


def _safe_mapping(values: Mapping[str, object]) -> dict[str, object]:
    return {key: _safe_value(value) for key, value in values.items() if _safe_key(key)}


def _safe_key(value: object) -> bool:
    if not isinstance(value, str):
        raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
    return True


def _safe_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if isfinite(value):
            return value
        raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
    if isinstance(value, Decimal):
        if value.is_finite():
            return format(value, "f")
        raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return _safe_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")


def _safe_float_mapping(values: Mapping[str, float]) -> dict[str, float]:
    mapped: dict[str, float] = {}
    for key, value in values.items():
        _safe_key(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
        ):
            raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
        mapped[key] = float(value)
    return mapped


def _safe_strings(values: tuple[str, ...]) -> list[str]:
    if any(not isinstance(value, str) for value in values):
        raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")
    return list(values)
