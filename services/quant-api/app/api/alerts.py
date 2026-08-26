"""Alert V2 scope, historical-event, and current-view HTTP API."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.current_trading_day import (
    CurrentTradingDayResult,
    CurrentTradingDayStatus,
    resolve_current_trading_day,
)
from app.alerts.models import AlertEvent, AlertRule
from app.alerts.registry import get_alert_rule_definition
from app.alerts.strategy_payload import (
    StrategyPayloadError,
    parse_subing_strategy_payload,
    validate_subing_strategy_event_facts,
)
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
from app.market_data.product_taxonomy import load_product_taxonomy
from app.schemas.alerts import (
    AlertEventListResponse,
    AlertEventOut,
    AlertScopeUpdate,
    CurrentAlertEventsResponse,
    CurrentStrategyActionEventsResponse,
    ProductAlertRuleStateOut,
    ProductAlertStateResponse,
    StrategyActionAlertEventOut,
    SubingStrategyActionOut,
)


router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def get_current_alert_trading_day(
    session: Session = Depends(get_db),
) -> CurrentTradingDayResult:
    """Resolve the current day only from the Task 3 phase-based resolver."""

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
    """Add or remove one operational product/frequency pair from HTDY scope."""

    try:
        state = _service(session).set_product_frequency_enabled(
            rule_code, symbol, frequency, request.enabled
        )
    except AlertRuleNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code}) from exc
    except AlertScopeError as exc:
        raise _scope_http_error(exc) from exc
    return _state_out(state)


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
    return AlertEventListResponse(
        items=[_event_out(event, rule_code=rule_code) for event in events]
    )


@router.get(
    "/strategy-actions/current",
    response_model=CurrentStrategyActionEventsResponse,
)
def current_strategy_action_events(
    current_day: CurrentTradingDayResult = Depends(get_current_alert_trading_day),
    session: Session = Depends(get_db),
) -> CurrentStrategyActionEventsResponse:
    """Return current-trading-day immutable Strategy Action events."""

    if current_day.status is CurrentTradingDayStatus.UNAVAILABLE:
        return CurrentStrategyActionEventsResponse(
            status="unavailable",
            trading_day=None,
            items=[],
        )
    assert current_day.trading_day is not None
    taxonomy = load_product_taxonomy()
    events = _service(session).list_current_strategy_action_events(
        trading_day=current_day.trading_day
    )
    return CurrentStrategyActionEventsResponse(
        status="ready",
        trading_day=current_day.trading_day,
        items=[
            StrategyActionAlertEventOut(
                **_event_out(event, rule_code=event.rule.rule_code).model_dump(),
                display_name=get_alert_rule_definition(
                    event.rule.rule_code
                ).display_name,
                product_name=taxonomy[event.symbol].name,
            )
            for event in events
        ],
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
    """Return one product's current-trading-day Alert events."""

    if current_day.status is CurrentTradingDayStatus.UNAVAILABLE:
        return CurrentAlertEventsResponse(
            status="unavailable",
            trading_day=None,
            items=[],
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
        items=[_event_out(event, rule_code=event.rule.rule_code) for event in events],
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
    """Preserve the bounded legacy range view while serializing its V2 fields."""

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
    statement = (
        select(AlertEvent)
        .where(
            AlertEvent.rule_id == rule.id,
            AlertEvent.symbol == normalize_symbol(symbol),
            AlertEvent.bar_end >= start,
            AlertEvent.bar_end <= end,
        )
        .order_by(AlertEvent.bar_end)
    )
    return tuple(session.scalars(statement).all())


def _event_out(event: AlertEvent, *, rule_code: str) -> AlertEventOut:
    definition = get_alert_rule_definition(rule_code)
    bar_end = _utc(event.bar_end)
    strategy_action: SubingStrategyActionOut | None = None
    try:
        if definition.kind.value == "indicator_observation":
            if event.action_id is not None or event.strategy_payload is not None:
                raise StrategyPayloadError()
        else:
            if (
                event.action_id is None
                or event.strategy_payload is None
                or event.trading_day is None
            ):
                raise StrategyPayloadError()
            payload = parse_subing_strategy_payload(event.strategy_payload)
            validate_subing_strategy_event_facts(
                payload,
                action_id=event.action_id,
                symbol=event.symbol,
                contract=event.contract,
                trading_day=event.trading_day,
                frequency=event.frequency,
                bar_end=bar_end,
                result_codes=tuple(event.result_codes),
            )
            strategy_action = SubingStrategyActionOut.model_validate(payload.to_json())
    except StrategyPayloadError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "ALERT_EVENT_FACTS_INVALID"},
        ) from exc
    return AlertEventOut(
        id=event.id,
        rule_code=rule_code,
        symbol=event.symbol,
        contract=event.contract,
        trading_day=event.trading_day,
        frequency=event.frequency,
        bar_end=bar_end,
        result_codes=list(event.result_codes),
        action_id=event.action_id,
        strategy_action=strategy_action,
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
