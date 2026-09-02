"""HTDY Alert scope, history, and current-view API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.current_trading_day import (
    CurrentTradingDayResult,
    CurrentTradingDayStatus,
    resolve_current_trading_day,
)
from app.alerts.models import AlertEvent, AlertRule
from app.alerts.registry import HTDY_ALERT_RULE_CODE, get_alert_rule_definition
from app.alerts.service import (
    AlertRuleNotFoundError,
    AlertScopeError,
    AlertService,
    ProductAlertRuleState,
)
from app.db.session import get_db
from app.market_data.market_phase import MarketPhaseResolver
from app.market_data.operational_universe import load_operational_products
from app.market_data.product_retirement import normalize_symbol
from app.schemas.alerts import (
    AlertEventListResponse,
    AlertScopeUpdate,
    CurrentAlertEventsResponse,
    CurrentHtdyEventsResponse,
    HtdyAlertEventOut,
    ProductAlertRuleStateOut,
    ProductAlertStateResponse,
)


router = APIRouter(prefix="/api/alerts", tags=["alerts"])
_RESULT_CODES = TypeAdapter(list[Literal["buy", "sell"]])


def get_current_alert_trading_day(
    session: Session = Depends(get_db),
) -> CurrentTradingDayResult:
    return resolve_current_trading_day(
        MarketPhaseResolver(session),
        products=load_operational_products(),
        now=datetime.now(UTC),
    )


@router.get("/products/{symbol}", response_model=ProductAlertStateResponse)
def product_alert_state(
    symbol: str,
    session: Session = Depends(get_db),
) -> ProductAlertStateResponse:
    try:
        rules = _service(session).product_rules(symbol)
    except AlertScopeError as exc:
        raise _scope_http_error(exc) from exc
    return ProductAlertStateResponse(
        symbol=normalize_symbol(symbol),
        rules=[_state_out(item) for item in rules],
    )


@router.put(
    "/rules/{rule_code}/scope/{symbol}/{frequency}",
    response_model=ProductAlertRuleStateOut,
)
def set_product_frequency_alert_scope(
    rule_code: str,
    symbol: str,
    frequency: str,
    request: AlertScopeUpdate,
    session: Session = Depends(get_db),
) -> ProductAlertRuleStateOut:
    try:
        state = _service(session).set_product_frequency_enabled(
            rule_code, symbol, frequency, request.enabled
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
    try:
        events = _list_events(
            session,
            symbol=symbol,
            rule_code=rule_code,
            start=start,
            end=end,
        )
    except AlertRuleNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code}) from exc
    except AlertScopeError as exc:
        raise _scope_http_error(exc) from exc
    return AlertEventListResponse(items=[_event_out(event) for event in events])


@router.get("/current-events", response_model=CurrentHtdyEventsResponse)
def current_alert_events(
    limit: int = Query(default=30, ge=1, le=100),
    current_day: CurrentTradingDayResult = Depends(get_current_alert_trading_day),
    session: Session = Depends(get_db),
) -> CurrentHtdyEventsResponse:
    if current_day.status is CurrentTradingDayStatus.UNAVAILABLE:
        return CurrentHtdyEventsResponse(
            status="unavailable", trading_day=None, items=[]
        )
    assert current_day.trading_day is not None
    events = _service(session).list_current_events(
        trading_day=current_day.trading_day,
        limit=limit,
    )
    return CurrentHtdyEventsResponse(
        status="ready",
        trading_day=current_day.trading_day,
        items=[_event_out(event) for event in events],
    )


@router.get(
    "/products/{symbol}/current-events",
    response_model=CurrentAlertEventsResponse,
)
def current_product_alert_events(
    symbol: str,
    current_day: CurrentTradingDayResult = Depends(get_current_alert_trading_day),
    session: Session = Depends(get_db),
) -> CurrentAlertEventsResponse:
    if current_day.status is CurrentTradingDayStatus.UNAVAILABLE:
        return CurrentAlertEventsResponse(
            status="unavailable", trading_day=None, items=[]
        )
    assert current_day.trading_day is not None
    try:
        events = _service(session).list_current_product_events(
            symbol=symbol,
            trading_day=current_day.trading_day,
        )
    except AlertScopeError as exc:
        raise _scope_http_error(exc) from exc
    return CurrentAlertEventsResponse(
        status="ready",
        trading_day=current_day.trading_day,
        items=[_event_out(event) for event in events],
    )


def _service(session: Session) -> AlertService:
    return AlertService(session, operational_products=load_operational_products())


def _state_out(state: ProductAlertRuleState) -> ProductAlertRuleStateOut:
    return ProductAlertRuleStateOut(
        rule_code=state.rule_code,
        display_name=state.display_name,
        kind=state.kind,
        input_frequencies=list(state.input_frequencies),
        enabled_frequencies=list(state.enabled_frequencies),
        enabled_for_product=state.enabled_for_product,
    )


def _list_events(
    session: Session,
    *,
    symbol: str,
    rule_code: str,
    start: datetime,
    end: datetime,
) -> tuple[AlertEvent, ...]:
    service = _service(session)
    service.product_rules(symbol)
    if start.tzinfo is None or start.utcoffset() is None:
        raise AlertScopeError("ALERT_TIMEZONE_REQUIRED")
    if end.tzinfo is None or end.utcoffset() is None:
        raise AlertScopeError("ALERT_TIMEZONE_REQUIRED")
    if start >= end:
        raise AlertScopeError("ALERT_EVENT_RANGE_INVALID")
    try:
        get_alert_rule_definition(rule_code)
    except KeyError:
        raise AlertRuleNotFoundError() from None
    rule = session.scalar(select(AlertRule).where(AlertRule.rule_code == rule_code))
    if rule is None:
        raise AlertRuleNotFoundError()
    return tuple(
        session.scalars(
            select(AlertEvent)
            .where(
                AlertEvent.rule_id == rule.id,
                AlertEvent.symbol == normalize_symbol(symbol),
                AlertEvent.bar_end >= start,
                AlertEvent.bar_end <= end,
            )
            .order_by(AlertEvent.bar_end)
        ).all()
    )


def _event_out(event: AlertEvent) -> HtdyAlertEventOut:
    try:
        result_codes = _RESULT_CODES.validate_python(event.result_codes)
    except ValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "ALERT_EVENT_FACTS_INVALID"},
        ) from exc
    return HtdyAlertEventOut(
        id=event.id,
        rule_code=HTDY_ALERT_RULE_CODE,
        symbol=event.symbol,
        contract=event.contract,
        trading_day=event.trading_day,
        frequency=event.frequency,
        bar_end=_utc(event.bar_end),
        result_codes=result_codes,
        detected_at=_utc(event.detected_at),
        notification_attempted_at=(
            _utc(event.notification_attempted_at)
            if event.notification_attempted_at is not None
            else None
        ),
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _scope_http_error(exc: AlertScopeError) -> HTTPException:
    status_code = 503 if exc.code == "ALERT_SCOPE_PERSIST_FAILED" else 422
    return HTTPException(status_code=status_code, detail={"code": exc.code})
