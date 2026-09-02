"""Single-process, forward-only HTDY Alert orchestration."""

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
    AlertEvaluationError,
    AlertEvaluator,
    AlertObservationCandidate,
)
from app.alerts.models import AlertRule
from app.alerts.notification import (
    AlertNotificationMessage,
    AlertNotificationSender,
    ProviderAcceptance,
)
from app.alerts.registry import (
    AlertEventMode,
    HTDY_ALERT_RULE_CODE,
    SUBING_THS_ALERT_RULE_CODE,
    alert_rule_definitions,
    get_alert_rule_definition,
)
from app.alerts.service import AlertEventCreate, AlertService
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


class AlertNotificationAcknowledgeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AlertMessageSource(Protocol):
    def subscribe(self, *patterns: str) -> None: ...
    def drain_startup_messages(self) -> tuple[tuple[object, object], ...]: ...
    def get_message(self, *, timeout_seconds: float) -> tuple[object, object] | None: ...
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


def _persist_candidate_and_prepare_notification(
    service: AlertService,
    *,
    taxonomy: Mapping[str, ProductTaxonomyEntry],
    rule: AlertRule,
    symbol: str,
    frequency: str,
    candidate: AlertObservationCandidate,
    processing_now: datetime,
) -> _PreparedEvent:
    create = AlertEventCreate(
        rule_id=rule.id,
        symbol=symbol,
        contract=candidate.contract,
        trading_day=candidate.trading_day,
        frequency=frequency,
        bar_end=candidate.bar_end,
        result_codes=candidate.observation_types,
        detected_at=processing_now,
        notification_attempted_at=processing_now,
    )
    if get_alert_rule_definition(rule.rule_code).event_mode is AlertEventMode.FIRST_SEEN:
        created = service.create_first_seen_observation_event(create)
    else:
        created = service.create_event(create)
    if created is None:
        return _PreparedEvent(False, None, None)
    taxonomy_entry = taxonomy.get(symbol)
    if taxonomy_entry is None:
        return _PreparedEvent(True, None, NOTIFICATION_PREPARATION_FAILURE)
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


