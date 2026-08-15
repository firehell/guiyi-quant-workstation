"""Alert V2 rule scope and current-trading-day event read model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.alerts.models import AlertEvent, AlertRule
from app.alerts.registry import (
    AlertRuleDefinition,
    AlertRuleKind,
    alert_rule_definitions,
    get_alert_rule_definition,
)
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
    kind: str
    input_frequencies: tuple[str, ...]
    enabled_for_product: bool


@dataclass(frozen=True, slots=True)
class AlertEventCreate:
    rule_id: int
    symbol: str
    contract: str
    trading_day: date
    frequency: str
    bar_end: datetime
    result_codes: tuple[str, ...]
    lower_tf_confirmation: bool
    detected_at: datetime
    notification_attempted_at: datetime


class AlertService:
    """Manage server-side rule scope and immutable AlertEvent facts."""

    def __init__(
        self, session: Session, *, operational_products: tuple[str, ...]
    ) -> None:
        self._session = session
        self._operational_products = frozenset(
            normalize_symbol(item) for item in operational_products
        )

    def product_rules(self, symbol: str) -> tuple[ProductAlertRuleState, ...]:
        normalized = self._require_operational_symbol(symbol)
        rules = self._session.scalars(
            select(AlertRule).order_by(AlertRule.rule_code)
        ).all()
        return tuple(self._state(rule, normalized) for rule in rules)

    def set_product_enabled(
        self,
        rule_code: str,
        symbol: str,
        enabled: bool,
    ) -> ProductAlertRuleState:
        normalized = self._require_operational_symbol(symbol)
        rule = self._rule_by_code(rule_code, for_update=True)
        scope = set(rule.scope_products or [])
        if enabled:
            scope.add(normalized)
        else:
            scope.discard(normalized)
        rule.scope_products = sorted(scope)
        try:
            self._session.commit()
            self._session.refresh(rule)
        except SQLAlchemyError:
            self._session.rollback()
            raise AlertScopeError("ALERT_SCOPE_PERSIST_FAILED") from None
        return self._state(rule, normalized)

    def create_event(self, request: AlertEventCreate) -> AlertEvent | None:
        symbol = self._require_operational_symbol(request.symbol)
        rule = self._session.get(AlertRule, request.rule_id)
        if rule is None:
            raise AlertRuleNotFoundError()
        definition = _definition(rule.rule_code)
        frequency = request.frequency.strip()
        if frequency not in definition.input_frequencies:
            raise AlertConsistencyError()
        contract = normalize_contract_for_symbol(symbol, request.contract)
        if contract is None:
            raise AlertConsistencyError()
        if not isinstance(request.trading_day, date) or isinstance(
            request.trading_day, datetime
        ):
            raise AlertScopeError("ALERT_TRADING_DAY_REQUIRED")
        result_codes = _normalize_result_codes(request.result_codes)
        for value in (
            request.bar_end,
            request.detected_at,
            request.notification_attempted_at,
        ):
            _require_aware(value)

        event = AlertEvent(
            rule_id=rule.id,
            symbol=symbol,
            contract=contract,
            trading_day=request.trading_day,
            frequency=frequency,
            bar_end=request.bar_end,
            result_codes=list(result_codes),
            lower_tf_confirmation=request.lower_tf_confirmation,
            detected_at=request.detected_at,
            notification_attempted_at=request.notification_attempted_at,
        )
        self._session.add(event)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            existing = self._event_by_identity(
                rule_id=rule.id,
                symbol=symbol,
                bar_end=request.bar_end,
            )
            if (
                existing is not None
                and existing.contract == contract
                and existing.frequency == frequency
                and existing.trading_day == request.trading_day
                and tuple(existing.result_codes) == result_codes
                and existing.lower_tf_confirmation is request.lower_tf_confirmation
            ):
                return None
            raise AlertConsistencyError() from None
        self._session.refresh(event)
        return event

    def list_current_formal_signal_events(
        self,
        *,
        trading_day: date,
    ) -> tuple[AlertEvent, ...]:
        formal_rule_codes = tuple(
            definition.rule_code
            for definition in alert_rule_definitions()
            if definition.kind is AlertRuleKind.FORMAL_SIGNAL
        )
        statement = (
            select(AlertEvent)
            .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
            .where(
                AlertRule.rule_code.in_(formal_rule_codes),
                AlertEvent.trading_day == trading_day,
            )
            .order_by(AlertEvent.bar_end.desc())
        )
        return tuple(self._session.scalars(statement).all())

    def list_current_product_events(
        self,
        *,
        symbol: str,
        trading_day: date,
    ) -> tuple[AlertEvent, ...]:
        normalized = self._require_operational_symbol(symbol)
        registered_rule_codes = tuple(
            definition.rule_code for definition in alert_rule_definitions()
        )
        statement = (
            select(AlertEvent)
            .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
            .where(
                AlertRule.rule_code.in_(registered_rule_codes),
                AlertEvent.symbol == normalized,
                AlertEvent.trading_day == trading_day,
            )
            .order_by(AlertEvent.bar_end.desc())
        )
        return tuple(self._session.scalars(statement).all())

    def _rule_by_code(
        self,
        rule_code: str,
        *,
        for_update: bool = False,
    ) -> AlertRule:
        normalized = str(rule_code or "").strip()
        _definition(normalized)
        statement = select(AlertRule).where(AlertRule.rule_code == normalized)
        if for_update:
            statement = statement.with_for_update()
        rule = self._session.scalar(statement)
        if rule is None:
            raise AlertRuleNotFoundError()
        return rule

    def _event_by_identity(
        self,
        *,
        rule_id: int,
        symbol: str,
        bar_end: datetime,
    ) -> AlertEvent | None:
        return self._session.scalar(
            select(AlertEvent).where(
                AlertEvent.rule_id == rule_id,
                AlertEvent.symbol == symbol,
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
        definition = _definition(rule.rule_code)
        return ProductAlertRuleState(
            rule_code=definition.rule_code,
            display_name=definition.display_name,
            kind=definition.kind.value,
            input_frequencies=definition.input_frequencies,
            enabled_for_product=symbol in set(rule.scope_products or []),
        )


def _definition(rule_code: str) -> AlertRuleDefinition:
    try:
        return get_alert_rule_definition(rule_code)
    except KeyError:
        raise AlertRuleNotFoundError() from None


def _normalize_result_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    requested = set(values)
    if not requested or not requested.issubset({"buy", "sell"}):
        raise AlertScopeError("ALERT_RESULT_CODES_INVALID")
    return tuple(item for item in ("buy", "sell") if item in requested)


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AlertScopeError("ALERT_TIMEZONE_REQUIRED")
