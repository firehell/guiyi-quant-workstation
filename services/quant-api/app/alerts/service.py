"""Alert V2 rule scope and current-trading-day event read model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

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
from app.alerts.strategy_payload import (
    StrategyPayloadError,
    SubingStrategyActionPayload,
    parse_subing_strategy_payload,
    validate_subing_strategy_event_facts,
)
from app.market_data.domain import normalize_contract_for_symbol
from app.market_data.product_retirement import normalize_symbol


class AlertConsistencyError(RuntimeError):
    """An existing event disagrees with the same unique event identity."""

    code = "ALERT_EVENT_CONSISTENCY_ERROR"

    def __init__(self) -> None:
        super().__init__(self.code)


class AlertEventPersistenceError(RuntimeError):
    """An AlertEvent write failed without an idempotent identity readback."""

    code = "ALERT_EVENT_PERSIST_FAILED"

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
    enabled_frequencies: tuple[str, ...]
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
    action_id: str | None
    strategy_payload: SubingStrategyActionPayload | None
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
        definition = _definition(rule.rule_code)
        if definition.kind is not AlertRuleKind.STRATEGY_ACTION:
            raise AlertScopeError("ALERT_SCOPE_MODE_INVALID")
        self._require_product_scope_authority(rule, definition)
        scope = set(rule.scope_products or [])
        if enabled:
            scope.add(normalized)
        else:
            scope.discard(normalized)
        rule.scope_products = sorted(scope)
        return self._commit_scope(rule, normalized)

    def set_product_frequency_enabled(
        self,
        rule_code: str,
        symbol: str,
        frequency: str,
        enabled: bool,
    ) -> ProductAlertRuleState:
        normalized_symbol = self._require_operational_symbol(symbol)
        rule = self._rule_by_code(rule_code, for_update=True)
        definition = _definition(rule.rule_code)
        if definition.kind is not AlertRuleKind.INDICATOR_OBSERVATION:
            raise AlertScopeError("ALERT_SCOPE_MODE_INVALID")
        normalized_frequency = str(frequency).strip()
        if normalized_frequency not in definition.input_frequencies:
            raise AlertScopeError("ALERT_SCOPE_FREQUENCY_INVALID")
        scope = self._normalized_frequency_scope(rule, definition)
        current = set(scope.get(normalized_symbol, ()))
        if enabled:
            current.add(normalized_frequency)
        else:
            current.discard(normalized_frequency)
        if current:
            scope[normalized_symbol] = tuple(
                value for value in definition.input_frequencies if value in current
            )
        else:
            scope.pop(normalized_symbol, None)
        rule.scope_product_frequencies = {
            key: list(values) for key, values in sorted(scope.items())
        }
        return self._commit_scope(rule, normalized_symbol)

    def rule_allows_event(
        self,
        rule: AlertRule,
        *,
        symbol: str,
        frequency: str,
    ) -> bool:
        normalized_symbol = self._require_operational_symbol(symbol)
        definition = _definition(rule.rule_code)
        if frequency not in definition.input_frequencies:
            return False
        if definition.kind is AlertRuleKind.INDICATOR_OBSERVATION:
            scope = self._normalized_frequency_scope(rule, definition)
            return frequency in scope.get(normalized_symbol, ())
        if frequency != "15m":
            return False
        self._require_product_scope_authority(rule, definition)
        return normalized_symbol in set(rule.scope_products or [])

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
        try:
            result_codes = _normalize_result_codes(definition, request.result_codes)
        except AlertScopeError:
            if definition.kind is AlertRuleKind.STRATEGY_ACTION:
                raise AlertConsistencyError() from None
            raise
        for value in (
            request.bar_end,
            request.detected_at,
            request.notification_attempted_at,
        ):
            _require_aware(value)

        strategy_payload_json: dict[str, object] | None
        if definition.kind is AlertRuleKind.INDICATOR_OBSERVATION:
            if request.action_id is not None or request.strategy_payload is not None:
                raise AlertConsistencyError()
            strategy_payload_json = None
        else:
            if (
                not isinstance(request.action_id, str)
                or not request.action_id
                or not isinstance(request.strategy_payload, SubingStrategyActionPayload)
            ):
                raise AlertConsistencyError()
            try:
                canonical_payload = parse_subing_strategy_payload(
                    request.strategy_payload.to_json()
                )
                validate_subing_strategy_event_facts(
                    canonical_payload,
                    action_id=request.action_id,
                    symbol=symbol,
                    contract=contract,
                    trading_day=request.trading_day,
                    frequency=frequency,
                    bar_end=request.bar_end,
                    result_codes=result_codes,
                )
            except StrategyPayloadError:
                raise AlertConsistencyError() from None
            strategy_payload_json = canonical_payload.to_json()

        existing = self._event_by_identity(
            definition=definition,
            rule_id=rule.id,
            symbol=symbol,
            frequency=frequency,
            bar_end=request.bar_end,
            action_id=request.action_id,
        )
        if existing is not None:
            if self._event_matches(
                existing,
                rule_id=rule.id,
                symbol=symbol,
                bar_end=request.bar_end,
                contract=contract,
                trading_day=request.trading_day,
                frequency=frequency,
                result_codes=result_codes,
                action_id=request.action_id,
                strategy_payload=strategy_payload_json,
            ):
                return None
            raise AlertConsistencyError()

        event = AlertEvent(
            rule_id=rule.id,
            symbol=symbol,
            contract=contract,
            trading_day=request.trading_day,
            frequency=frequency,
            bar_end=request.bar_end,
            result_codes=list(result_codes),
            action_id=request.action_id,
            strategy_payload=strategy_payload_json,
            detected_at=request.detected_at,
            notification_attempted_at=request.notification_attempted_at,
        )
        self._session.add(event)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            if definition.kind is AlertRuleKind.STRATEGY_ACTION:
                try:
                    existing = self._event_by_identity(
                        definition=definition,
                        rule_id=rule.id,
                        symbol=symbol,
                        frequency=frequency,
                        bar_end=request.bar_end,
                        action_id=request.action_id,
                    )
                except SQLAlchemyError:
                    self._session.rollback()
                    raise AlertEventPersistenceError() from None
                if existing is not None:
                    matches = self._event_matches(
                        existing,
                        rule_id=rule.id,
                        symbol=symbol,
                        bar_end=request.bar_end,
                        contract=contract,
                        trading_day=request.trading_day,
                        frequency=frequency,
                        result_codes=result_codes,
                        action_id=request.action_id,
                        strategy_payload=strategy_payload_json,
                    )
                    self._session.rollback()
                    if matches:
                        return None
                    raise AlertConsistencyError() from None
            self._session.rollback()
            raise AlertEventPersistenceError() from None
        except SQLAlchemyError:
            self._session.rollback()
            raise AlertEventPersistenceError() from None
        self._session.refresh(event)
        return event

    def list_current_strategy_action_events(
        self,
        *,
        trading_day: date,
    ) -> tuple[AlertEvent, ...]:
        strategy_rule_codes = tuple(
            definition.rule_code
            for definition in alert_rule_definitions()
            if definition.kind is AlertRuleKind.STRATEGY_ACTION
        )
        statement = (
            select(AlertEvent)
            .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
            .where(
                AlertRule.rule_code.in_(strategy_rule_codes),
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
        definition: AlertRuleDefinition,
        rule_id: int,
        symbol: str,
        frequency: str,
        bar_end: datetime,
        action_id: str | None,
    ) -> AlertEvent | None:
        if definition.kind is AlertRuleKind.STRATEGY_ACTION:
            if action_id is None:
                return None
            return self._session.scalar(
                select(AlertEvent).where(AlertEvent.action_id == action_id)
            )
        statement = select(AlertEvent).where(
            AlertEvent.rule_id == rule_id,
            AlertEvent.symbol == symbol,
            AlertEvent.bar_end == bar_end,
        )
        statement = statement.where(AlertEvent.frequency == frequency)
        return self._session.scalar(statement)

    @staticmethod
    def _event_matches(
        event: AlertEvent,
        *,
        rule_id: int,
        symbol: str,
        bar_end: datetime,
        contract: str,
        trading_day: date,
        frequency: str,
        result_codes: tuple[str, ...],
        action_id: str | None,
        strategy_payload: dict[str, object] | None,
    ) -> bool:
        return (
            event.rule_id == rule_id
            and event.symbol == symbol
            and _same_utc_instant(event.bar_end, bar_end)
            and event.contract == contract
            and event.frequency == frequency
            and event.trading_day == trading_day
            and tuple(event.result_codes) == result_codes
            and event.action_id == action_id
            and event.strategy_payload == strategy_payload
        )

    def _require_operational_symbol(self, symbol: str) -> str:
        normalized = normalize_symbol(symbol)
        if not normalized or normalized not in self._operational_products:
            raise AlertScopeError("ALERT_SYMBOL_NOT_OPERATIONAL")
        return normalized

    def _state(self, rule: AlertRule, symbol: str) -> ProductAlertRuleState:
        definition = _definition(rule.rule_code)
        if definition.kind is AlertRuleKind.INDICATOR_OBSERVATION:
            enabled_frequencies = self._normalized_frequency_scope(
                rule, definition
            ).get(symbol, ())
            enabled_for_product = bool(enabled_frequencies)
        else:
            self._require_product_scope_authority(rule, definition)
            enabled_frequencies = ()
            enabled_for_product = symbol in set(rule.scope_products or [])
        return ProductAlertRuleState(
            rule_code=definition.rule_code,
            display_name=definition.display_name,
            kind=definition.kind.value,
            input_frequencies=definition.input_frequencies,
            enabled_frequencies=enabled_frequencies,
            enabled_for_product=enabled_for_product,
        )

    def _normalized_frequency_scope(
        self,
        rule: AlertRule,
        definition: AlertRuleDefinition,
    ) -> dict[str, tuple[str, ...]]:
        if not isinstance(rule.scope_products, list) or rule.scope_products:
            raise AlertScopeError("ALERT_SCOPE_STATE_INVALID")
        stored_scope = rule.scope_product_frequencies
        if not isinstance(stored_scope, dict):
            raise AlertScopeError("ALERT_SCOPE_STATE_INVALID")

        normalized_scope: dict[str, tuple[str, ...]] = {}
        for symbol, frequencies in stored_scope.items():
            if (
                not isinstance(symbol, str)
                or normalize_symbol(symbol) != symbol
                or symbol not in self._operational_products
                or not isinstance(frequencies, list)
                or not frequencies
                or any(
                    not isinstance(value, str)
                    or value not in definition.input_frequencies
                    for value in frequencies
                )
            ):
                raise AlertScopeError("ALERT_SCOPE_STATE_INVALID")
            normalized_scope[symbol] = tuple(
                value
                for value in definition.input_frequencies
                if value in set(frequencies)
            )
        return normalized_scope

    def _require_product_scope_authority(
        self,
        rule: AlertRule,
        definition: AlertRuleDefinition,
    ) -> None:
        if not isinstance(rule.scope_product_frequencies, dict) or (
            rule.scope_product_frequencies
        ):
            raise AlertScopeError("ALERT_SCOPE_STATE_INVALID")
        if not isinstance(rule.scope_products, list):
            raise AlertScopeError("ALERT_SCOPE_STATE_INVALID")
        for symbol in rule.scope_products:
            if (
                not isinstance(symbol, str)
                or normalize_symbol(symbol) != symbol
                or symbol not in self._operational_products
            ):
                raise AlertScopeError("ALERT_SCOPE_STATE_INVALID")

    def _commit_scope(
        self,
        rule: AlertRule,
        symbol: str,
    ) -> ProductAlertRuleState:
        try:
            self._session.commit()
            self._session.refresh(rule)
        except SQLAlchemyError:
            self._session.rollback()
            raise AlertScopeError("ALERT_SCOPE_PERSIST_FAILED") from None
        return self._state(rule, symbol)


def _definition(rule_code: str) -> AlertRuleDefinition:
    try:
        return get_alert_rule_definition(rule_code)
    except KeyError:
        raise AlertRuleNotFoundError() from None


def _normalize_result_codes(
    definition: AlertRuleDefinition,
    values: tuple[str, ...],
) -> tuple[str, ...]:
    if type(values) is not tuple or any(type(value) is not str for value in values):
        raise AlertScopeError("ALERT_RESULT_CODES_INVALID")
    requested = set(values)
    if len(requested) != len(values):
        raise AlertScopeError("ALERT_RESULT_CODES_INVALID")
    if definition.kind is AlertRuleKind.INDICATOR_OBSERVATION:
        if not requested or not requested.issubset({"buy", "sell"}):
            raise AlertScopeError("ALERT_RESULT_CODES_INVALID")
        return tuple(item for item in ("buy", "sell") if item in requested)
    if len(values) != 1 or values[0] not in {
        "open_long",
        "open_short",
        "close_long",
        "close_short",
    }:
        raise AlertScopeError("ALERT_RESULT_CODES_INVALID")
    return values


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AlertScopeError("ALERT_TIMEZONE_REQUIRED")


def _same_utc_instant(stored: datetime, requested: datetime) -> bool:
    stored_utc = (
        stored.replace(tzinfo=UTC)
        if stored.tzinfo is None or stored.utcoffset() is None
        else stored.astimezone(UTC)
    )
    return stored_utc == requested.astimezone(UTC)
