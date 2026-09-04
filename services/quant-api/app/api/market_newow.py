"""Read-only Newow actual-dominant D1 detail endpoint."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from math import isfinite
from typing import Literal, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query
from guiyi_quant.newow.models import CupPivot, NewowCupHandleOverlay, NewowMainMarker
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market_data.composition import build_market_data_service
from app.market_data.newow.trend_detail_query import NewowTrendDetailQuery
from app.market_data.newow.trend_detail_service import (
    NewowTrendDetailError,
    NewowTrendDetailResult,
    NewowTrendDetailService,
)
from app.market_data.product_taxonomy import ProductTaxonomyError, load_product_taxonomy
from app.schemas.market_newow import (
    NewowBarOut,
    NewowCupFormula,
    NewowCupHandleOut,
    NewowCupState,
    NewowCupPivotOut,
    NewowCompositeCleanroomOut,
    NewowCompositePageOut,
    NewowDiagnosticFactsOut,
    NewowDiagnosticTokenOut,
    NewowFirstActionOut,
    NewowFrequency,
    NewowFormulaDescriptionsOut,
    NewowMarkerFormula,
    NewowPageWindowOut,
    NewowPriceChannelOut,
    NewowSemanticLabelsOut,
    NewowInstrumentOut,
    NewowMarkerOut,
    NewowMetaOut,
    NewowProfileId,
    NewowRolloverSeamOut,
    NewowSeriesKind,
    NewowTrendBandOut,
    NewowTrendDetailResponse,
    NewowTrendStateBefore,
)

router = APIRouter(prefix="/api/v1/market/newow", tags=["market"])

_CLIENT_ERRORS = frozenset({"NEWOW_INVALID_PRODUCT", "NEWOW_INVALID_RANGE", "NEWOW_RANGE_TOO_LARGE"})
_TREND_MARKERS = frozenset({"BUILD", "CLEAR"})
_ESCAPE_MARKERS = frozenset({"NEWOW_ESCAPE_D1", "NEWOW_ESCAPE_D2", "NEWOW_ESCAPE_D3"})
_CUP_MARKERS = frozenset({"CUP_HANDLE_READY", "CUP_HANDLE_BREAKOUT", "CUP_HANDLE_WEAKENED", "CUP_HANDLE_INVALIDATED", "CUP_HANDLE_EXPIRED"})
_PROFILE_IDS: tuple[NewowProfileId, ...] = ("newow_trend_d1_page_v2",)
_FREQUENCIES: tuple[NewowFrequency, ...] = ("1d",)
_SERIES_KINDS: tuple[NewowSeriesKind, ...] = ("actual_dominant",)
_TREND_STATES_BEFORE: tuple[NewowTrendStateBefore, ...] = ("YELLOW", "BLUE")
_MARKER_FORMULAS: tuple[NewowMarkerFormula, ...] = (
    "newow_trend_band_page_v2",
    "newow_escape_d123_page_v2",
    "newow_cup_handle_v1",
)
_CUP_STATES: tuple[NewowCupState, ...] = (
    "FORMING",
    "READY",
    "BREAKOUT",
    "WEAKENED",
    "INVALIDATED",
    "EXPIRED",
)
_CUP_FORMULAS: tuple[NewowCupFormula, ...] = ("newow_cup_handle_v1",)
_LiteralValue = TypeVar("_LiteralValue", bound=str)


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
        result = NewowTrendDetailService(build_market_data_service(session), taxonomy=load_product_taxonomy()).query(
            NewowTrendDetailQuery(product, from_, through)
        )
        return _response(result)
    except NewowTrendDetailError as exc:
        raise HTTPException(
            status_code=422 if exc.code in _CLIENT_ERRORS else 409,
            detail={"code": exc.code},
        ) from exc
    except ProductTaxonomyError as exc:
        raise HTTPException(status_code=409, detail={"code": "NEWOW_DATA_UNAVAILABLE"}) from exc
    except ValueError as exc:
        code = str(exc)
        status_code = 422
        if code not in _CLIENT_ERRORS:
            code = "NEWOW_DATA_UNAVAILABLE"
            status_code = 409
        raise HTTPException(status_code=status_code, detail={"code": code}) from exc


def _response(result: NewowTrendDetailResult) -> NewowTrendDetailResponse:
    markers = tuple(_marker(marker) for marker in result.markers)
    return NewowTrendDetailResponse(
        meta=NewowMetaOut(
            strategy_code="newow_trend_v1",
            profile_id=_canonical_literal(result.instrument.profile_id, _PROFILE_IDS),
            frequency=_canonical_literal(result.instrument.frequency, _FREQUENCIES),
            series_kind=_canonical_literal(result.instrument.series_kind, _SERIES_KINDS),
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
                state_before=_canonical_optional_literal(
                    frame.trend_band.state_before.value
                    if frame.trend_band.state_before is not None
                    else None,
                    _TREND_STATES_BEFORE,
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
        price_channel=NewowPriceChannelOut.model_validate(
            asdict(result.price_channel)
        ),
        page_window_comparison=[
            NewowPageWindowOut.model_validate(asdict(item))
            for item in result.page_window_comparison
        ],
        composite_page=(
            NewowCompositePageOut.model_validate(asdict(result.composite_page))
            if result.composite_page is not None
            else None
        ),
        composite_cleanroom=(
            NewowCompositeCleanroomOut.model_validate(
                asdict(result.composite_cleanroom)
            )
            if result.composite_cleanroom is not None
            else None
        ),
        first_action_principle=NewowFirstActionOut.model_validate(
            asdict(result.first_action_principle)
        ),
        diagnostic_facts=NewowDiagnosticFactsOut.model_validate(
            asdict(result.diagnostic_facts)
        ),
        diagnostic_tokens=[
            NewowDiagnosticTokenOut.model_validate(asdict(item))
            for item in result.diagnostic_tokens
        ],
        semantic_labels=NewowSemanticLabelsOut.model_validate(
            asdict(result.semantic_labels)
        ),
        legend={
            "BUILD": "trend build",
            "CLEAR": "trend clear",
            "D1": "escape D1",
            "D2": "escape D2",
            "D3": "escape D3",
        },
        formula_descriptions=NewowFormulaDescriptionsOut.model_validate(
            {
                "trend_band": result.instrument.formula_versions[0],
                "escape": result.instrument.formula_versions[1],
                "cup_handle": result.instrument.formula_versions[2],
                "oscillation": result.instrument.formula_versions[3],
                "main_force": result.instrument.formula_versions[4],
                "main_rise": result.instrument.formula_versions[5],
                "price_channel": result.instrument.formula_versions[6],
                "display_selection": result.instrument.formula_versions[7],
                "page_window_comparison": result.instrument.formula_versions[8],
                "causal_window_identity": result.instrument.formula_versions[9],
                "composite_page": result.instrument.formula_versions[10],
                "composite_cleanroom": result.instrument.formula_versions[11],
                "first_action": result.instrument.formula_versions[12],
                "diagnostic_facts": result.instrument.formula_versions[13],
                "diagnostic_rules": result.instrument.formula_versions[14],
            }
        ),
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
        formula_version=_canonical_literal(marker.formula_version, _MARKER_FORMULAS),
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
        state=_canonical_literal(value.state.value, _CUP_STATES),
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
        formula_version=_canonical_literal(value.formula_version, _CUP_FORMULAS),
    )


def _canonical_literal(
    value: str,
    allowed: tuple[_LiteralValue, ...],
) -> _LiteralValue:
    for candidate in allowed:
        if value == candidate:
            return candidate
    raise NewowTrendDetailError("NEWOW_DATA_IDENTITY_INVALID")


def _canonical_optional_literal(
    value: str | None,
    allowed: tuple[_LiteralValue, ...],
) -> _LiteralValue | None:
    if value is None:
        return None
    return _canonical_literal(value, allowed)


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
