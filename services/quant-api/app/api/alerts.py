"""Minimal Alert V1 scope and persistent-event HTTP API."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.alerts.service import (
    AlertRuleNotFoundError,
    AlertScopeError,
    AlertService,
    ProductAlertRuleState,
)
from app.db.session import get_db
from app.market_data.operational_universe import load_operational_products
from app.market_data.product_retirement import normalize_symbol
from app.schemas.alerts import (
    AlertEventListResponse,
    AlertEventOut,
    AlertScopeUpdate,
    ProductAlertRuleStateOut,
    ProductAlertStateResponse,
)


router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("/products/{symbol}", response_model=ProductAlertStateResponse)
def product_alert_state(
    symbol: str,
    session: Session = Depends(get_db),
) -> ProductAlertStateResponse:
    """Return code-defined rules and server-side scope state for one product."""

    try:
        rules = _service(session).product_rules(symbol)
    except AlertScopeError as exc:
        raise _scope_http_error(exc) from exc
    return ProductAlertStateResponse(
        symbol=normalize_symbol(symbol),
        rules=[_state_out(item) for item in rules],
    )


@router.put(
    "/rules/{rule_code}/scope/{symbol}",
    response_model=ProductAlertRuleStateOut,
)
def set_product_alert_scope(
    rule_code: str,
    symbol: str,
    request: AlertScopeUpdate,
    session: Session = Depends(get_db),
) -> ProductAlertRuleStateOut:
    """Add or remove one operational product from one existing rule scope."""

    try:
        state = _service(session).set_product_enabled(
            rule_code, symbol, request.enabled
        )
    except AlertRuleNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code}) from exc
    except AlertScopeError as exc:
        raise _scope_http_error(exc) from exc
    return _state_out(state)


@router.get("/events", response_model=AlertEventListResponse)
def alert_events(
    symbol: str = Query(...),
    rule_code: str = Query(...),
    start: datetime = Query(...),
    end: datetime = Query(...),
    session: Session = Depends(get_db),
) -> AlertEventListResponse:
    """Read persistent AlertEvent markers for one rule/product/time range."""

    try:
        events = _service(session).list_events(
            symbol=symbol,
            rule_code=rule_code,
            start=start,
            end=end,
        )
    except AlertRuleNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code}) from exc
    except AlertScopeError as exc:
        raise _scope_http_error(exc) from exc
    return AlertEventListResponse(
        items=[
            AlertEventOut(
                id=event.id,
                rule_code=rule_code,
                symbol=event.symbol,
                contract=event.contract,
                frequency=event.frequency,
                bar_end=event.bar_end,
                observation_types=list(event.observation_types),
                detected_at=event.detected_at,
                notified_at=event.notified_at,
            )
            for event in events
        ]
    )


def _service(session: Session) -> AlertService:
    return AlertService(session, operational_products=load_operational_products())


def _state_out(state: ProductAlertRuleState) -> ProductAlertRuleStateOut:
    return ProductAlertRuleStateOut(
        rule_code=state.rule_code,
        display_name=state.display_name,
        indicator_code=state.indicator_code,
        series_kind=state.series_kind,
        frequency=state.frequency,
        enabled_for_product=state.enabled_for_product,
    )


def _scope_http_error(exc: AlertScopeError) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": exc.code})
