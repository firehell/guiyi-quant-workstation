"""Bounded read-only historical reference; never invokes Alert or notification code."""

from collections.abc import Callable
from datetime import date, datetime
from threading import BoundedSemaphore
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market_data.composition import (
    build_market_data_service,
    build_database_coverage_source,
)
from app.market_data.market_data_service import MarketDataError
from app.market_data.actual_dominant_research import (
    ActualDominantResearchSegmentIdentityError,
)
from app.market_data.operational_universe import load_active_products
from app.market_data.subing_reference import (
    SubingReferenceQuery,
    SubingReferenceService,
    SubingReferenceError,
)
from app.schemas.subing_reference import SubingReferenceResponse

router = APIRouter(prefix="/api/v1/market", tags=["market"])
_GATE = BoundedSemaphore(1)
_FIELDS = frozenset({"since", "through", "as_of", "before", "limit"})


def _build_service(
    session: Session, check_cancelled: Callable[[], None]
) -> SubingReferenceService:
    return SubingReferenceService(
        build_market_data_service(session),
        coverage=build_database_coverage_source(session),
        active_products=load_active_products(),
        check_cancelled=check_cancelled,
    )


@router.get("/{symbol}/subing/reference", response_model=SubingReferenceResponse)
def subing_reference(
    request: Request,
    symbol: str,
    since: date | None = None,
    through: date | None = None,
    as_of: datetime | None = None,
    before: str | None = Query(default=None, max_length=129),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> SubingReferenceResponse:
    keys = [key for key, _ in request.query_params.multi_items()]
    if set(keys) - _FIELDS or len(keys) != len(set(keys)):
        raise HTTPException(422, detail={"code": "SUBING_REFERENCE_INVALID_QUERY"})
    if not _GATE.acquire(blocking=False):
        raise HTTPException(503, detail={"code": "SUBING_REFERENCE_BUSY"})
    deadline = monotonic() + 30

    def check_cancelled() -> None:
        if monotonic() > deadline:
            raise SubingReferenceError("SUBING_REFERENCE_BUDGET_EXCEEDED")

    try:
        result = _build_service(session, check_cancelled).query(
            SubingReferenceQuery(symbol, since, through, as_of, before, limit)
        )
        return SubingReferenceResponse.model_validate(result)
    except SubingReferenceError as exc:
        status = (
            422
            if exc.code == "SUBING_REFERENCE_INVALID_QUERY"
            else 503
            if exc.code == "SUBING_REFERENCE_BUDGET_EXCEEDED"
            else 409
        )
        raise HTTPException(status, detail={"code": exc.code}) from None
    except ActualDominantResearchSegmentIdentityError:
        raise HTTPException(
            409, detail={"code": "SUBING_REFERENCE_DATA_CONFLICT"}
        ) from None
    except (MarketDataError, ValueError):
        raise HTTPException(
            409, detail={"code": "SUBING_REFERENCE_DATA_UNAVAILABLE"}
        ) from None
    except Exception:  # noqa: BLE001 - only a public classification may cross the API boundary
        raise HTTPException(
            500, detail={"code": "SUBING_REFERENCE_INTERNAL_ERROR"}
        ) from None
    finally:
        _GATE.release()
