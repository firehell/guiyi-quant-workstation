"""HTDY Alert scope and immutable first-seen Event service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.alerts.models import AlertEvent, AlertRule
from app.alerts.registry import (
    AlertRuleDefinition,
    get_alert_rule_definition,
)
from app.market_data.domain import normalize_contract_for_symbol
from app.market_data.product_retirement import normalize_symbol


class AlertConsistencyError(RuntimeError):
    code = "ALERT_EVENT_CONSISTENCY_ERROR"

    def __init__(self) -> None:
        super().__init__(self.code)


class AlertEventPersistenceError(RuntimeError):
    code = "ALERT_EVENT_PERSIST_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class AlertRuleNotFoundError(LookupError):
    code = "ALERT_RULE_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__(self.code)


class AlertScopeError(ValueError):
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
    detected_at: datetime
    notification_attempted_at: datetime


class AlertService:
    def __init__(self, session: Session, *, operational_products: tuple[str, ...]) -> None:
        self._session = session
        self._operational_products = frozenset(
            normalize_symbol(item) for item in operational_products
        )

    def product_rules(self, symbol: str) -> tuple[ProductAlertRuleState, ...]:
        normalized = self._require_operational_symbol(symbol)
        rules = self._session.scalars(select(AlertRule).order_by(AlertRule.rule_code)).all()
        return tuple(self._state(rule, normalized) for rule in rules)

    def set_product_frequency_enabled(
        self,
        rule_code: str,
        symbol: str,
        frequency: str,
        enabled: bool,
    ) -> ProductAlertRuleState:
        normalized_symbol = self._require_operational_symbol(symbol)
        rule = self._rule_by_code(rule_code, for_update=True)
        if not rule.enabled:
            raise AlertScopeError("ALERT_SCOPE_RULE_DISABLED")
        definition = _definition(rule.rule_code)
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
        try:
            self._session.commit()
            self._session.refresh(rule)
        except SQLAlchemyError:
            self._session.rollback()
            raise AlertScopeError("ALERT_SCOPE_PERSIST_FAILED") from None
        return self._state(rule, normalized_symbol)

    def rule_allows_event(self, rule: AlertRule, *, symbol: str, frequency: str) -> bool:
        normalized = self._require_operational_symbol(symbol)
        definition = _definition(rule.rule_code)
        if frequency not in definition.input_frequencies:
            return False
        return frequency in self._normalized_frequency_scope(rule, definition).get(
            normalized, ()
        )

    def create_first_seen_observation_event(
        self, request: AlertEventCreate
    ) -> AlertEvent | None:
        return self._create(request, first_seen=True)

    def create_event(self, request: AlertEventCreate) -> AlertEvent | None:
        return self._create(request, first_seen=False)

    def _create(self, request: AlertEventCreate, *, first_seen: bool) -> AlertEvent | None:
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
        existing = self._event_by_identity(
            rule_id=rule.id,
            symbol=symbol,
            frequency=frequency,
            bar_end=request.bar_end,
        )
        if existing is not None:
            if (
                first_seen
                and _valid_first_seen_event(
                    existing,
                    rule_id=rule.id,
                    symbol=symbol,
                    frequency=frequency,
                    bar_end=request.bar_end,
                )
            ) or (
                not first_seen
                and _event_matches(
                    existing,
                    rule_id=rule.id,
                    symbol=symbol,
                    contract=contract,
                    trading_day=request.trading_day,
                    frequency=frequency,
                    bar_end=request.bar_end,
                    result_codes=result_codes,
                )
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
            detected_at=request.detected_at,
            notification_attempted_at=request.notification_attempted_at,
        )
        self._session.add(event)
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            try:
                existing = self._event_by_identity(
                    rule_id=rule.id,
                    symbol=symbol,
                    frequency=frequency,
                    bar_end=request.bar_end,
                )
            except SQLAlchemyError:
                self._session.rollback()
                raise AlertEventPersistenceError() from None
            if existing is not None and (
                (
                    first_seen
                    and _valid_first_seen_event(
                        existing,
                        rule_id=rule.id,
                        symbol=symbol,
                        frequency=frequency,
                        bar_end=request.bar_end,
                    )
                )
                or (
                    not first_seen
                    and _event_matches(
                        existing,
                        rule_id=rule.id,
                        symbol=symbol,
                        contract=contract,
                        trading_day=request.trading_day,
                        frequency=frequency,
                        bar_end=request.bar_end,
                        result_codes=result_codes,
                    )
                )
            ):
                return None
            raise AlertEventPersistenceError() from None
        except SQLAlchemyError:
            self._session.rollback()
            raise AlertEventPersistenceError() from None
        self._session.refresh(event)
        return event

    def list_current_product_events(
        self, *, symbol: str, trading_day: date
    ) -> tuple[AlertEvent, ...]:
        normalized = self._require_operational_symbol(symbol)
        statement = (
            select(AlertEvent)
            .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
            .where(
                AlertEvent.symbol == normalized,
                AlertEvent.trading_day == trading_day,
            )
            .order_by(
                AlertEvent.detected_at.desc(),
                AlertEvent.bar_end.desc(),
                AlertEvent.id.desc(),
            )
        )
        return tuple(self._session.scalars(statement).all())

    def list_current_events(
        self, *, trading_day: date, limit: int | None
    ) -> tuple[AlertEvent, ...]:
        """Read every current-day Event so API serialization can fail closed."""

        statement = (
            select(AlertEvent)
            .join(AlertRule, AlertEvent.rule_id == AlertRule.id)
            .where(
                AlertEvent.trading_day == trading_day,
            )
            .order_by(
                AlertEvent.detected_at.desc(),
                AlertEvent.bar_end.desc(),
                AlertEvent.id.desc(),
            )
        )
        if limit is not None:
            statement = statement.limit(limit)
        return tuple(self._session.scalars(statement).all())

    def _rule_by_code(self, rule_code: str, *, for_update: bool = False) -> AlertRule:
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
        self, *, rule_id: int, symbol: str, frequency: str, bar_end: datetime
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

    def _state(self, rule: AlertRule, symbol: str) -> ProductAlertRuleState:
        definition = _definition(rule.rule_code)
        enabled_frequencies = self._normalized_frequency_scope(rule, definition).get(
            symbol, ()
        )
        return ProductAlertRuleState(
            rule_code=definition.rule_code,
            display_name=definition.display_name,
            kind=definition.kind.value,
            input_frequencies=definition.input_frequencies,
            enabled_frequencies=enabled_frequencies,
            enabled_for_product=bool(enabled_frequencies),
        )

    def _normalized_frequency_scope(
        self, rule: AlertRule, definition: AlertRuleDefinition
    ) -> dict[str, tuple[str, ...]]:
        stored = rule.scope_product_frequencies
        if not isinstance(stored, dict):
            raise AlertScopeError("ALERT_SCOPE_STATE_INVALID")
        normalized: dict[str, tuple[str, ...]] = {}
        for symbol, frequencies in stored.items():
            if (
                not isinstance(symbol, str)
                or normalize_symbol(symbol) != symbol
                or symbol not in self._operational_products
                or not isinstance(frequencies, list)
                or not frequencies
                or any(value not in definition.input_frequencies for value in frequencies)
            ):
                raise AlertScopeError("ALERT_SCOPE_STATE_INVALID")
            normalized[symbol] = tuple(
                value for value in definition.input_frequencies if value in set(frequencies)
            )
        return normalized


def _definition(rule_code: str) -> AlertRuleDefinition:
    try:
        return get_alert_rule_definition(rule_code)
    except KeyError:
        raise AlertRuleNotFoundError() from None


def _normalize_result_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    if not values or len(values) > 2 or len(set(values)) != len(values):
        raise AlertScopeError("ALERT_RESULT_CODES_INVALID")
    if any(value not in {"buy", "sell"} for value in values):
        raise AlertScopeError("ALERT_RESULT_CODES_INVALID")
    return tuple(value for value in ("buy", "sell") if value in values)


def _event_matches(
    event: AlertEvent,
    *,
    rule_id: int,
    symbol: str,
    contract: str,
    trading_day: date,
    frequency: str,
    bar_end: datetime,
    result_codes: tuple[str, ...],
) -> bool:
    return (
        event.rule_id == rule_id
        and event.symbol == symbol
        and event.contract == contract
        and event.trading_day == trading_day
        and event.frequency == frequency
        and _same_utc_instant(event.bar_end, bar_end)
        and tuple(event.result_codes) == result_codes
    )


def _valid_first_seen_event(
    event: AlertEvent,
    *,
    rule_id: int,
    symbol: str,
    frequency: str,
    bar_end: datetime,
) -> bool:
    try:
        result_codes = _normalize_result_codes(tuple(event.result_codes))
    except (AlertScopeError, TypeError):
        return False
    return (
        event.rule_id == rule_id
        and event.symbol == symbol
        and event.frequency == frequency
        and _same_utc_instant(event.bar_end, bar_end)
        and normalize_contract_for_symbol(symbol, event.contract) == event.contract
        and isinstance(event.trading_day, date)
        and not isinstance(event.trading_day, datetime)
        and tuple(event.result_codes) == result_codes
    )


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AlertScopeError("ALERT_TIMEZONE_REQUIRED")


def _same_utc_instant(left: datetime, right: datetime) -> bool:
    left_utc = left.replace(tzinfo=UTC) if left.tzinfo is None else left.astimezone(UTC)
    right_utc = right.replace(tzinfo=UTC) if right.tzinfo is None else right.astimezone(UTC)
    return left_utc == right_utc