class AlertRuntime:
    def __init__(
        self,
        *,
        session_factory: AlertSessionFactory,
        market_read_factory: AlertMarketReadFactory,
        htdy_evaluator: AlertEvaluator | None = None,
        evaluators: Mapping[str, AlertEvaluator] | None = None,
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
        self._evaluators = dict(evaluators or {})
        if htdy_evaluator is not None:
            self._evaluators.setdefault(HTDY_ALERT_RULE_CODE, htdy_evaluator)
        self._htdy_evaluator = self._evaluators.get(HTDY_ALERT_RULE_CODE)
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
        if self.message_source is None or self.heartbeat_store is None:
            raise RuntimeError("ALERT_RUNTIME_TRANSPORT_UNAVAILABLE")
        self._current_runtime_status()
        self._validate_startup_composition()
        self.message_source.subscribe(_LIVE_BAR_PATTERN, _MARKET_STATE_PATTERN)
        for startup_message in self.message_source.drain_startup_messages():
            self.process_message(*startup_message, emit_events=False)
        next_heartbeat = self._aware_now()
        try:
            while not self.stop_requested():
                now = self._aware_now()
                if now >= next_heartbeat:
                    self._write_heartbeat(now)
                    next_heartbeat = now + _HEARTBEAT_INTERVAL
                runtime_message = self.message_source.get_message(timeout_seconds=1.0)
                if runtime_message is not None:
                    self.process_message(*runtime_message)
        finally:
            self.message_source.close()

    def _validate_startup_composition(self) -> None:
        expected = tuple(
            sorted(definition.rule_code for definition in alert_rule_definitions())
        )
        try:
            with self._session_factory() as session:
                rules = session.scalars(select(AlertRule).order_by(AlertRule.rule_code)).all()
                if tuple(rule.rule_code for rule in rules) != expected:
                    raise ValueError("rule registry mismatch")
                service = AlertService(
                    session,
                    operational_products=tuple(sorted(self._operational_products)),
                )
                for symbol in sorted(self._operational_products):
                    if tuple(state.rule_code for state in service.product_rules(symbol)) != expected:
                        raise ValueError("rule projection mismatch")
                if session.in_transaction():
                    session.rollback()
        except Exception:
            raise RuntimeError("ALERT_RUNTIME_COMPOSITION_INVALID") from None

    def process_message(
        self,
        channel: object,
        payload: object,
        *,
        emit_events: bool = True,
    ) -> None:
        live = _parse_live_bar_trigger(channel, payload)
        if live is not None:
            if emit_events:
                self._process_live(live)
            return
        canonical = _parse_canonical_updated_trigger(channel, payload)
        if canonical is not None and emit_events:
            self._process_canonical_updated(canonical)

    def _process_live(self, trigger: _LiveBarTrigger) -> None:
        if trigger.symbol not in self._operational_products:
            return
        processing_now = self._aware_now()
        messages: list[AlertNotificationMessage] = []
        event_count = 0
        failed = False
        try:
            with self._session_factory() as session:
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
                market_read = self._market_read_factory(session)
                for rule in rules:
                    try:
                        definition = get_alert_rule_definition(rule.rule_code)
                        evaluator = self._evaluators.get(rule.rule_code)
                        if evaluator is None:
                            raise ValueError("ALERT_EVALUATOR_MISSING")
                        if trigger.frequency.value not in definition.input_frequencies:
                            continue
                        if not service.rule_allows_event(
                            rule,
                            symbol=trigger.symbol,
                            frequency=trigger.frequency.value,
                        ):
                            continue
                        window = market_read.bars_until(
                            SeriesPageQuery(
                                SeriesKind.ACTUAL_DOMINANT,
                                trigger.symbol,
                                trigger.frequency,
                            ),
                            trading_day=trigger.bar.trading_day,
                            end=trigger.bar.bar_end,
                            limit=64,
                        )
                        if not _window_matches_event(
                            window,
                            symbol=trigger.symbol,
                            event_frequency=trigger.frequency,
                            event_bar=trigger.bar,
                        ):
                            continue
                        candidates = _validated_candidates(
                            evaluator.evaluate_candidates(market_read, window),
                            window=window,
                            event_mode=definition.event_mode,
                        )
                        rule_event_created = False
                        for candidate in candidates:
                            prepared = _persist_candidate_and_prepare_notification(
                                service,
                                taxonomy=self._taxonomy,
                                rule=rule,
                                symbol=trigger.symbol,
                                frequency=trigger.frequency.value,
                                candidate=candidate,
                                processing_now=processing_now,
                            )
                            if prepared.event_created:
                                event_count += 1
                                rule_event_created = True
                            if prepared.notification_error_type is not None:
                                self._record_notification_failure(
                                    at=processing_now,
                                    error_type=prepared.notification_error_type,
                                )
                            if prepared.message is not None:
                                messages.append(prepared.message)
                        self._record_rule_result(
                            rule.rule_code,
                            evaluated_bar_at=window.cutoff,
                            at=processing_now,
                            event_created=rule_event_created,
                            error_type=None,
                        )
                    except AlertEvaluationError as exc:
                        if session.in_transaction():
                            session.rollback()
                        self._record_rule_result(
                            rule.rule_code,
                            evaluated_bar_at=None,
                            at=processing_now,
                            event_created=False,
                            error_type=_rule_error_type(str(exc)),
                        )
                    except Exception:
                        if session.in_transaction():
                            session.rollback()
                        failed = True
                        _LOGGER.warning("ALERT_RULE_PROCESSING_FAILED")
                if session.in_transaction():
                    session.rollback()
        except Exception:
            failed = True
            messages.clear()
            _LOGGER.warning("ALERT_PROCESSING_FAILED")
        if event_count:
            self._update_runtime_status(last_event_at=_iso_timestamp(processing_now))
        self._record_processing_result(
            processing_now=processing_now,
            bar_at=trigger.bar.bar_end,
            failed=failed,
        )
        if not failed or messages:
            self._send_messages_once(messages, processing_now=processing_now)

    def _process_canonical_updated(self, trigger: _CanonicalUpdatedTrigger) -> None:
        processing_now = self._aware_now()
        messages: list[AlertNotificationMessage] = []
        event_count = 0
        failed = False
        try:
            with self._session_factory() as session:
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
                    definition = get_alert_rule_definition(rule.rule_code)
                    evaluator = self._evaluators.get(rule.rule_code)
                    if evaluator is None:
                        failed = True
                        _LOGGER.warning("ALERT_RULE_PROCESSING_FAILED")
                        continue
                    market_read = self._market_read_factory(session)
                    for symbol in sorted(self._operational_products):
                        for frequency in _CANONICAL_ALERT_FREQUENCIES:
                            try:
                                if frequency.value not in definition.input_frequencies:
                                    continue
                                if not service.rule_allows_event(
                                    rule, symbol=symbol, frequency=frequency.value
                                ):
                                    continue
                                window = market_read.latest_canonical_window(
                                    SeriesPageQuery(
                                        SeriesKind.ACTUAL_DOMINANT,
                                        symbol,
                                        frequency,
                                    ),
                                    trading_day=trigger.trading_day,
                                    limit=64,
                                )
                                if not _canonical_window_matches_trigger(
                                    window,
                                    symbol=symbol,
                                    frequency=frequency,
                                    trading_day=trigger.trading_day,
                                ):
                                    continue
                                candidates = _validated_candidates(
                                    evaluator.evaluate_candidates(market_read, window),
                                    window=window,
                                    event_mode=definition.event_mode,
                                )
                                rule_event_created = False
                                for candidate in candidates:
                                    prepared = _persist_candidate_and_prepare_notification(
                                        service,
                                        taxonomy=self._taxonomy,
                                        rule=rule,
                                        symbol=symbol,
                                        frequency=frequency.value,
                                        candidate=candidate,
                                        processing_now=processing_now,
                                    )
                                    if prepared.event_created:
                                        event_count += 1
                                        rule_event_created = True
                                    if prepared.notification_error_type is not None:
                                        self._record_notification_failure(
                                            at=processing_now,
                                            error_type=prepared.notification_error_type,
                                        )
                                    if prepared.message is not None:
                                        messages.append(prepared.message)
                                self._record_rule_result(
                                    rule.rule_code,
                                    evaluated_bar_at=window.cutoff,
                                    at=processing_now,
                                    event_created=rule_event_created,
                                    error_type=None,
                                )
                            except AlertEvaluationError as exc:
                                if session.in_transaction():
                                    session.rollback()
                                self._record_rule_result(
                                    rule.rule_code,
                                    evaluated_bar_at=None,
                                    at=processing_now,
                                    event_created=False,
                                    error_type=_rule_error_type(str(exc)),
                                )
                            except Exception:
                                if session.in_transaction():
                                    session.rollback()
                                failed = True
                                _LOGGER.warning("ALERT_RULE_PROCESSING_FAILED")
                if session.in_transaction():
                    session.rollback()
        except Exception:
            failed = True
            messages.clear()
            _LOGGER.warning("ALERT_PROCESSING_FAILED")
        if event_count:
            self._update_runtime_status(last_event_at=_iso_timestamp(processing_now))
        self._record_processing_result(
            processing_now=processing_now,
            bar_at=None,
            failed=failed,
        )
        if not failed or messages:
            self._send_messages_once(messages, processing_now=processing_now)

    def _record_processing_result(
        self,
        *,
        processing_now: datetime,
        bar_at: datetime | None,
        failed: bool,
    ) -> None:
        common = {"last_processed_bar_at": _iso_timestamp(bar_at) if bar_at else None}
        if failed:
            self._update_runtime_status(
                **common,
                last_processing_failure_at=_iso_timestamp(processing_now),
                processing_error_type=PROCESSING_FAILURE,
            )
        else:
            self._update_runtime_status(
                **common,
                last_processing_success_at=_iso_timestamp(processing_now),
                processing_error_type=None,
            )

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
            except Exception:
                self._record_notification_failure(
                    at=processing_now,
                    error_type=NOTIFICATION_TRANSPORT_FAILURE,
                )
                continue
            if not isinstance(acceptance, ProviderAcceptance):
                self._record_notification_failure(
                    at=processing_now,
                    error_type=NOTIFICATION_ACCEPTANCE_INVALID,
                )
                continue
            self._update_runtime_status(
                last_provider_accepted_at=_iso_timestamp(processing_now),
                consecutive_notification_failures=0,
            )

    def _write_heartbeat(self, now: datetime) -> None:
        assert self.heartbeat_store is not None
        with self._session_factory() as session:
            enabled = session.scalars(
                select(AlertRule).where(AlertRule.enabled.is_(True))
            ).all()
            service = AlertService(
                session,
                operational_products=tuple(sorted(self._operational_products)),
            )
            scope = {
                symbol
                for rule in enabled
                for symbol in self._operational_products
                if any(
                    service.rule_allows_event(
                        rule,
                        symbol=symbol,
                        frequency=frequency,
                    )
                    for frequency in get_alert_rule_definition(
                        rule.rule_code
                    ).input_frequencies
                )
            }
            if session.in_transaction():
                session.rollback()
        self.heartbeat_store.write(
            {
                "generated_at": now.astimezone(UTC).isoformat(),
                "available": True,
                "enabled_rule_count": len(enabled),
                "scope_product_count": len(scope),
            },
            ttl_seconds=_HEARTBEAT_TTL_SECONDS,
        )

    def _aware_now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise RuntimeError("ALERT_RUNTIME_CLOCK_INVALID")
        return now.astimezone(UTC)

    def _record_notification_failure(self, *, at: datetime, error_type: str) -> None:
        status = self._current_runtime_status()
        self._update_runtime_status(
            last_notification_failure_at=_iso_timestamp(at),
            notification_acknowledged_at=None,
            notification_error_type=error_type,
            consecutive_notification_failures=(
                cast(int, status["consecutive_notification_failures"]) + 1
            ),
        )

    def _record_rule_result(
        self,
        rule_code: str,
        *,
        evaluated_bar_at: datetime | None,
        at: datetime,
        event_created: bool,
        error_type: str | None,
    ) -> None:
        status = self._current_runtime_status()
        rule_status = dict(cast(Mapping[str, object], status["rule_status"]))
        current = dict(cast(Mapping[str, object], rule_status[rule_code]))
        if error_type is None:
            current["last_evaluated_bar_at"] = _iso_timestamp(evaluated_bar_at) if evaluated_bar_at else None
            current["error_type"] = None
        else:
            current["last_failure_at"] = _iso_timestamp(at)
            current["error_type"] = error_type
        if event_created:
            current["last_event_at"] = _iso_timestamp(at)
        rule_status[rule_code] = current
        self._update_runtime_status(rule_status=rule_status)

    def _current_runtime_status(self) -> dict[str, object]:
        if self._runtime_status is None:
            self._runtime_status = (
                empty_alert_runtime_status()
                if self.runtime_status_store is None
                else validate_alert_runtime_status(self.runtime_status_store.read())
            )
        return self._runtime_status

    def _update_runtime_status(self, **changes: object) -> None:
        if self.runtime_status_store is None:
            self._runtime_status = validate_alert_runtime_status(
                {**self._current_runtime_status(), **changes}
            )
            return
        atomic_update = getattr(self.runtime_status_store, "update", None)
        if callable(atomic_update):
            self._runtime_status = validate_alert_runtime_status(
                atomic_update(dict(changes))
            )
            return
        normalized = validate_alert_runtime_status(
            {**self._current_runtime_status(), **changes}
        )
        self.runtime_status_store.write(normalized)
        self._runtime_status = normalized


_STATUS_FIELDS = frozenset(
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
        "notification_acknowledged_at",
        "notification_error_type",
        "consecutive_notification_failures",
        "rule_status",
    }
)
_TIMESTAMP_FIELDS = _STATUS_FIELDS - {
    "schema_version",
    "processing_error_type",
    "notification_error_type",
    "consecutive_notification_failures",
    "rule_status",
}
_RULE_STATUS_FIELDS = frozenset(
    {"last_evaluated_bar_at", "last_event_at", "last_failure_at", "error_type"}
)
_RULE_ERROR_TYPES = frozenset(
    {None, "evaluation_input_invalid", "evaluation_warming_up", "evaluation_failed"}
)


