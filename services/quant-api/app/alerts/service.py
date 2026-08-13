"""Alert V1 rule scope and immutable event application service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.alerts.models import AlertEvent, AlertRule
from app.market_data.domain import normalize_contract_for_symbol
from app.market_data.product_retirement import normalize_symbol


class AlertConsistencyError(RuntimeError):
    """An existing event disagrees with the same unique event identity."""

    code = "ALERT_EVENT_CONSISTENCY_ERROR"

    def __init__(self) -> None:
        super().__init__(self.code)


class AlertRuleNotFoundError(LookupError):
    """A requested code-defined Alert rule does not exist."""

    code = "ALERT_RULE_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__(self.code)


class AlertScopeError(ValueError):
    """A symbol or event request is outside the bounded Alert contract."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ProductAlertRuleState:
    rule_code: str
    display_name: str
    indicator_code: str
    series_kind: str
    frequency: str
    enabled_for_product: bool


@dataclass(frozen=True, slots=True)
class AlertEventCreate:
    rule_id: int
    symbol: str
    contract: str
    frequency: str
    bar_end: datetime
    observation_types: tuple[str, ...]
    detected_at: datetime
    notified_at: datetime


class AlertService:
    """Manage server-side rule scope and idempotent AlertEvent facts."""

    def __init__(self, session: Session, *, operational_products: tuple[str, ...]) -> None:
        self._session = session
        self._operational_products = frozenset(
            normalize_symbol(item) for item in operational_products
        )

    def product_rules(self, symbol: str) -> tuple[ProductAlertRuleState, ...]:
        normalized = self._require_operational_symbol(symbol)
        rules = self._session.scalars(select(AlertRule).order_by(AlertRule.rule_code)).all()
        return tuple(self._state(rule, normalized) for rule in rules)

    def set_product_enabled(
        self,
        rule_code: str,
        symbol: str,
        enabled: bool,
    ) -> ProductAlertRuleState:
        normalized = self._require_operational_symbol(symbol)
        rule = self._rule_by_code(rule_code)
        scope = set(rule.scope_products or [])
        if enabled:
            scope.add(normalized)
        else:
            scope.discard(normalized)
        rule.scope_products = sorted(scope)
        self._session.commit()
        return self._state(rule, normalized)

    def create_event(self, request: AlertEventCreate) -> AlertEvent | None:
        symbol = self._require_operational_symbol(request.symbol)
        rule = self._session.get(AlertRule, request.rule_id)
        if rule is None:
            raise AlertRuleNotFoundError()
        frequency = request.frequency.strip()
        if frequency != rule.frequency:
            raise AlertConsistencyError()
        contract = normalize_contract_for_symbol(symbol, request.contract)
        if contract is None:
            raise AlertConsistencyError()
        observations = _normalize_observations(request.observation_types)
        for value in (request.bar_end, request.detected_at, request.notified_at):
            _require_aware(value)

        event = AlertEvent(
            rule_id=rule.id,
            symbol=symbol,
            contract=contract,
            frequency=frequency,
            bar_end=request.bar_end,
            observation_types=list(observations),
            detected_at=request.detected_at,
            notified_at=request.notified_at,
        )
        self._session.add(event)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            existing = self._event_by_identity(
                rule_id=rule.id,
                symbol=symbol,
                frequency=frequency,
                bar_end=request.bar_end,
            )
            if (
                existing is not None
                and existing.contract == contract
                and tuple(existing.observation_types) == observations
            ):
                return None
            raise AlertConsistencyError() from None
        self._session.refresh(event)
        return event

    def list_events(
        self,
        *,
        symbol: str,
        rule_code: str,
        start: datetime,
        end: datetime,
    ) -> tuple[AlertEvent, ...]:
        normalized = self._require_operational_symbol(symbol)
        _require_aware(start)
        _require_aware(end)
        if start >= end:
            raise AlertScopeError("ALERT_EVENT_RANGE_INVALID")
        rule = self._rule_by_code(rule_code)
        statement = (
            select(AlertEvent)
            .where(
                AlertEvent.rule_id == rule.id,
                AlertEvent.symbol == normalized,
                AlertEvent.bar_end >= start,
                AlertEvent.bar_end <= end,
            )
            .order_by(AlertEvent.bar_end)
        )
        return tuple(self._session.scalars(statement).all())

    def _rule_by_code(self, rule_code: str) -> AlertRule:
        normalized = str(rule_code or "").strip()
        rule = self._session.scalar(
            select(AlertRule).where(AlertRule.rule_code == normalized)
        )
        if rule is None:
            raise AlertRuleNotFoundError()
        return rule

    def _event_by_identity(
        self,
        *,
        rule_id: int,
        symbol: str,
        frequency: str,
        bar_end: datetime,
    ) -> AlertEvent | None:
        return self._session.scalar(
            select(AlertEvent).where(
                AlertEvent.rule_id == rule_id,
                AlertEvent.symbol == symbol,
                AlertEvent.frequency == frequency,
                AlertEvent.bar_end == bar_end,
            )
        )

    def _require_operational_symbol(self, symbol: str) -> str:
        normalized = normalize_symbol(symbol)
        if not normalized or normalized not in self._operational_products:
            raise AlertScopeError("ALERT_SYMBOL_NOT_OPERATIONAL")
        return normalized

    @staticmethod
    def _state(rule: AlertRule, symbol: str) -> ProductAlertRuleState:
        return ProductAlertRuleState(
            rule_code=rule.rule_code,
            display_name=_rule_display_name(rule.rule_code),
            indicator_code=rule.indicator_code,
            series_kind="actual_dominant",
            frequency=rule.frequency,
            enabled_for_product=symbol in set(rule.scope_products or []),
        )


def _normalize_observations(values: tuple[str, ...]) -> tuple[str, ...]:
    requested = set(values)
    if not requested or not requested.issubset({"buy", "sell"}):
        raise AlertScopeError("ALERT_OBSERVATION_TYPES_INVALID")
    return tuple(item for item in ("buy", "sell") if item in requested)


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AlertScopeError("ALERT_TIMEZONE_REQUIRED")


def _rule_display_name(rule_code: str) -> str:
    if rule_code == "htdy_original_15m":
        return "火天大有"
    raise AlertRuleNotFoundError()
