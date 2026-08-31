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

from app.alerts.evaluators import (
    HTDY_FIRST_SEEN_CONTEXT_BARS,
    AlertEvaluator,
    HtdyFirstSeenObservation,
)
from app.alerts.models import AlertRule
from app.alerts.notification import (
    AlertNotificationMessage,
    AlertNotificationSender,
    ProviderAcceptance,
)
from app.alerts.registry import (
    HTDY_RULE,
    SUBING_RULE,
    alert_rule_definitions,
    get_alert_rule_definition,
)
from app.alerts.service import AlertEventCreate, AlertScopeError, AlertService
from app.alerts.strategy_payload import serialize_subing_strategy_payload
from app.alerts.subing_strategy_runtime import (
    PUBLIC_SUBING_STRATEGY_RUNTIME_REASON_CODES,
    SubingStrategyRuntimeActionFact,
    SubingStrategyRuntimeEvaluator,
    SubingStrategyRuntimeProductStatus,
    SubingStrategyRuntimeResult,
)
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    INTRADAY_FREQUENCIES,
    SeriesKind,
    SeriesPageQuery,
    normalize_contract_for_symbol,
)
from app.market_data.market_read_service import MarketReadService, MarketReadWindow
from app.market_data.product_retirement import normalize_symbol
from app.market_data.product_taxonomy import ProductTaxonomyEntry
from app.market_data.subing_strategy.contracts import (
    SubingStrategyAction,
    SubingStrategyEpisode,
)
from app.market_data.subing_strategy.machine import SubingStrategySourceIdentity
from guiyi_quant.indicators.htdy_original import CONFIGURED_REPAINT_SCAN_ZONE_BARS


_LOGGER = logging.getLogger(__name__)
_LIVE_BAR_PATTERN = "live:bar:*:*"
_MARKET_STATE_PATTERN = "market:state"
_CANONICAL_ALERT_FREQUENCIES = (BarFrequency.D1, BarFrequency.W1)
_HEARTBEAT_INTERVAL = timedelta(seconds=10)
_HEARTBEAT_TTL_SECONDS = 30
_STRATEGY_PRODUCT_LIMIT = 60
PROCESSING_FAILURE = "processing_failed"
NOTIFICATION_PREPARATION_FAILURE = "notification_preparation_failed"
NOTIFICATION_TRANSPORT_FAILURE = "notification_transport_failed"
NOTIFICATION_ACCEPTANCE_INVALID = "notification_acceptance_invalid"


class AlertNotificationAcknowledgeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AlertMessageSource(Protocol):
    def subscribe(self, *patterns: str) -> None: ...
    def drain_startup_messages(self) -> tuple[tuple[object, object], ...]: ...
    def get_message(
        self, *, timeout_seconds: float
    ) -> tuple[object, object] | None: ...
    def close(self) -> None: ...


class AlertHeartbeatStore(Protocol):
    def write(self, payload: dict[str, object], *, ttl_seconds: int) -> None: ...


class AlertRuntimeStatusStore(Protocol):
    def read(self) -> dict[str, object]: ...
    def write(self, payload: dict[str, object]) -> None: ...


AlertSessionFactory = Callable[[], AbstractContextManager[Session]]
AlertMarketReadFactory = Callable[[Session], MarketReadService]


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


def _persist_first_seen_htdy_and_prepare_notification(
    service: AlertService,
    *,
    taxonomy: Mapping[str, ProductTaxonomyEntry],
    rule: AlertRule,
    symbol: str,
    frequency: str,
    candidate: HtdyFirstSeenObservation,
    processing_now: datetime,
) -> _PreparedEvent:
    created = service.create_first_seen_observation_event(
        AlertEventCreate(
            rule_id=rule.id,
            symbol=symbol,
            contract=candidate.contract,
            trading_day=candidate.trading_day,
            frequency=frequency,
            bar_end=candidate.bar_end,
            result_codes=candidate.observation_types,
            action_id=None,
            strategy_payload=None,
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
            contract=candidate.contract,
            frequency=frequency,
            bar_end=candidate.bar_end,
            detected_at=processing_now,
            result_codes=candidate.observation_types,
        ),
        None,
    )