def empty_alert_runtime_status() -> dict[str, object]:
    return {
        "schema_version": 6,
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
        "rule_status": {
            rule_code: {
                "last_evaluated_bar_at": None,
                "last_event_at": None,
                "last_failure_at": None,
                "error_type": None,
            }
            for rule_code in (HTDY_ALERT_RULE_CODE, SUBING_THS_ALERT_RULE_CODE)
        },
    }


def validate_alert_runtime_status(payload: Mapping[str, object]) -> dict[str, object]:
    if type(payload.get("schema_version")) is not int:
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    version = cast(int, payload["schema_version"])
    if version == 6 and set(payload) == _STATUS_FIELDS:
        normalized = dict(payload)
    elif version in {1, 2, 3, 4, 5}:
        base = empty_alert_runtime_status()
        normalized = {
            **base,
            **{key: payload[key] for key in _STATUS_FIELDS - {"schema_version"} if key in payload},
        }
    else:
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    normalized["schema_version"] = 6
    for field in _TIMESTAMP_FIELDS:
        value = normalized[field]
        if value is not None:
            if not isinstance(value, str):
                raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
            try:
                normalized[field] = _iso_timestamp(datetime.fromisoformat(value))
            except ValueError:
                raise ValueError("ALERT_RUNTIME_STATUS_INVALID") from None
    if normalized["processing_error_type"] not in {None, PROCESSING_FAILURE}:
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    if normalized["notification_error_type"] not in {
        None,
        NOTIFICATION_PREPARATION_FAILURE,
        NOTIFICATION_TRANSPORT_FAILURE,
        NOTIFICATION_ACCEPTANCE_INVALID,
    }:
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    count = normalized["consecutive_notification_failures"]
    if type(count) is not int or count < 0:
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    if (
        normalized["notification_acknowledged_at"] is not None
        and normalized["last_notification_failure_at"] is None
    ):
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    rule_status = normalized["rule_status"]
    if not isinstance(rule_status, Mapping) or set(rule_status) != {
        HTDY_ALERT_RULE_CODE,
        SUBING_THS_ALERT_RULE_CODE,
    }:
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    normalized_rule_status: dict[str, dict[str, object]] = {}
    for rule_code, value in rule_status.items():
        if not isinstance(value, Mapping) or set(value) != _RULE_STATUS_FIELDS:
            raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
        item = dict(value)
        for field in _RULE_STATUS_FIELDS - {"error_type"}:
            timestamp = item[field]
            if timestamp is not None:
                if not isinstance(timestamp, str):
                    raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
                try:
                    item[field] = _iso_timestamp(datetime.fromisoformat(timestamp))
                except ValueError:
                    raise ValueError("ALERT_RUNTIME_STATUS_INVALID") from None
        if item["error_type"] not in _RULE_ERROR_TYPES:
            raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
        normalized_rule_status[rule_code] = item
    normalized["rule_status"] = normalized_rule_status
    return normalized


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
    if normalized["notification_acknowledged_at"] is not None:
        raise AlertNotificationAcknowledgeError(
            "ALERT_NOTIFICATION_FAILURE_ALREADY_ACKNOWLEDGED"
        )
    acknowledgement = _iso_timestamp(acknowledged_at)
    if datetime.fromisoformat(acknowledgement) < datetime.fromisoformat(
        cast(str, failure_at)
    ):
        raise AlertNotificationAcknowledgeError(
            "ALERT_NOTIFICATION_ACKNOWLEDGEMENT_TIME_INVALID"
        )
    return validate_alert_runtime_status(
        {**normalized, "notification_acknowledged_at": acknowledgement}
    )


