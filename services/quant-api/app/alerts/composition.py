"""Default-off composition for the Alert Runtime."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import json
import os
from functools import partial
from typing import Any

from redis.exceptions import WatchError

from app.alerts.evaluators import HtdyOriginalEvaluator, SubingThsEvaluator
from app.alerts.registry import HTDY_ALERT_RULE_CODE, SUBING_THS_ALERT_RULE_CODE
from app.alerts.notification_composition import build_notification_sender_from_env
from app.alerts.runtime import (
    AlertNotificationAcknowledgeError,
    AlertRuntime,
    acknowledge_notification_failure,
    empty_alert_runtime_status,
    validate_alert_runtime_status,
)
from app.core.env import PROJECT_ROOT
from app.db.session import SessionLocal
from app.market_data.composition import build_database_coverage_source, build_market_read_service
from app.market_data.operational_universe import load_operational_products
from app.market_data.product_taxonomy import load_product_taxonomy
from app.redis_connections import get_redis_connection


ALERT_RUNTIME_ACTIVATION_MARKER = PROJECT_ROOT / ".run" / "alert-runtime-enabled"


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
                payload = payload.decode("utf-8")
            if payload == self._STARTUP_BOUNDARY:
                return tuple(messages)

    def get_message(self, *, timeout_seconds: float) -> tuple[object, object] | None:
        message = self._pubsub.get_message(timeout=timeout_seconds)
        if not isinstance(message, Mapping) or message.get("type") != "pmessage":
            return None
        return message.get("channel"), message.get("data")

    def close(self) -> None:
        self._pubsub.close()


class StreamAlertMessageSource(RedisAlertMessageSource):
    """Durable completed observations; PubSub only carries canonical wake hints."""
    def __init__(self, redis):
        super().__init__(redis)
        from app.market_data.observation_stream import ObservationStream
        self._stream = ObservationStream(redis, kind="completed")
        self.current_observation = None
        self._expected_cursor = None
        self._acknowledged_routes: dict[str, dict[str, object]] = {}
        self._acknowledged_history: dict[str, list[dict[str, object]]] = {}

    def subscribe(self, *patterns):
        super().subscribe("market:state")

    def get_message(self, *, timeout_seconds):
        for day in self._stream.days():
            cursor = self._stream.cursor("alert", day)
            observations = self._stream.read("alert", day, count=1)
            if observations:
                self.current_observation = observations[0]
                self._expected_cursor = cursor
                if not self.current_observation.notification_eligible:
                    self.ack_current()
                    return None
                return self.current_observation.channel, json.dumps(self.current_observation.data)
        self.current_observation = None
        return super().get_message(timeout_seconds=timeout_seconds)

    def ack_current(self):
        envelope = self.current_observation
        if envelope is None:
            raise RuntimeError("ALERT_BUFFER_ACK_INVALID")
        self._stream.ack("alert", envelope.trading_day,
                         expected_cursor=self._expected_cursor, next_id=envelope.stream_id)
        route = self._coverage_route(envelope)
        if route is not None:
            key, evidence = route
            self._acknowledged_routes[key] = evidence
            history = self._acknowledged_history.setdefault(key, [])
            history.append(evidence)
            del history[:-64]
            if len(self._acknowledged_routes) > 1024:
                oldest = next(iter(self._acknowledged_routes))
                self._acknowledged_routes.pop(oldest)
                self._acknowledged_history.pop(oldest, None)
        self.current_observation = None

    @staticmethod
    def _coverage_route(envelope):
        if not envelope.notification_eligible:
            return None
        parts = envelope.channel.split(":")
        bar_end = envelope.data.get("bar_end")
        if len(parts) != 4 or parts[:2] != ["live", "bar"] or not isinstance(bar_end, str):
            return None
        return f"{parts[2]}:{parts[3]}", {
            "trading_day": envelope.trading_day.isoformat(),
            "stream_id": envelope.stream_id,
            "bar_end": bar_end,
            "observation_id": envelope.observation_id,
        }

    def coverage_snapshot(self, *, warming_routes: frozenset[str] = frozenset()) -> dict[str, object]:
        day = self._stream.registered_day("alert")
        cursor = self._stream.cursor("alert", day)
        for key in tuple(self._acknowledged_history):
            if key not in warming_routes:
                self._acknowledged_history.pop(key)
        pending_routes: dict[str, dict[str, object]] = {}
        for envelope in self._stream.read("alert", day, count=128):
            route = self._coverage_route(envelope)
            if route is not None:
                key, evidence = route
                pending_routes.setdefault(key, evidence)
        history_budget = 128
        route_history: dict[str, list[dict[str, object]]] = {}
        for key in sorted(warming_routes):
            rows = self._acknowledged_history.get(key, [])
            if rows and len(rows) <= history_budget:
                route_history[key] = list(rows)
                history_budget -= len(rows)
        return {"trading_day": day.isoformat(), "cursor": cursor,
                "tail": self._stream.tail(day), "routes": dict(self._acknowledged_routes),
                "route_history": route_history,
                "pending_routes": pending_routes}


class RedisAlertHeartbeatStore:
    _UNRESOLVED_KEY = "alert:coverage-unresolved:v2"
    _CLOSEOUT_KEY = "alert:coverage-closeouts:v1"

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    def write(self, payload: dict[str, object], *, ttl_seconds: int) -> None:
        self._redis.set(
            "alert:heartbeat",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            ex=ttl_seconds,
        )

    def read_unresolved(self) -> dict[str, object]:
        raw = self._redis.get(self._UNRESOLVED_KEY)
        if raw is None:
            return {}
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("ALERT_COVERAGE_RECOVERY_INVALID") from exc
        if not isinstance(parsed, Mapping) or parsed.get("schema_version") != 2 or not isinstance(parsed.get("unresolved"), dict):
            raise RuntimeError("ALERT_COVERAGE_RECOVERY_INVALID")
        return parsed["unresolved"]

    def write_unresolved(self, value: dict[str, dict[str, object]]) -> None:
        payload = {"schema_version": 2, "unresolved": value}
        if self._redis.set(self._UNRESOLVED_KEY, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))) is not True:
            raise RuntimeError("ALERT_COVERAGE_PERSIST_FAILED")

    def close_not_due(self, expected, resolutions, *, assert_owned, replacements=None):
        from app.alerts.coverage_closeout import merge_closeout
        with self._redis.pipeline() as pipe:
            pipe.watch(self._UNRESOLVED_KEY, self._CLOSEOUT_KEY)
            raw = pipe.get(self._UNRESOLVED_KEY)
            if raw is not None and len(raw) > 4 * 1024 * 1024:
                raise RuntimeError("ALERT_COVERAGE_CLOSEOUT_INVALID")
            if raw is None or json.loads(raw) != {"schema_version": 2, "unresolved": expected}:
                raise RuntimeError("ALERT_COVERAGE_CLOSEOUT_STALE")
            raw_archive = pipe.get(self._CLOSEOUT_KEY)
            if raw_archive is not None and len(raw_archive) > 8 * 1024 * 1024:
                raise RuntimeError("ALERT_COVERAGE_CLOSEOUT_INVALID")
            archive = json.loads(raw_archive) if raw_archive is not None else {"schema_version": 1, "resolutions": {}}
            remaining, archive = merge_closeout(expected, resolutions, archive, replacements=replacements)
            encoded_archive = json.dumps(archive)
            if len(encoded_archive.encode()) > 8 * 1024 * 1024:
                raise RuntimeError("ALERT_COVERAGE_CLOSEOUT_INVALID")
            assert_owned()
            pipe.multi()
            pipe.set(self._UNRESOLVED_KEY, json.dumps({"schema_version": 2, "unresolved": remaining}))
            pipe.set(self._CLOSEOUT_KEY, encoded_archive)
            if pipe.execute() != [True, True]:
                raise RuntimeError("ALERT_COVERAGE_CLOSEOUT_UNKNOWN")
        return remaining


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
        if self._redis.set(
            "alert:runtime-status",
            json.dumps(normalized, ensure_ascii=False, separators=(",", ":")),
        ) is not True:
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
                json.dumps(updated, ensure_ascii=False, separators=(",", ":")),
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


def acknowledge_alert_notification_failure(expected_failure_at: str) -> dict[str, object]:
    return RedisAlertRuntimeStatusStore(
        get_redis_connection()
    ).acknowledge_notification_failure(
        expected_failure_at=expected_failure_at,
        acknowledged_at=datetime.now(UTC),
    )


def build_alert_runtime(*, assert_owned=None) -> AlertRuntime:
    try:
        enabled = ALERT_RUNTIME_ACTIVATION_MARKER.read_text(encoding="utf-8") == "enabled\n"
    except (OSError, UnicodeDecodeError):
        enabled = False
    if not enabled:
        raise RuntimeError("ALERT_RUNTIME_NOT_ENABLED")
    operational_products = load_operational_products()
    redis = get_redis_connection()
    from app.market_data.live_recovery_guard import recovery_guard

    return AlertRuntime(
        assert_owned=assert_owned,
        live_processing_guard=(partial(recovery_guard, wait=True)
                               if os.getenv("GUIYI_LIVE_RECOVERY_ENABLED", "0") == "1" else None),
        session_factory=SessionLocal,
        market_read_factory=build_alert_market_read_service,
        evaluators={
            HTDY_ALERT_RULE_CODE: HtdyOriginalEvaluator(),
            SUBING_THS_ALERT_RULE_CODE: SubingThsEvaluator(),
        },
        sender=build_notification_sender_from_env(),
        operational_products=operational_products,
        taxonomy=load_product_taxonomy(),
        message_source=(StreamAlertMessageSource(redis) if os.getenv("GUIYI_OBSERVATION_STREAM_ENABLED", "0") == "1" else RedisAlertMessageSource(redis)),
        heartbeat_store=RedisAlertHeartbeatStore(redis),
        runtime_status_store=RedisAlertRuntimeStatusStore(redis),
    )


def build_alert_market_read_service(session):
    """Share Session endpoint assembly only within one rule's read transaction."""
    market = build_market_read_service(session)
    market._market_data.replay_coverage = build_database_coverage_source(session, reuse_session_windows=True)
    return market


