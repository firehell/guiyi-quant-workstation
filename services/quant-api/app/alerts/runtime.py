"""Alert V2 的单前台、无 replay 规则编排循环。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, DecimalException
import json
import logging
from typing import Protocol, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.evaluators import AlertEvaluation, AlertEvaluator
from app.alerts.models import AlertRule
from app.alerts.notification import (
    AlertNotificationMessage,
    AlertNotificationSender,
    ProviderAcceptance,
)
from app.alerts.registry import HTDY_RULE, SUBING_RULE, get_alert_rule_definition
from app.alerts.service import AlertEventCreate, AlertScopeError, AlertService
from app.market_data.aggregation import SessionWindow, bucket_window_for_bar
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    INTRADAY_FREQUENCIES,
    SeriesKind,
    SeriesPageQuery,
    normalize_contract_for_symbol,
)
from app.market_data.live_market import LIVE_SESSION_END_ARRIVAL_GRACE
from app.market_data.market_read_service import MarketReadService, MarketReadWindow
from app.market_data.product_retirement import normalize_symbol
from app.market_data.product_taxonomy import ProductTaxonomyEntry
from app.market_data.session_clock import (
    SessionClockError,
    resolved_session_windows_for_trading_day,
)
from app.market_data.subing_read_service import SubingReadRequest, SubingReadService
from app.market_data.subing_research import (
    SubingDirection,
    SubingFactorStatus,
    SubingSignalStatus,
)
from app.models import Instrument, TradingCalendar


_LOGGER = logging.getLogger(__name__)
_LIVE_BAR_PATTERN = "live:bar:*:*"
_MARKET_STATE_PATTERN = "market:state"
_CANONICAL_ALERT_FREQUENCIES = (BarFrequency.D1, BarFrequency.W1)
_HEARTBEAT_INTERVAL = timedelta(seconds=10)
_HEARTBEAT_TTL_SECONDS = 30
PROCESSING_FAILURE = "processing_failed"
NOTIFICATION_PREPARATION_FAILURE = "notification_preparation_failed"
NOTIFICATION_TRANSPORT_FAILURE = "notification_transport_failed"
NOTIFICATION_ACCEPTANCE_INVALID = "notification_acceptance_invalid"


class AlertMessageSource(Protocol):
    def subscribe(self, *patterns: str) -> None: ...
    def get_message(self, *, timeout_seconds: float) -> tuple[object, object] | None: ...
    def close(self) -> None: ...


class AlertHeartbeatStore(Protocol):
    def write(self, payload: dict[str, object], *, ttl_seconds: int) -> None: ...


class AlertRuntimeStatusStore(Protocol):
    def read(self) -> dict[str, object]: ...
    def write(self, payload: dict[str, object]) -> None: ...


AlertSessionFactory = Callable[[], AbstractContextManager[Session]]
AlertMarketReadFactory = Callable[[Session], MarketReadService]
AlertSubingReadFactory = Callable[[Session], SubingReadService]


@dataclass(frozen=True, slots=True)
class _RuleResult:
    contract: str
    frequency: str
    result_codes: tuple[str, ...]
    lower_tf_confirmation: bool


@dataclass(frozen=True, slots=True)
class _LiveBarTrigger:
    symbol: str
    frequency: BarFrequency
    bar: CanonicalBar


@dataclass(frozen=True, slots=True)
class _CanonicalUpdatedTrigger:
    trading_day: date


@dataclass(frozen=True, slots=True)
class _PreparedEvent:
    event_created: bool
    message: AlertNotificationMessage | None
    notification_error_type: str | None


def _persist_event_and_prepare_notification(
    service: AlertService,
    *,
    taxonomy: Mapping[str, ProductTaxonomyEntry],
    rule: AlertRule,
    symbol: str,
    trading_day: date,
    bar_end: datetime,
    result: _RuleResult,
    processing_now: datetime,
) -> _PreparedEvent:
    created = service.create_event(
        AlertEventCreate(
            rule_id=rule.id,
            symbol=symbol,
            contract=result.contract,
            trading_day=trading_day,
            frequency=result.frequency,
            bar_end=bar_end,
            result_codes=result.result_codes,
            lower_tf_confirmation=result.lower_tf_confirmation,
            detected_at=processing_now,
            notification_attempted_at=processing_now,
        )
    )
    if created is None:
        return _PreparedEvent(False, None, None)
    taxonomy_entry = taxonomy.get(symbol)
    if taxonomy_entry is None:
        _LOGGER.warning("ALERT_PRODUCT_NAME_UNAVAILABLE")
        return _PreparedEvent(
            True,
            None,
            NOTIFICATION_PREPARATION_FAILURE,
        )
    return _PreparedEvent(
        True,
        AlertNotificationMessage(
            rule_code=rule.rule_code,
            symbol=symbol,
            product_name=taxonomy_entry.name,
            contract=result.contract,
            frequency=result.frequency,
            bar_end=bar_end,
            result_codes=result.result_codes,
            lower_tf_confirmation=result.lower_tf_confirmation,
        ),
        None,
    )


class AlertRuntime:
    def __init__(
        self,
        *,
        session_factory: AlertSessionFactory,
        market_read_factory: AlertMarketReadFactory,
        subing_read_factory: AlertSubingReadFactory,
        htdy_evaluator: AlertEvaluator,
        sender: AlertNotificationSender,
        operational_products: tuple[str, ...],
        taxonomy: Mapping[str, ProductTaxonomyEntry],
        message_source: AlertMessageSource | None = None,
        heartbeat_store: AlertHeartbeatStore | None = None,
        runtime_status_store: AlertRuntimeStatusStore | None = None,
        clock: Callable[[], datetime] | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._market_read_factory = market_read_factory
        self._subing_read_factory = subing_read_factory
        self._htdy_evaluator = htdy_evaluator
        self._sender = sender
        self._operational_products = frozenset(
            normalize_symbol(symbol) for symbol in operational_products
        )
        self._taxonomy = dict(taxonomy)
        self.message_source = message_source
        self.heartbeat_store = heartbeat_store
        self.runtime_status_store = runtime_status_store
        self._runtime_status: dict[str, object] | None = None
        self.clock = clock or (lambda: datetime.now(UTC))
        self.stop_requested = stop_requested or (lambda: False)

    def run_forever(self) -> None:
        """只消费启动后新到达的 completed 日内 Bar 与 Canonical state。"""
        if self.message_source is None or self.heartbeat_store is None:
            raise RuntimeError("ALERT_RUNTIME_TRANSPORT_UNAVAILABLE")
        self.message_source.subscribe(_LIVE_BAR_PATTERN, _MARKET_STATE_PATTERN)
        next_heartbeat = self._aware_now()
        try:
            while not self.stop_requested():
                now = self._aware_now()
                if now >= next_heartbeat:
                    self._write_heartbeat(now)
                    next_heartbeat = now + _HEARTBEAT_INTERVAL
                message = self.message_source.get_message(timeout_seconds=1.0)
                if message is not None:
                    self.process_message(*message)
        finally:
            self.message_source.close()

    def process_message(self, channel: object, payload: object) -> None:
        """处理单条强类型触发；Rule 故障隔离，Event 提交后只发送一次。"""
        trigger = _parse_live_bar_trigger(channel, payload)
        if trigger is None:
            canonical_trigger = _parse_canonical_updated_trigger(channel, payload)
            if canonical_trigger is not None:
                self._process_canonical_updated(canonical_trigger)
            return
        symbol = trigger.symbol
        event_frequency = trigger.frequency
        event_bar = trigger.bar
        if symbol not in self._operational_products:
            return
        try:
            processing_now = self._aware_now()
        except Exception:  # noqa: BLE001 - collapse clock detail
            _LOGGER.warning("ALERT_PROCESSING_FAILED")
            return

        messages: list[AlertNotificationMessage] = []
        event_count = 0
        notification_preparation_failures: list[str] = []
        processing_error_type: str | None = None
        fatal_processing_failure = False
        try:
            with self._session_factory() as session:
                try:
                    rules = session.scalars(
                        select(AlertRule)
                        .where(AlertRule.enabled.is_(True))
                        .order_by(AlertRule.rule_code)
                        .execution_options(populate_existing=True)
                    ).all()
                    service = AlertService(
                        session,
                        operational_products=tuple(
                            sorted(self._operational_products)
                        ),
                    )
                    for rule in rules:
                        try:
                            definition = get_alert_rule_definition(rule.rule_code)
                            if event_frequency.value not in definition.input_frequencies:
                                continue
                            if not service.rule_allows_event(
                                rule,
                                symbol=symbol,
                                frequency=event_frequency.value,
                            ):
                                continue
                            result = self._evaluate_rule(
                                session,
                                rule_code=definition.rule_code,
                                symbol=symbol,
                                event_frequency=event_frequency,
                                event_bar=event_bar,
                                processing_now=processing_now,
                            )
                            if result is None:
                                continue
                            prepared = _persist_event_and_prepare_notification(
                                service,
                                taxonomy=self._taxonomy,
                                rule=rule,
                                symbol=symbol,
                                trading_day=event_bar.trading_day,
                                bar_end=event_bar.bar_end,
                                result=result,
                                processing_now=processing_now,
                            )
                            if not prepared.event_created:
                                continue
                            event_count += 1
                            if prepared.notification_error_type is not None:
                                notification_preparation_failures.append(
                                    prepared.notification_error_type
                                )
                            if prepared.message is not None:
                                messages.append(prepared.message)
                        except Exception:  # noqa: BLE001 - isolate each fixed rule
                            if session.in_transaction():
                                session.rollback()
                            processing_error_type = PROCESSING_FAILURE
                            _LOGGER.warning("ALERT_RULE_PROCESSING_FAILED")
                finally:
                    if session.in_transaction():
                        session.rollback()
        except Exception:  # noqa: BLE001 - DB/session failure must not send
            processing_error_type = PROCESSING_FAILURE
            fatal_processing_failure = True
            _LOGGER.warning("ALERT_PROCESSING_FAILED")

        if event_count:
            self._update_runtime_status(last_event_at=_iso_timestamp(processing_now))
        for error_type in notification_preparation_failures:
            self._record_notification_failure(
                at=processing_now,
                error_type=error_type,
            )
        if processing_error_type is None:
            self._update_runtime_status(
                last_processed_bar_at=_iso_timestamp(event_bar.bar_end),
                last_processing_success_at=_iso_timestamp(processing_now),
                processing_error_type=None,
            )
        else:
            self._update_runtime_status(
                last_processed_bar_at=_iso_timestamp(event_bar.bar_end),
                last_processing_failure_at=_iso_timestamp(processing_now),
                processing_error_type=processing_error_type,
            )
            if fatal_processing_failure or not messages:
                return

        self._send_messages_once(messages, processing_now=processing_now)

    def _process_canonical_updated(
        self,
        trigger: _CanonicalUpdatedTrigger,
    ) -> None:
        try:
            processing_now = self._aware_now()
        except Exception:  # noqa: BLE001 - collapse clock detail
            _LOGGER.warning("ALERT_PROCESSING_FAILED")
            return

        messages: list[AlertNotificationMessage] = []
        event_count = 0
        notification_preparation_failures: list[str] = []
        processing_error_type: str | None = None
        fatal_processing_failure = False
        try:
            with self._session_factory() as session:
                try:
                    rules = session.scalars(
                        select(AlertRule)
                        .where(
                            AlertRule.enabled.is_(True),
                            AlertRule.rule_code == HTDY_RULE.rule_code,
                        )
                        .execution_options(populate_existing=True)
                    ).all()
                    service = AlertService(
                        session,
                        operational_products=tuple(
                            sorted(self._operational_products)
                        ),
                    )
                    for rule in rules:
                        try:
                            definition = get_alert_rule_definition(rule.rule_code)
                            pairs = tuple(
                                (symbol, frequency)
                                for symbol in sorted(self._operational_products)
                                for frequency in _CANONICAL_ALERT_FREQUENCIES
                                if frequency.value in definition.input_frequencies
                                and service.rule_allows_event(
                                    rule,
                                    symbol=symbol,
                                    frequency=frequency.value,
                                )
                            )
                        except Exception:  # noqa: BLE001 - invalid Rule Scope is isolated
                            if session.in_transaction():
                                session.rollback()
                            processing_error_type = PROCESSING_FAILURE
                            _LOGGER.warning("ALERT_RULE_PROCESSING_FAILED")
                            continue
                        if not pairs:
                            continue
                        market_read = self._market_read_factory(session)
                        for symbol, frequency in pairs:
                            stage = "market_read"
                            try:
                                window = market_read.latest_canonical_window(
                                    SeriesPageQuery(
                                        SeriesKind.ACTUAL_DOMINANT,
                                        symbol,
                                        frequency,
                                    ),
                                    trading_day=trigger.trading_day,
                                    limit=32,
                                )
                                stage = "window_validate"
                                if not _canonical_window_matches_trigger(
                                    window,
                                    symbol=symbol,
                                    frequency=frequency,
                                    trading_day=trigger.trading_day,
                                ):
                                    continue
                                stage = "evaluate"
                                evaluation = self._htdy_evaluator.evaluate(window)
                                if (
                                    not isinstance(evaluation, AlertEvaluation)
                                    or not evaluation.observation_types
                                ):
                                    continue
                                stage = "event_persist"
                                prepared = _persist_event_and_prepare_notification(
                                    service,
                                    taxonomy=self._taxonomy,
                                    rule=rule,
                                    symbol=symbol,
                                    trading_day=trigger.trading_day,
                                    bar_end=window.cutoff,
                                    result=_RuleResult(
                                        contract=window.contract,
                                        frequency=frequency.value,
                                        result_codes=evaluation.observation_types,
                                        lower_tf_confirmation=False,
                                    ),
                                    processing_now=processing_now,
                                )
                                if not prepared.event_created:
                                    continue
                                event_count += 1
                                if prepared.notification_error_type is not None:
                                    notification_preparation_failures.append(
                                        prepared.notification_error_type
                                    )
                                if prepared.message is not None:
                                    messages.append(prepared.message)
                            except Exception:  # noqa: BLE001 - isolate each exact pair
                                if session.in_transaction():
                                    session.rollback()
                                processing_error_type = PROCESSING_FAILURE
                                _LOGGER.warning(
                                    "ALERT_RULE_PROCESSING_FAILED "
                                    "symbol=%s frequency=%s stage=%s",
                                    symbol,
                                    frequency.value,
                                    stage,
                                )
                finally:
                    if session.in_transaction():
                        session.rollback()
        except Exception:  # noqa: BLE001 - DB/session failure must not send
            processing_error_type = PROCESSING_FAILURE
            fatal_processing_failure = True
            _LOGGER.warning("ALERT_PROCESSING_FAILED")

        if event_count:
            self._update_runtime_status(last_event_at=_iso_timestamp(processing_now))
        for error_type in notification_preparation_failures:
            self._record_notification_failure(
                at=processing_now,
                error_type=error_type,
            )
        if processing_error_type is None:
            self._update_runtime_status(
                last_processing_success_at=_iso_timestamp(processing_now),
                processing_error_type=None,
            )
        else:
            self._update_runtime_status(
                last_processing_failure_at=_iso_timestamp(processing_now),
                processing_error_type=processing_error_type,
            )
            if fatal_processing_failure or not messages:
                return

        self._send_messages_once(messages, processing_now=processing_now)

    def _send_messages_once(
        self,
        messages: list[AlertNotificationMessage],
        *,
        processing_now: datetime,
    ) -> None:
        for message in messages:
            self._update_runtime_status(
                last_transport_attempt_at=_iso_timestamp(processing_now)
            )
            try:
                acceptance = self._sender.send(message)
            except Exception:  # noqa: BLE001 - committed Event is never retried
                self._record_notification_failure(
                    at=processing_now,
                    error_type=NOTIFICATION_TRANSPORT_FAILURE,
                )
                _LOGGER.warning("ALERT_NOTIFICATION_FAILED")
                continue
            if not isinstance(acceptance, ProviderAcceptance):
                self._record_notification_failure(
                    at=processing_now,
                    error_type=NOTIFICATION_ACCEPTANCE_INVALID,
                )
                _LOGGER.warning("ALERT_NOTIFICATION_FAILED")
                continue
            self._update_runtime_status(
                last_provider_accepted_at=_iso_timestamp(processing_now),
                last_notification_failure_at=None,
                notification_error_type=None,
                consecutive_notification_failures=0,
            )

    def _evaluate_rule(
        self,
        session: Session,
        *,
        rule_code: str,
        symbol: str,
        event_frequency: BarFrequency,
        event_bar: CanonicalBar,
        processing_now: datetime,
    ) -> _RuleResult | None:
        if rule_code == HTDY_RULE.rule_code:
            return self._evaluate_htdy(
                session,
                symbol=symbol,
                event_frequency=event_frequency,
                event_bar=event_bar,
            )
        if rule_code == SUBING_RULE.rule_code:
            return self._evaluate_subing(
                session,
                symbol=symbol,
                event_frequency=event_frequency,
                event_bar=event_bar,
                processing_now=processing_now,
            )
        return None

    def _evaluate_htdy(
        self,
        session: Session,
        *,
        symbol: str,
        event_frequency: BarFrequency,
        event_bar: CanonicalBar,
    ) -> _RuleResult | None:
        window = self._market_read_factory(session).bars_until(
            SeriesPageQuery(
                SeriesKind.ACTUAL_DOMINANT,
                symbol,
                event_frequency,
            ),
            trading_day=event_bar.trading_day,
            end=event_bar.bar_end,
            limit=32,
        )
        if not _window_matches_event(
            window,
            symbol=symbol,
            event_frequency=event_frequency,
            event_bar=event_bar,
        ):
            return None
        evaluation = self._htdy_evaluator.evaluate(window)
        if (
            not isinstance(evaluation, AlertEvaluation)
            or not evaluation.observation_types
        ):
            return None
        return _RuleResult(
            contract=window.contract,
            frequency=event_frequency.value,
            result_codes=evaluation.observation_types,
            lower_tf_confirmation=False,
        )

    def _evaluate_subing(
        self,
        session: Session,
        *,
        symbol: str,
        event_frequency: BarFrequency,
        event_bar: CanonicalBar,
        processing_now: datetime,
    ) -> _RuleResult | None:
        event_session = _event_session_window(
            session,
            symbol=symbol,
            event_bar=event_bar,
        )
        if event_session is None:
            return None
        if (
            event_frequency is BarFrequency.M5
            and bucket_window_for_bar(
                event_session,
                BarFrequency.M15,
                event_bar.bar_end,
            ).end
            == event_bar.bar_end
        ):
            return None
        snapshot_now = _subing_snapshot_now(
            event_bar=event_bar,
            event_session=event_session,
            processing_now=processing_now,
        )
        if snapshot_now is None:
            return None
        snapshot = self._subing_read_factory(session).snapshot(
            SubingReadRequest(symbol, event_frequency),
            snapshot_now,
        )
        primary = snapshot.primary
        if (
            primary.status is not SubingFactorStatus.READY
            or primary.snapshot is None
            or primary.snapshot.bar_end != event_bar.bar_end
            or primary.snapshot.trading_day != event_bar.trading_day
        ):
            return None
        resolved = snapshot.resolved_signal
        if (
            resolved is None
            or resolved.status is not SubingSignalStatus.MATCHED
            or resolved.trigger_timeframe
            not in {BarFrequency.M5, BarFrequency.M15}
        ):
            return None
        if resolved.direction is SubingDirection.LONG:
            result_codes = ("buy",)
        elif resolved.direction is SubingDirection.SHORT:
            result_codes = ("sell",)
        else:
            return None
        return _RuleResult(
            contract=snapshot.actual_contract,
            frequency=resolved.trigger_timeframe.value,
            result_codes=result_codes,
            lower_tf_confirmation=resolved.lower_tf_confirmation,
        )

    def _write_heartbeat(self, now: datetime) -> None:
        assert self.heartbeat_store is not None
        with self._session_factory() as session:
            try:
                enabled = session.scalars(
                    select(AlertRule).where(AlertRule.enabled.is_(True))
                ).all()
                enabled_rule_count = len(enabled)
                service = AlertService(
                    session,
                    operational_products=tuple(
                        sorted(self._operational_products)
                    ),
                )
                scope: set[str] = set()
                for rule in enabled:
                    try:
                        definition = get_alert_rule_definition(rule.rule_code)
                        rule_scope = {
                            symbol
                            for symbol in self._operational_products
                            if any(
                                service.rule_allows_event(
                                    rule,
                                    symbol=symbol,
                                    frequency=frequency,
                                )
                                for frequency in definition.input_frequencies
                            )
                        }
                    except AlertScopeError:
                        _LOGGER.warning("ALERT_RULE_SCOPE_INVALID")
                        continue
                    scope.update(rule_scope)
            finally:
                if session.in_transaction():
                    session.rollback()
        self.heartbeat_store.write(
            {
                "generated_at": now.astimezone(UTC).isoformat(),
                "available": True,
                "enabled_rule_count": enabled_rule_count,
                "scope_product_count": len(scope),
            },
            ttl_seconds=_HEARTBEAT_TTL_SECONDS,
        )

    def _aware_now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise RuntimeError("ALERT_RUNTIME_CLOCK_INVALID")
        return now.astimezone(UTC)

    def _record_notification_failure(
        self,
        *,
        at: datetime,
        error_type: str,
    ) -> None:
        status = self._current_runtime_status()
        self._update_runtime_status(
            last_notification_failure_at=_iso_timestamp(at),
            notification_error_type=error_type,
            consecutive_notification_failures=(
                cast(int, status["consecutive_notification_failures"]) + 1
            ),
        )

    def _current_runtime_status(self) -> dict[str, object]:
        if self._runtime_status is None:
            if self.runtime_status_store is None:
                self._runtime_status = empty_alert_runtime_status()
            else:
                self._runtime_status = self.runtime_status_store.read()
        return self._runtime_status

    def _update_runtime_status(self, **changes: object) -> None:
        if self.runtime_status_store is None:
            return
        updated = {**self._current_runtime_status(), **changes}
        normalized = validate_alert_runtime_status(updated)
        self.runtime_status_store.write(normalized)
        self._runtime_status = normalized


_RUNTIME_STATUS_FIELDS = frozenset(
    {
        "schema_version",
        "last_processed_bar_at",
        "last_processing_success_at",
        "last_processing_failure_at",
        "processing_error_type",
        "last_event_at",
        "last_transport_attempt_at",
        "last_provider_accepted_at",
        "last_notification_failure_at",
        "notification_error_type",
        "consecutive_notification_failures",
    }
)
_RUNTIME_STATUS_TIMESTAMP_FIELDS = _RUNTIME_STATUS_FIELDS - {
    "schema_version",
    "processing_error_type",
    "notification_error_type",
    "consecutive_notification_failures",
}
_RUNTIME_STATUS_ERROR_TYPES = {
    "processing_error_type": frozenset({PROCESSING_FAILURE}),
    "notification_error_type": frozenset(
        {
            NOTIFICATION_PREPARATION_FAILURE,
            NOTIFICATION_TRANSPORT_FAILURE,
            NOTIFICATION_ACCEPTANCE_INVALID,
        }
    ),
}


def empty_alert_runtime_status() -> dict[str, object]:
    return {
        "schema_version": 1,
        "last_processed_bar_at": None,
        "last_processing_success_at": None,
        "last_processing_failure_at": None,
        "processing_error_type": None,
        "last_event_at": None,
        "last_transport_attempt_at": None,
        "last_provider_accepted_at": None,
        "last_notification_failure_at": None,
        "notification_error_type": None,
        "consecutive_notification_failures": 0,
    }


def validate_alert_runtime_status(
    payload: Mapping[str, object],
) -> dict[str, object]:
    if set(payload) != _RUNTIME_STATUS_FIELDS or type(payload.get("schema_version")) is not int:
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    if payload["schema_version"] != 1:
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    normalized = dict(payload)
    for field in _RUNTIME_STATUS_TIMESTAMP_FIELDS:
        value = payload[field]
        if value is not None:
            if not isinstance(value, str):
                raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
            normalized[field] = _iso_timestamp(datetime.fromisoformat(value))
    for field, allowed_values in _RUNTIME_STATUS_ERROR_TYPES.items():
        value = payload[field]
        if value is not None and (
            not isinstance(value, str) or value not in allowed_values
        ):
            raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    count = payload["consecutive_notification_failures"]
    if type(count) is not int or count < 0:
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    return normalized


def _iso_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    return value.astimezone(UTC).isoformat()


def _event_session_window(
    session: Session,
    *,
    symbol: str,
    event_bar: CanonicalBar,
) -> SessionWindow | None:
    """使用交易日、交易所与既有 Session clock 唯一解析事件时段。"""
    normalized = normalize_symbol(symbol)
    exchange = session.scalar(
        select(Instrument.exchange_code).where(
            Instrument.symbol == normalized,
            Instrument.is_active.is_(True),
        )
    )
    if exchange is None:
        return None
    calendar = session.scalar(
        select(TradingCalendar).where(
            TradingCalendar.exchange_code == exchange,
            TradingCalendar.trade_date == event_bar.trading_day,
        )
    )
    if calendar is None or calendar.is_trading_day is not True:
        return None
    try:
        resolved = resolved_session_windows_for_trading_day(
            session,
            exchange=exchange,
            symbol=normalized,
            trading_day=event_bar.trading_day,
        )
    except SessionClockError:
        return None
    matching = tuple(
        item.window
        for item in resolved
        if (not item.is_night or calendar.has_night_session is True)
        and item.window.start < event_bar.bar_end <= item.window.end
    )
    return matching[0] if len(matching) == 1 else None


def _subing_snapshot_now(
    *,
    event_bar: CanonicalBar,
    event_session: SessionWindow,
    processing_now: datetime,
) -> datetime | None:
    """限定 final Session Bar 的 phase-observation 时间，不改变 snapshot 数据截止。"""
    if processing_now.tzinfo is None or processing_now.utcoffset() is None:
        return None
    normalized_now = processing_now.astimezone(UTC)
    if normalized_now < event_bar.bar_end:
        return None
    if event_bar.bar_end != event_session.end:
        return normalized_now
    if normalized_now <= event_bar.bar_end + LIVE_SESSION_END_ARRIVAL_GRACE:
        return event_bar.bar_end - timedelta(microseconds=1)
    return None


def _parse_live_bar_trigger(
    channel: object,
    payload: object,
) -> _LiveBarTrigger | None:
    try:
        if isinstance(channel, bytes):
            channel = channel.decode("utf-8")
        if not isinstance(channel, str):
            return None
        parts = channel.split(":")
        if len(parts) != 4 or parts[:2] != ["live", "bar"]:
            return None
        frequency = BarFrequency(parts[3])
        if frequency not in INTRADAY_FREQUENCIES:
            return None
        symbol = normalize_symbol(parts[2])
        if not symbol:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        raw = json.loads(payload) if isinstance(payload, str) else payload
        if not isinstance(raw, Mapping):
            return None
        bar = CanonicalBar(
            bar_end=datetime.fromisoformat(
                str(raw["bar_end"]).replace("Z", "+00:00")
            ),
            trading_day=date.fromisoformat(str(raw["trading_day"])),
            open=Decimal(str(raw["open"])),
            high=Decimal(str(raw["high"])),
            low=Decimal(str(raw["low"])),
            close=Decimal(str(raw["close"])),
            volume=Decimal(str(raw["volume"])),
            turnover=(
                None
                if raw["turnover"] is None
                else Decimal(str(raw["turnover"]))
            ),
            open_interest=(
                None
                if raw["open_interest"] is None
                else Decimal(str(raw["open_interest"]))
            ),
        )
    except (DecimalException, KeyError, TypeError, ValueError, UnicodeError):
        return None
    return _LiveBarTrigger(symbol=symbol, frequency=frequency, bar=bar)


def _parse_canonical_updated_trigger(
    channel: object,
    payload: object,
) -> _CanonicalUpdatedTrigger | None:
    try:
        if isinstance(channel, bytes):
            channel = channel.decode("utf-8")
        if channel != _MARKET_STATE_PATTERN:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        raw = json.loads(payload) if isinstance(payload, str) else payload
        if not isinstance(raw, Mapping) or raw.get("reason") != "canonical_updated":
            return None
        raw_trading_day = raw.get("trading_day")
        if not isinstance(raw_trading_day, str):
            return None
        trading_day = date.fromisoformat(raw_trading_day)
        if raw_trading_day != trading_day.isoformat():
            return None
    except (TypeError, ValueError, UnicodeError):
        return None
    return _CanonicalUpdatedTrigger(trading_day=trading_day)


def _window_matches_event(
    window: MarketReadWindow,
    *,
    symbol: str,
    event_frequency: BarFrequency,
    event_bar: CanonicalBar,
) -> bool:
    return bool(
        window.symbol == symbol
        and window.series_kind == "actual_dominant"
        and window.frequency == event_frequency.value
        and window.trading_day == event_bar.trading_day
        and window.cutoff == event_bar.bar_end
        and window.bars
        and window.bars[-1] == event_bar
        and normalize_contract_for_symbol(symbol, window.contract) == window.contract
    )


def _canonical_window_matches_trigger(
    window: MarketReadWindow,
    *,
    symbol: str,
    frequency: BarFrequency,
    trading_day: date,
) -> bool:
    return bool(
        window.symbol == symbol
        and window.series_kind == "actual_dominant"
        and window.frequency == frequency.value
        and window.trading_day == trading_day
        and window.bars
        and window.bars[-1].trading_day == trading_day
        and window.cutoff == window.bars[-1].bar_end
        and normalize_contract_for_symbol(symbol, window.contract) == window.contract
    )