def _iso_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
    return value.astimezone(UTC).isoformat()


def _rule_error_type(code: str) -> str:
    return {
        "ALERT_EVALUATION_INPUT_INVALID": "evaluation_input_invalid",
        "ALERT_EVALUATION_WARMING_UP": "evaluation_warming_up",
    }.get(code, "evaluation_failed")


def _parse_live_bar_trigger(channel: object, payload: object) -> _LiveBarTrigger | None:
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
            turnover=None if raw["turnover"] is None else Decimal(str(raw["turnover"])),
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
    channel: object, payload: object
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
        raw_day = raw.get("trading_day")
        if not isinstance(raw_day, str):
            return None
        trading_day = date.fromisoformat(raw_day)
        if raw_day != trading_day.isoformat():
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


def _validated_candidates(
    value: object,
    *,
    window: MarketReadWindow,
    event_mode: AlertEventMode,
) -> tuple[AlertObservationCandidate, ...]:
    if type(value) is not tuple:
        raise ValueError("ALERT_EVALUATION_OUTPUT_INVALID")
    candidates = cast(tuple[object, ...], value)
    validated: list[AlertObservationCandidate] = []
    seen: set[datetime] = set()
    for item in candidates:
        if not isinstance(item, AlertObservationCandidate):
            raise ValueError("ALERT_EVALUATION_OUTPUT_INVALID")
        if (
            item.bar_end in seen
            or type(item.observation_types) is not tuple
            or item.observation_types not in (("buy",), ("sell",), ("buy", "sell"))
            or (event_mode is AlertEventMode.EXACT and item.observation_types not in (("buy",), ("sell",)))
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
            or matches[0][0] != len(window.bars) - 1
            or matches[0][1].trading_day != item.trading_day
            or matches[0][2] != item.contract
            or normalize_contract_for_symbol(window.symbol, item.contract) != item.contract
        ):
            raise ValueError("ALERT_EVALUATION_OUTPUT_INVALID")
        seen.add(item.bar_end)
        validated.append(item)
    return tuple(sorted(validated, key=lambda candidate: candidate.bar_end))
