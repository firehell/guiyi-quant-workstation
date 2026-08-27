"""Alert Runtime 的默认关闭 composition；构造不启动消费循环。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
import json
from typing import Any, TypeVar

from redis.exceptions import WatchError

from app.alerts.evaluators import HtdyOriginalEvaluator
from app.alerts.notification_composition import build_notification_sender_from_env
from app.alerts.runtime import (
    AlertNotificationAcknowledgeError,
    AlertRuntime,
    acknowledge_notification_failure,
    empty_alert_runtime_status,
    validate_alert_runtime_status,
)
from app.alerts.subing_strategy_runtime import (
    SubingStrategyRuntimeEvaluator,
    SubingStrategyRuntimeProductSourceError,
)
from app.core.env import PROJECT_ROOT
from app.db.session import SessionLocal
from app.market_data.composition import (
    build_market_read_service,
    build_subing_strategy_current_service,
)
from app.market_data.aggregation import SessionWindow
from app.market_data.domain import BarFrequency, CanonicalBar
from app.market_data.operational_universe import load_active_products
from app.market_data.operational_universe import load_operational_products
from app.market_data.product_taxonomy import load_product_taxonomy
from app.market_data.subing_strategy.current_service import (
    SubingStrategyCurrentActiveProductError,
    SubingStrategyCurrentProjectionService,
    SubingStrategyCurrentSourceIdentityError,
    SubingStrategyCurrentSourceUnavailableError,
)
from app.market_data.subing_strategy.machine import (
    SubingStrategyMachineState,
    SubingStrategySourceIdentity,
)
from app.market_data.subing_strategy.stream_contracts import (
    AuthoritativeSegmentTerminal,
)
from app.redis_connections import get_redis_connection


ALERT_RUNTIME_ACTIVATION_MARKER = PROJECT_ROOT / ".run" / "alert-runtime-enabled"
_ReadResult = TypeVar("_ReadResult")


class _SubingStrategyRuntimeReader:
    """Open one read-only session per active-product reconstruction operation."""

    def __init__(
        self,
        *,
        session_factory=SessionLocal,
        service_factory=build_subing_strategy_current_service,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._service_factory = service_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def restore(
        self,
        *,
        symbol: str,
        started_at: datetime,
    ) -> SubingStrategyMachineState:
        return self._read(
            lambda service: service.restore_machine(symbol=symbol, now=started_at)
        )

    def restore_rollover(
        self,
        *,
        symbol: str,
        trading_day: date,
        previous_identity: SubingStrategySourceIdentity,
        terminal: AuthoritativeSegmentTerminal,
    ) -> SubingStrategyMachineState:
        if (
            terminal.symbol != symbol
            or terminal.contract != previous_identity.contract
            or terminal.segment_start_trading_day
            != previous_identity.segment_start_trading_day
            or terminal.terminal_bar.trading_day >= trading_day
        ):
            raise SubingStrategyRuntimeProductSourceError()
        return self._read(
            lambda service: service.restore_machine(
                symbol=symbol,
                now=self._clock(),
            )
        )

    def read_completed_bars(
        self,
        *,
        symbol: str,
        source_identity: SubingStrategySourceIdentity,
        after_1m: datetime | None,
        after_5m: datetime | None,
        after_15m: datetime | None,
        through: datetime,
    ) -> dict[BarFrequency, tuple[CanonicalBar, ...]]:
        return dict(
            self._read(
                lambda service: service.completed_live_after(
                    symbol=symbol,
                    source_identity=source_identity,
                    after_1m=after_1m,
                    after_5m=after_5m,
                    after_15m=after_15m,
                    through=through,
                )
            )
        )

    def read_session_windows(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> tuple[SessionWindow, ...]:
        return self._read(
            lambda service: service.session_windows(
                symbol=symbol,
                trading_day=trading_day,
                source_identity=source_identity,
            )
        )

    def read_authoritative_terminal(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> AuthoritativeSegmentTerminal | None:
        return self._read(
            lambda service: service.authoritative_terminal(
                symbol=symbol,
                trading_day=trading_day,
                source_identity=source_identity,
            )
        )

    def _read(
        self,
        operation: Callable[
            [SubingStrategyCurrentProjectionService],
            _ReadResult,
        ],
    ) -> _ReadResult:
        try:
            with self._session_factory() as session:
                service: SubingStrategyCurrentProjectionService = self._service_factory(
                    session
                )
                return operation(service)
        except (
            SubingStrategyCurrentActiveProductError,
            SubingStrategyCurrentSourceIdentityError,
            SubingStrategyCurrentSourceUnavailableError,
        ) as exc:
            raise SubingStrategyRuntimeProductSourceError() from exc


class RedisAlertMessageSource:
    _STARTUP_BOUNDARY = "alert-runtime-startup-boundary-v1"

    def __init__(self, redis: Any) -> None:
        self._pubsub = redis.pubsub(ignore_subscribe_messages=False)

    def subscribe(self, *patterns: str) -> None:
        self._pubsub.psubscribe(*patterns)

    def drain_startup_messages(self) -> tuple[tuple[object, object], ...]:
        self._pubsub.ping(self._STARTUP_BOUNDARY)
        messages: list[tuple[object, object]] = []
        while True:
            message = self._pubsub.get_message(timeout=1.0)
            if not isinstance(message, Mapping):
                raise RuntimeError("ALERT_RUNTIME_STARTUP_BOUNDARY_UNAVAILABLE")
            if message.get("type") == "pmessage":
                messages.append((message.get("channel"), message.get("data")))
                continue
            if message.get("type") != "pong":
                continue
            payload = message.get("data")
            if isinstance(payload, bytes):
                try:
                    payload = payload.decode("utf-8")
                except UnicodeError:
                    raise RuntimeError(
                        "ALERT_RUNTIME_STARTUP_BOUNDARY_UNAVAILABLE"
                    ) from None
            if payload == self._STARTUP_BOUNDARY:
                return tuple(messages)

    def get_message(self, *, timeout_seconds: float) -> tuple[object, object] | None:
        message = self._pubsub.get_message(timeout=timeout_seconds)
        if not isinstance(message, Mapping) or message.get("type") != "pmessage":
            return None
        return message.get("channel"), message.get("data")

    def close(self) -> None:
        self._pubsub.close()


class RedisAlertHeartbeatStore:
    def __init__(self, redis: Any) -> None:
        self._redis = redis

    def write(self, payload: dict[str, object], *, ttl_seconds: int) -> None:
        self._redis.set(
            "alert:heartbeat",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            ex=ttl_seconds,
        )


class RedisAlertRuntimeStatusStore:
    def __init__(self, redis: Any) -> None:
        self._redis = redis

    def read(self) -> dict[str, object]:
        raw = self._redis.get("alert:runtime-status")
        if raw is None:
            return empty_alert_runtime_status()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        parsed = json.loads(raw)
        if not isinstance(parsed, Mapping):
            raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
        return validate_alert_runtime_status(parsed)

    def write(self, payload: dict[str, object]) -> None:
        normalized = validate_alert_runtime_status(payload)
        persisted = self._redis.set(
            "alert:runtime-status",
            json.dumps(normalized, ensure_ascii=False, separators=(",", ":")),
        )
        if persisted is not True:
            raise RuntimeError("ALERT_RUNTIME_STATUS_WRITE_FAILED")

    def acknowledge_notification_failure(
        self,
        *,
        expected_failure_at: str,
        acknowledged_at: datetime,
    ) -> dict[str, object]:
        return self._atomic_mutate(
            lambda current: acknowledge_notification_failure(
                current,
                expected_failure_at=expected_failure_at,
                acknowledged_at=acknowledged_at,
            )
        )

    def update(self, changes: dict[str, object]) -> dict[str, object]:
        return self._atomic_mutate(
            lambda current: validate_alert_runtime_status({**current, **changes})
        )

    def _atomic_mutate(
        self,
        mutation: Callable[[dict[str, object]], dict[str, object]],
    ) -> dict[str, object]:
        pipeline = self._redis.pipeline()
        try:
            pipeline.watch("alert:runtime-status")
            raw = pipeline.get("alert:runtime-status")
            if raw is None:
                current = empty_alert_runtime_status()
            else:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                parsed = json.loads(raw)
                if not isinstance(parsed, Mapping):
                    raise ValueError("ALERT_RUNTIME_STATUS_INVALID")
                current = validate_alert_runtime_status(parsed)
            updated = mutation(current)
            pipeline.multi()
            pipeline.set(
                "alert:runtime-status",
                json.dumps(
                    updated,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
            if pipeline.execute() != [True]:
                raise RuntimeError("ALERT_RUNTIME_STATUS_WRITE_FAILED")
            return updated
        except WatchError as exc:
            raise AlertNotificationAcknowledgeError(
                "ALERT_RUNTIME_STATUS_CHANGED"
            ) from exc
        finally:
            pipeline.reset()


def acknowledge_alert_notification_failure(
    expected_failure_at: str,
) -> dict[str, object]:
    return RedisAlertRuntimeStatusStore(
        get_redis_connection()
    ).acknowledge_notification_failure(
        expected_failure_at=expected_failure_at,
        acknowledged_at=datetime.now(UTC),
    )


def build_alert_runtime() -> AlertRuntime:
    """构造已显式 activation 的 Alert Runtime；缺 Gate 时保持关闭。"""
    try:
        enabled = (
            ALERT_RUNTIME_ACTIVATION_MARKER.read_text(encoding="utf-8") == "enabled\n"
        )
    except (OSError, UnicodeDecodeError):
        enabled = False
    if not enabled:
        raise RuntimeError("ALERT_RUNTIME_NOT_ENABLED")
    operational_products = load_operational_products()
    taxonomy = load_product_taxonomy()
    sender = build_notification_sender_from_env()
    redis = get_redis_connection()
    strategy_reader = _SubingStrategyRuntimeReader()
    return AlertRuntime(
        session_factory=SessionLocal,
        market_read_factory=build_market_read_service,
        strategy_evaluator=SubingStrategyRuntimeEvaluator(
            load_active_products(),
            restore_reader=strategy_reader,
            current_reader=strategy_reader,
        ),
        htdy_evaluator=HtdyOriginalEvaluator(),
        sender=sender,
        operational_products=operational_products,
        taxonomy=taxonomy,
        message_source=RedisAlertMessageSource(redis),
        heartbeat_store=RedisAlertHeartbeatStore(redis),
        runtime_status_store=RedisAlertRuntimeStatusStore(redis),
    )