def _persist_strategy_action_and_prepare_notification(
    service: AlertService,
    *,
    taxonomy: Mapping[str, ProductTaxonomyEntry],
    rule: AlertRule,
    action: SubingStrategyAction,
    episode: SubingStrategyEpisode | None,
    processing_now: datetime,
) -> _PreparedEvent:
    payload = serialize_subing_strategy_payload(action, episode=episode)
    created = service.create_event(
        AlertEventCreate(
            rule_id=rule.id,
            symbol=action.symbol,
            contract=action.contract,
            trading_day=action.trading_day,
            frequency=BarFrequency.M15.value,
            bar_end=action.decision_at,
            result_codes=(action.kind.value,),
            action_id=action.action_id,
            strategy_payload=payload,
            detected_at=processing_now,
            notification_attempted_at=processing_now,
        )
    )
    if created is None:
        return _PreparedEvent(False, None, None)
    taxonomy_entry = taxonomy.get(action.symbol)
    if taxonomy_entry is None:
        _LOGGER.warning("ALERT_PRODUCT_NAME_UNAVAILABLE")
        return _PreparedEvent(True, None, NOTIFICATION_PREPARATION_FAILURE)
    return _PreparedEvent(
        True,
        AlertNotificationMessage(
            rule_code=rule.rule_code,
            symbol=action.symbol,
            product_name=taxonomy_entry.name,
            contract=action.contract,
            frequency=BarFrequency.M15.value,
            bar_end=action.decision_at,
            detected_at=processing_now,
            result_codes=(action.kind.value,),
            strategy_payload=payload,
        ),
        None,
    )