def warmup_alert_runtime(*, allow_closed_warming: bool = False, allow_break: bool = False):
    """Verify scoped Market windows and evaluate without Event or transport writes."""
    from sqlalchemy import select
    from app.alerts.models import AlertRule
    from app.alerts.evaluators import AlertEvaluationError
    from app.alerts.registry import SUBING_QUALITY_REWARM_POLICY_V2
    from app.market_data.domain import BarFrequency, SeriesKind, SeriesPageQuery
    from app.market_data.market_read_service import MarketReadWindowError

    def prove_feed_idle(session):
        from app.market_data.composition import build_market_feed_service
        feed = build_market_feed_service(session)
        try:
            if feed.quiescent(datetime.now(UTC)) is not True:
                raise MarketReadWindowError("MARKET_READ_PHASE_UNAVAILABLE")
        finally:
            clients = (getattr(getattr(feed, "_store", None), "_redis", None),
                       getattr(getattr(feed, "source_stream", None), "redis", None))
            closed = set()
            for client in clients:
                if client is not None and id(client) not in closed:
                    closed.add(id(client))
                    client.close()

    runtime = build_alert_runtime()
    count = 0
    warming = []
    try:
        runtime._validate_startup_composition()
        source = runtime.message_source
        if isinstance(source, StreamAlertMessageSource):
            for day in source._stream.days():
                source._stream.cursor("alert", day)
        with runtime._session_factory() as session:
            market = runtime._market_read_factory(session)
            if allow_break:
                prove_feed_idle(session)
                canonical = market.canonical_warmup_reader(
                    datetime.now(UTC), allow_break=True, clock=lambda: datetime.now(UTC))
            else:
                canonical = market.canonical_warmup_reader(datetime.now(UTC))
            for rule in session.scalars(select(AlertRule).where(AlertRule.enabled.is_(True))):
                for symbol, frequencies in rule.scope_product_frequencies.items():
                    for frequency in frequencies:
                        query = SeriesPageQuery(SeriesKind.ACTUAL_DOMINANT, symbol, BarFrequency(frequency))
                        window = canonical.closed_window(query, limit=64,
                            quality_rewarm=rule.rule_code == SUBING_THS_ALERT_RULE_CODE and frequency in {"1d", "1w"})
                        closed_canonical = window is not None
                        reader = canonical if closed_canonical else market
                        if window is None:
                            page = market.history_page(query)
                            if not page.bars:
                                raise RuntimeError("ALERT_WARMUP_INPUT_UNAVAILABLE")
                            latest = page.bars[-1]
                            window = market.bars_until(query, trading_day=latest.trading_day, end=latest.bar_end, limit=64)
                        reader.assert_window_current(window)
                        try:
                            runtime._evaluators[rule.rule_code].evaluate_candidates(reader, window)
                        except AlertEvaluationError as exc:
                            if not (
                                allow_closed_warming is True
                                and closed_canonical and reader is canonical
                                and rule.rule_code == SUBING_THS_ALERT_RULE_CODE
                                and frequency in {"1d", "1w"}
                                and window.input_policy_version == SUBING_QUALITY_REWARM_POLICY_V2
                                and type(exc) is AlertEvaluationError
                                and str(exc) == "ALERT_EVALUATION_WARMING_UP"
                            ):
                                raise
                            # Reprove source/owner after the pure calculation;
                            # warming is never a quality or mapping fallback.
                            reader.assert_window_current(window)
                            warming.append({"rule_code": rule.rule_code, "symbol": symbol,
                                            "frequency": frequency, "contract": window.contract,
                                            "bar_count": len(window.bars)})
                            continue
                        reader.assert_window_current(window)
                        count += 1
            if allow_break:
                prove_feed_idle(session)
        if not count and not warming:
            raise RuntimeError("ALERT_WARMUP_SCOPE_EMPTY")
        return {"calculated": count, "total": count + len(warming), "warming": warming,
                "natural_signals_verified": False}
    finally:
        runtime.message_source.close()
