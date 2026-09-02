"""Read-only Newow actual-dominant D1 detail endpoint."""

from __future__ import annotations

from datetime import date
from typing import Literal

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

router = APIRouter(prefix="/api/v1/market/newow", tags=["market"])

_CLIENT_ERRORS = frozenset({"NEWOW_INVALID_PRODUCT", "NEWOW_INVALID_RANGE"})
_TREND_MARKERS = frozenset({"BUILD", "CLEAR"})
_ESCAPE_MARKERS = frozenset({"NEWOW_ESCAPE_D1", "NEWOW_ESCAPE_D2", "NEWOW_ESCAPE_D3"})


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
        result = NewowTrendDetailService(build_market_data_service(session)).query(
            NewowTrendDetailQuery(product, from_, through)
        )
    except NewowTrendDetailError as exc:
        raise HTTPException(
            status_code=422 if exc.code in _CLIENT_ERRORS else 409,
            detail={"code": exc.code},
        ) from exc
    except ValueError as exc:
        code = str(exc)
        if code not in _CLIENT_ERRORS:
            code = "NEWOW_DATA_UNAVAILABLE"
        raise HTTPException(status_code=422, detail={"code": code}) from exc
    return _response(result)


def _response(result: NewowTrendDetailResult) -> NewowTrendDetailResponse:
    markers = tuple(_marker(marker) for marker in result.markers)
    return NewowTrendDetailResponse(
        meta=NewowMetaOut(
            strategy="newow_trend_v1",
            profile=result.instrument.profile_id,
            frequency=result.instrument.frequency,
            series_kind=result.instrument.series_kind,
            calculation_identity=result.calculation_identity,
            request_identity=result.request_identity,
        ),
        instrument=NewowInstrumentOut(
            product=result.instrument.product,
            display_name=result.instrument.display_name,
            latest_physical_contract=result.instrument.latest_physical_contract,
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
        trigger_facts=dict(marker.trigger_facts),
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
        formula_version=value.formula_version,
    )