class AlertRuntime:
    def __init__(
        self,
        *,
        session_factory: AlertSessionFactory,
        market_read_factory: AlertMarketReadFactory,
        strategy_evaluator: SubingStrategyRuntimeEvaluator,
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
        self._strategy_evaluator = strategy_evaluator
        try:
            strategy_products = tuple(strategy_evaluator.products)
        except (AttributeError, TypeError):
            raise ValueError("ALERT_RUNTIME_STRATEGY_PRODUCTS_INVALID") from None
        if (
            not strategy_products
            or len(set(strategy_products)) != len(strategy_products)
            or any(
                type(symbol) is not str
                or symbol != symbol.strip().lower()
                or not symbol.isascii()
                or not symbol.isalpha()
                for symbol in strategy_products
            )
        ):
            raise ValueError("ALERT_RUNTIME_STRATEGY_PRODUCTS_INVALID")
        self._strategy_products = frozenset(strategy_products)
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
        self._strategy_product_statuses: dict[
            str, SubingStrategyRuntimeProductStatus
        ] = {}
        self.clock = clock or (lambda: datetime.now(UTC))
        self.stop_requested = stop_requested or (lambda: False)

    def run_forever(self) -> None:
        """只消费启动后新到达的 completed 日内 Bar 与 Canonical state。"""
        if self.message_source is None or self.heartbeat_store is None:
            raise RuntimeError("ALERT_RUNTIME_TRANSPORT_UNAVAILABLE")
        self._current_runtime_status()
        self._validate_startup_composition()
        self.message_source.subscribe(_LIVE_BAR_PATTERN, _MARKET_STATE_PATTERN)
        strategy_started_at = self._aware_now()
        self._update_runtime_status(
            strategy_state="warming",
            strategy_started_at=_iso_timestamp(strategy_started_at),
            strategy_ready_at=None,
            strategy_product_count=0,
            strategy_ready_product_count=0,
            strategy_unavailable_product_count=0,
            strategy_unavailable_symbols=[],
            strategy_unavailable_reason_codes={},
        )
        self._strategy_evaluator.restore_all(
            started_at=strategy_started_at,
        )
        catch_up_at = self._aware_now()
        caught_up = self._strategy_evaluator.final_catch_up(ready_at=catch_up_at)
        self._strategy_product_statuses.clear()
        self._refresh_strategy_runtime_status(
            caught_up,
            expected_products=self._strategy_products,
        )
        self._drain_startup_messages()
        ready_at = self._aware_now()
        self._update_runtime_status(
            strategy_ready_at=_iso_timestamp(ready_at),
            last_strategy_restore_at=_iso_timestamp(catch_up_at),
        )
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

    def _validate_startup_composition(self) -> None:
        expected_codes = tuple(
            sorted(definition.rule_code for definition in alert_rule_definitions())
        )
        try:
            if not self._strategy_products.issubset(self._operational_products):
                raise ValueError("strategy Live feed incomplete")
            with self._session_factory() as session:
                try:
                    rules = session.scalars(
                        select(AlertRule).order_by(AlertRule.rule_code)
                    ).all()
                    if tuple(rule.rule_code for rule in rules) != expected_codes:
                        raise ValueError("rule registry mismatch")
                    service = AlertService(
                        session,
                        operational_products=tuple(sorted(self._operational_products)),
                    )
                    for symbol in sorted(self._operational_products):
                        states = service.product_rules(symbol)
                        if tuple(state.rule_code for state in states) != expected_codes:
                            raise ValueError("rule projection mismatch")
                finally:
                    if session.in_transaction():
                        session.rollback()
        except Exception:
            raise RuntimeError("ALERT_RUNTIME_COMPOSITION_INVALID") from None

    def _drain_startup_messages(self) -> None:
        assert self.message_source is not None
        for message in self.message_source.drain_startup_messages():
            self.process_message(*message, emit_events=False)

    def process_message(
        self,
        channel: object,
        payload: object,
        *,
        emit_events: bool = True,
    ) -> None:
        """处理单条强类型触发；Rule 故障隔离，Event 提交后只发送一次。"""
        trigger = _parse_live_bar_trigger(channel, payload)
        if trigger is None:
            canonical_trigger = _parse_canonical_updated_trigger(channel, payload)
            if canonical_trigger is not None:
                self._process_canonical_updated(
                    canonical_trigger,
                    emit_events=emit_events,
                )
            return
        symbol = trigger.symbol
        event_frequency = trigger.frequency
        event_bar = trigger.bar
        try:
            processing_now = self._aware_now()
        except Exception:  # noqa: BLE001 - collapse clock detail
            _LOGGER.warning("ALERT_PROCESSING_FAILED")
            return

        strategy_action_facts: tuple[SubingStrategyRuntimeActionFact, ...] = ()
        if symbol in self._strategy_products:
            state = self._strategy_evaluator.current_state(symbol)
        else:
            state = None
        if state is not None and event_frequency.value in SUBING_RULE.input_frequencies:
            strategy_result = self._strategy_evaluator.process_completed_bar(
                event_bar,
                event_frequency,
                source_identity=SubingStrategySourceIdentity(
                    symbol=state.symbol,
                    contract=state.contract,
                    segment_start_trading_day=state.segment_start_trading_day,
                ),
            )
            self._refresh_strategy_runtime_status(
                (strategy_result,),
                expected_products=frozenset((symbol,)),
            )
            strategy_action_facts = strategy_result.action_facts

        if not emit_events:
            return
        if symbol not in self._operational_products:
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
                        operational_products=tuple(sorted(self._operational_products)),
                    )
                    for rule in rules:
                        try:
                            definition = get_alert_rule_definition(rule.rule_code)
                            if definition.rule_code == SUBING_RULE.rule_code:
                                continue
                            if (
                                event_frequency.value
                                not in definition.input_frequencies
                            ):
                                continue
                            if not service.rule_allows_event(
                                rule,
                                symbol=symbol,
                                frequency=event_frequency.value,
                            ):
                                continue
                            candidates = self._evaluate_rule(
                                session,
                                rule_code=definition.rule_code,
                                symbol=symbol,
                                event_frequency=event_frequency,
                                event_bar=event_bar,
                            )
                            if not candidates:
                                continue
                            for candidate in candidates:
                                try:
                                    prepared = (
                                        _persist_first_seen_htdy_and_prepare_notification(
                                            service,
                                            taxonomy=self._taxonomy,
                                            rule=rule,
                                            symbol=symbol,
                                            frequency=event_frequency.value,
                                            candidate=candidate,
                                            processing_now=processing_now,
                                        )
                                    )
                                except Exception:  # noqa: BLE001 - isolate each candidate
                                    if session.in_transaction():
                                        session.rollback()
                                    processing_error_type = PROCESSING_FAILURE
                                    _LOGGER.warning("ALERT_RULE_PROCESSING_FAILED")
                                    continue
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
                    if strategy_action_facts:
                        strategy_rule = next(
                            (
                                rule
                                for rule in rules
                                if rule.rule_code == SUBING_RULE.rule_code
                            ),
                            None,
                        )
                        if strategy_rule is not None:
                            for action_fact in strategy_action_facts:
                                action = action_fact.action
                                try:
                                    if not service.rule_allows_event(
                                        strategy_rule,
                                        symbol=action.symbol,
                                        frequency=BarFrequency.M15.value,
                                    ):
                                        continue
                                    prepared = _persist_strategy_action_and_prepare_notification(
                                        service,
                                        taxonomy=self._taxonomy,
                                        rule=strategy_rule,
                                        action=action,
                                        episode=action_fact.episode,
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
                                except Exception:  # noqa: BLE001 - exact Strategy Rule isolation
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
        if strategy_action_facts:
            self._update_runtime_status(
                last_strategy_action_at=max(
                    _iso_timestamp(fact.action.effective_bar_end)
                    for fact in strategy_action_facts
                )
            )
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
        *,
        emit_events: bool = True,
    ) -> None:
        try:
            processing_now = self._aware_now()
        except Exception:  # noqa: BLE001 - collapse clock detail
            _LOGGER.warning("ALERT_PROCESSING_FAILED")
            return

        strategy_action_facts: tuple[SubingStrategyRuntimeActionFact, ...] = ()
        strategy_results = self._strategy_evaluator.process_canonical_updated(
            trigger.trading_day
        )
        self._refresh_strategy_runtime_status(
            strategy_results,
            expected_products=self._strategy_products,
        )
        strategy_action_facts = tuple(
            fact for result in strategy_results for fact in result.action_facts
        )
        if not emit_events:
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
                        operational_products=tuple(sorted(self._operational_products)),
                    )
                    for rule in rules:
                        if rule.rule_code != HTDY_RULE.rule_code:
                            continue
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
                                    limit=64,
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
                                candidates = _validated_first_seen_candidates(
                                    self._htdy_evaluator.evaluate_first_seen(window),
                                    window=window,
                                )
                                if not candidates:
                                    continue
                                for candidate in candidates:
                                    stage = "event_persist"
                                    try:
                                        prepared = (
                                            _persist_first_seen_htdy_and_prepare_notification(
                                                service,
                                                taxonomy=self._taxonomy,
                                                rule=rule,
                                                symbol=symbol,
                                                frequency=frequency.value,
                                                candidate=candidate,
                                                processing_now=processing_now,
                                            )
                                        )
                                    except Exception:  # noqa: BLE001 - isolate each candidate
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
                                        continue
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
                    if strategy_action_facts:
                        strategy_rule = next(
                            (
                                rule
                                for rule in rules
                                if rule.rule_code == SUBING_RULE.rule_code
                            ),
                            None,
                        )
                        if strategy_rule is not None:
                            for action_fact in strategy_action_facts:
                                action = action_fact.action
                                try:
                                    if not service.rule_allows_event(
                                        strategy_rule,
                                        symbol=action.symbol,
                                        frequency=BarFrequency.M15.value,
                                    ):
                                        continue
                                    prepared = _persist_strategy_action_and_prepare_notification(
                                        service,
                                        taxonomy=self._taxonomy,
                                        rule=strategy_rule,
                                        action=action,
                                        episode=action_fact.episode,
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
                                except Exception:  # noqa: BLE001 - exact Strategy Rule isolation
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
        if strategy_action_facts:
            self._update_runtime_status(
                last_strategy_action_at=max(
                    _iso_timestamp(fact.action.effective_bar_end)
                    for fact in strategy_action_facts
                )
            )
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
    ) -> tuple[HtdyFirstSeenObservation, ...]:
        if rule_code == HTDY_RULE.rule_code:
            return self._evaluate_htdy(
                session,
                symbol=symbol,
                event_frequency=event_frequency,
                event_bar=event_bar,
            )
        return ()

    def _evaluate_htdy(
        self,
        session: Session,
        *,
        symbol: str,
        event_frequency: BarFrequency,
        event_bar: CanonicalBar,
    ) -> tuple[HtdyFirstSeenObservation, ...]:
        window = self._market_read_factory(session).bars_until(
            SeriesPageQuery(
                SeriesKind.ACTUAL_DOMINANT,
                symbol,
                event_frequency,
            ),
            trading_day=event_bar.trading_day,
            end=event_bar.bar_end,
            limit=64,
        )
        if not _window_matches_event(
            window,
            symbol=symbol,
            event_frequency=event_frequency,
            event_bar=event_bar,
        ):
            return ()
        return _validated_first_seen_candidates(
            self._htdy_evaluator.evaluate_first_seen(window),
            window=window,
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
                    operational_products=tuple(sorted(self._operational_products)),
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

    def _refresh_strategy_runtime_status(
        self,
        results: tuple[SubingStrategyRuntimeResult, ...],
        *,
        expected_products: frozenset[str],
    ) -> None:
        _validate_strategy_runtime_results(
            results,
            active_products=self._strategy_products,
            expected_products=expected_products,
        )
        for result in results:
            status = result.product_status
            self._strategy_product_statuses[status.symbol] = status
        summary = _strategy_runtime_summary(
            tuple(self._strategy_product_statuses.values())
        )
        unavailable_reason_codes = _strategy_unavailable_reason_codes(
            tuple(self._strategy_product_statuses.values())
        )
        self._update_runtime_status(
            strategy_state=("degraded" if summary[2] else "ready"),
            strategy_product_count=summary[0],
            strategy_ready_product_count=summary[1],
            strategy_unavailable_product_count=len(summary[2]),
            strategy_unavailable_symbols=list(summary[2]),
            strategy_unavailable_reason_codes=unavailable_reason_codes,
        )

    def _record_notification_failure(
        self,
        *,
        at: datetime,
        error_type: str,
    ) -> None:
        status = self._current_runtime_status()
        self._update_runtime_status(
            last_notification_failure_at=_iso_timestamp(at),
            notification_acknowledged_at=None,
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
                self._runtime_status = validate_alert_runtime_status(
                    self.runtime_status_store.read()
                )
        return self._runtime_status

    def _update_runtime_status(self, **changes: object) -> None:
        if self.runtime_status_store is None:
            return
        atomic_update = getattr(self.runtime_status_store, "update", None)
        if callable(atomic_update):
            normalized = validate_alert_runtime_status(atomic_update(dict(changes)))
            self._runtime_status = normalized
            return
        updated = {**self._current_runtime_status(), **changes}
        normalized = validate_alert_runtime_status(updated)
        self.runtime_status_store.write(normalized)
        self._runtime_status = normalized


_RUNTIME_STATUS_V1_FIELDS = frozenset(
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
_RUNTIME_STATUS_V2_FIELDS = _RUNTIME_STATUS_V1_FIELDS | {"notification_acknowledged_at"}
_RUNTIME_STATUS_STRATEGY_FIELDS = frozenset(
    {
        "strategy_state",
        "strategy_started_at",
        "strategy_ready_at",
        "strategy_product_count",
        "strategy_ready_product_count",
        "strategy_unavailable_product_count",
        "strategy_unavailable_symbols",
        "last_strategy_action_at",
        "last_strategy_restore_at",
    }
)
_RUNTIME_STATUS_V3_FIELDS = _RUNTIME_STATUS_V2_FIELDS | _RUNTIME_STATUS_STRATEGY_FIELDS
_RUNTIME_STATUS_V4_FIELDS = _RUNTIME_STATUS_V3_FIELDS | {
    "strategy_unavailable_reason_codes"
}
_RUNTIME_STATUS_FIELDS = _RUNTIME_STATUS_V4_FIELDS
_RUNTIME_STATUS_TIMESTAMP_FIELDS = _RUNTIME_STATUS_V4_FIELDS - {
    "schema_version",
    "processing_error_type",
    "notification_error_type",
    "consecutive_notification_failures",
    "strategy_state",
    "strategy_product_count",
    "strategy_ready_product_count",
    "strategy_unavailable_product_count",
    "strategy_unavailable_symbols",
    "strategy_unavailable_reason_codes",
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
        "schema_version": 4,
        "last_processed_bar_at": None,
        "last_processing_success_at": None,
        "last_processing_failure_at": None,
        "processing_error_type": None,
        "last_event_at": None,
        "last_transport_attempt_at": None,
        "last_provider_accepted_at": None,
        "last_notification_failure_at": None,
        "notification_acknowledged_at": None,
        "notification_error_type": None,
        "consecutive_notification_failures": 0,
        "strategy_state": "warming",
        "strategy_started_at": None,
        "strategy_ready_at": None,
        "strategy_product_count": 0,
        "strategy_ready_product_count": 0,
        "strategy_unavailable_product_count": 0,
        "strategy_unavailable_symbols": [],
        "strategy_unavailable_reason_codes": {},
        "last_strategy_action_at": None,
        "last_strategy_restore_at": None,
    }


def validate_alert_runtime_status(
    payload: Mapping[str, object],
) -> dict[str, object]:
    if type(payload.get("schema_version")) is not int:
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    schema_version = payload["schema_version"]
    fields = set(payload)
    if schema_version == 1 and fields == _RUNTIME_STATUS_V1_FIELDS:
        normalized = {
            **payload,
            "schema_version": 2,
            "notification_acknowledged_at": None,
        }
    elif schema_version == 2 and fields == _RUNTIME_STATUS_V2_FIELDS:
        normalized = dict(payload)
    elif schema_version == 3 and fields == _RUNTIME_STATUS_V3_FIELDS:
        normalized = {
            **payload,
            "schema_version": 4,
            "strategy_unavailable_reason_codes": {
                symbol: "PREVIOUS_RUNTIME_REASON_UNAVAILABLE"
                for symbol in payload["strategy_unavailable_symbols"]
            }
            if type(payload["strategy_unavailable_symbols"]) is list
            else {},
        }
    elif schema_version == 4 and fields == _RUNTIME_STATUS_V4_FIELDS:
        normalized = dict(payload)
    else:
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    if normalized["schema_version"] in {1, 2}:
        normalized = {
            **normalized,
            **{
                key: value
                for key, value in empty_alert_runtime_status().items()
                if key
                in (_RUNTIME_STATUS_STRATEGY_FIELDS | {"strategy_unavailable_reason_codes"})
            },
            "schema_version": 4,
        }
    for field in _RUNTIME_STATUS_TIMESTAMP_FIELDS:
        value = normalized[field]
        if value is not None:
            if not isinstance(value, str):
                raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
            normalized[field] = _iso_timestamp(datetime.fromisoformat(value))
    for field, allowed_values in _RUNTIME_STATUS_ERROR_TYPES.items():
        value = normalized[field]
        if value is not None and (
            not isinstance(value, str) or value not in allowed_values
        ):
            raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    count = normalized["consecutive_notification_failures"]
    if type(count) is not int or count < 0:
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    failure_at = normalized["last_notification_failure_at"]
    acknowledged_at = normalized["notification_acknowledged_at"]
    if acknowledged_at is not None and failure_at is None:
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    if normalized["strategy_state"] not in {"warming", "ready", "degraded"}:
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    strategy_counts = tuple(
        normalized[field]
        for field in (
            "strategy_product_count",
            "strategy_ready_product_count",
            "strategy_unavailable_product_count",
        )
    )
    if any(
        type(value) is not int or value < 0 or value > _STRATEGY_PRODUCT_LIMIT
        for value in strategy_counts
    ):
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    product_count, ready_count, unavailable_count = cast(
        tuple[int, int, int], strategy_counts
    )
    unavailable_symbols = normalized["strategy_unavailable_symbols"]
    if (
        type(unavailable_symbols) is not list
        or len(unavailable_symbols) != unavailable_count
        or len(unavailable_symbols) > product_count
        or any(
            type(symbol) is not str
            or symbol != symbol.strip().lower()
            or not symbol.isascii()
            or not symbol.isalpha()
            for symbol in unavailable_symbols
        )
        or unavailable_symbols != sorted(set(unavailable_symbols))
        or ready_count + unavailable_count > product_count
    ):
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    unavailable_reason_codes = normalized["strategy_unavailable_reason_codes"]
    if (
        type(unavailable_reason_codes) is not dict
        or set(unavailable_reason_codes) != set(unavailable_symbols)
        or any(
            type(symbol) is not str
            or type(reason_code) is not str
            or reason_code not in PUBLIC_SUBING_STRATEGY_RUNTIME_REASON_CODES
            for symbol, reason_code in unavailable_reason_codes.items()
        )
    ):
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    return normalized


def _strategy_runtime_summary(
    statuses: tuple[SubingStrategyRuntimeProductStatus, ...],
) -> tuple[int, int, tuple[str, ...]]:
    if type(statuses) is not tuple:
        raise ValueError("ALERT_RUNTIME_STRATEGY_RESULT_INVALID")
    if (
        any(
            type(status) is not SubingStrategyRuntimeProductStatus
            for status in statuses
        )
        or len(statuses) > _STRATEGY_PRODUCT_LIMIT
    ):
        raise ValueError("ALERT_RUNTIME_STRATEGY_RESULT_INVALID")
    if len({status.symbol for status in statuses}) != len(statuses) or any(
        status.symbol != status.symbol.strip().lower()
        or not status.symbol.isascii()
        or not status.symbol.isalpha()
        for status in statuses
    ):
        raise ValueError("ALERT_RUNTIME_STRATEGY_RESULT_INVALID")
    unavailable = tuple(
        sorted(status.symbol for status in statuses if status.state == "unavailable")
    )
    ready = sum(status.state == "ready" for status in statuses)
    if ready + len(unavailable) != len(statuses):
        raise ValueError("ALERT_RUNTIME_STRATEGY_RESULT_INVALID")
    return len(statuses), ready, unavailable


def _strategy_unavailable_reason_codes(
    statuses: tuple[SubingStrategyRuntimeProductStatus, ...],
) -> dict[str, str]:
    return {
        status.symbol: _single_public_reason_code(status.reason_codes)
        for status in sorted(statuses, key=lambda item: item.symbol)
        if status.state == "unavailable"
    }


def _single_public_reason_code(reason_codes: tuple[str, ...]) -> str:
    if (
        type(reason_codes) is not tuple
        or len(reason_codes) != 1
        or type(reason_codes[0]) is not str
        or reason_codes[0] not in PUBLIC_SUBING_STRATEGY_RUNTIME_REASON_CODES
    ):
        raise ValueError("ALERT_RUNTIME_STRATEGY_RESULT_INVALID")
    return reason_codes[0]


def _validate_strategy_runtime_results(
    results: tuple[SubingStrategyRuntimeResult, ...],
    *,
    active_products: frozenset[str],
    expected_products: frozenset[str],
) -> None:
    if type(results) is not tuple:
        raise ValueError("ALERT_RUNTIME_STRATEGY_RESULT_INVALID")
    symbols: list[str] = []
    for result in results:
        if (
            type(result) is not SubingStrategyRuntimeResult
            or type(result.action_facts) is not tuple
            or type(result.product_status) is not SubingStrategyRuntimeProductStatus
            or any(
                type(fact) is not SubingStrategyRuntimeActionFact
                or fact.action.symbol != result.product_status.symbol
                for fact in result.action_facts
            )
        ):
            raise ValueError("ALERT_RUNTIME_STRATEGY_RESULT_INVALID")
        symbols.append(result.product_status.symbol)
    symbol_set = frozenset(symbols)
    if (
        len(symbol_set) != len(symbols)
        or not symbol_set.issubset(active_products)
        or symbol_set != expected_products
    ):
        raise ValueError("ALERT_RUNTIME_STRATEGY_RESULT_INVALID")


def acknowledge_notification_failure(
    payload: Mapping[str, object],
    *,
    expected_failure_at: str,
    acknowledged_at: datetime,
) -> dict[str, object]:
    normalized = validate_alert_runtime_status(payload)
    failure_at = normalized["last_notification_failure_at"]
    if failure_at is None:
        raise AlertNotificationAcknowledgeError("ALERT_NOTIFICATION_FAILURE_NOT_FOUND")
    try:
        expected = _iso_timestamp(datetime.fromisoformat(expected_failure_at))
    except (TypeError, ValueError) as exc:
        raise AlertNotificationAcknowledgeError(
            "ALERT_NOTIFICATION_FAILURE_AT_INVALID"
        ) from exc
    if failure_at != expected:
        raise AlertNotificationAcknowledgeError("ALERT_NOTIFICATION_FAILURE_MISMATCH")
    existing_acknowledgement = normalized["notification_acknowledged_at"]
    if existing_acknowledgement is not None and datetime.fromisoformat(
        cast(str, existing_acknowledgement)
    ) >= datetime.fromisoformat(cast(str, failure_at)):
        raise AlertNotificationAcknowledgeError(
            "ALERT_NOTIFICATION_FAILURE_ALREADY_ACKNOWLEDGED"
        )
    try:
        acknowledgement = _iso_timestamp(acknowledged_at)
    except ValueError as exc:
        raise AlertNotificationAcknowledgeError(
            "ALERT_NOTIFICATION_ACKNOWLEDGEMENT_TIME_INVALID"
        ) from exc
    if datetime.fromisoformat(acknowledgement) < datetime.fromisoformat(
        cast(str, failure_at)
    ):
        raise AlertNotificationAcknowledgeError(
            "ALERT_NOTIFICATION_ACKNOWLEDGEMENT_TIME_INVALID"
        )
    updated = {
        **normalized,
        "notification_acknowledged_at": acknowledgement,
    }
    return validate_alert_runtime_status(updated)


def _iso_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    return value.astimezone(UTC).isoformat()


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
            bar_end=datetime.fromisoformat(str(raw["bar_end"]).replace("Z", "+00:00")),
            trading_day=date.fromisoformat(str(raw["trading_day"])),
            open=Decimal(str(raw["open"])),
            high=Decimal(str(raw["high"])),
            low=Decimal(str(raw["low"])),
            close=Decimal(str(raw["close"])),
            volume=Decimal(str(raw["volume"])),
            turnover=(
                None if raw["turnover"] is None else Decimal(str(raw["turnover"]))
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
        and len(window.bar_contracts) == len(window.bars)
        and window.bars[-1] == event_bar
        and window.bar_contracts[-1] == window.contract
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
        and len(window.bar_contracts) == len(window.bars)
        and window.bars[-1].trading_day == trading_day
        and window.cutoff == window.bars[-1].bar_end
        and window.bar_contracts[-1] == window.contract
        and normalize_contract_for_symbol(symbol, window.contract) == window.contract
    )


def _validated_first_seen_candidates(
    value: object,
    *,
    window: MarketReadWindow,
) -> tuple[HtdyFirstSeenObservation, ...]:
    if type(value) is not tuple:
        raise ValueError("ALERT_EVALUATION_OUTPUT_INVALID")
    candidates = cast(tuple[object, ...], value)
    validated: list[HtdyFirstSeenObservation] = []
    seen_bar_ends: set[datetime] = set()
    for item in candidates:
        if not isinstance(item, HtdyFirstSeenObservation):
            raise ValueError("ALERT_EVALUATION_OUTPUT_INVALID")
        if (
            item.bar_end in seen_bar_ends
            or type(item.observation_types) is not tuple
            or item.observation_types
            not in (("buy",), ("sell",), ("buy", "sell"))
        ):
            raise ValueError("ALERT_EVALUATION_OUTPUT_INVALID")
        matches = tuple(
            (index, bar, contract)
            for index, (bar, contract) in enumerate(
                zip(window.bars, window.bar_contracts, strict=True)
            )
            if bar.bar_end == item.bar_end
        )
        if (
            len(matches) != 1
            or not _first_seen_candidate_is_in_repaint_authority(
                candidate_index=matches[0][0],
                window_size=len(window.bars),
            )
            or matches[0][1].trading_day != item.trading_day
            or matches[0][2] != item.contract
            or normalize_contract_for_symbol(window.symbol, item.contract)
            != item.contract
        ):
            raise ValueError("ALERT_EVALUATION_OUTPUT_INVALID")
        seen_bar_ends.add(item.bar_end)
        validated.append(item)
    return tuple(sorted(validated, key=lambda candidate: candidate.bar_end))


def _first_seen_candidate_is_in_repaint_authority(
    *,
    candidate_index: int,
    window_size: int,
) -> bool:
    latest_index = window_size - 1
    if candidate_index == latest_index:
        return True
    return bool(
        window_size >= HTDY_FIRST_SEEN_CONTEXT_BARS
        and candidate_index
        >= latest_index - CONFIGURED_REPAINT_SCAN_ZONE_BARS
    )
