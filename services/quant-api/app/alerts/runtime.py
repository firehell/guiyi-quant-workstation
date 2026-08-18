"""Alert V2 的单前台、无 replay 规则编排循环。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, DecimalException
import json
import logging
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.evaluators import AlertEvaluation, AlertEvaluator
from app.alerts.models import AlertRule
from app.alerts.notification import AlertNotificationMessage, AlertNotificationSender
from app.alerts.registry import get_alert_rule_definition
from app.alerts.service import AlertEventCreate, AlertService
from app.market_data.aggregation import SessionWindow, bucket_window_for_bar
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
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
_PATTERN = "live:bar:*:*"
_HEARTBEAT_INTERVAL = timedelta(seconds=10)
_HEARTBEAT_TTL_SECONDS = 30
_HTDY_RULE_CODE = "htdy_original_15m"
_SUBING_RULE_CODE = "subing_entry_signal_v1"


class AlertMessageSource(Protocol):
    def subscribe(self, pattern: str) -> None: ...
    def get_message(self, *, timeout_seconds: float) -> tuple[object, object] | None: ...
    def close(self) -> None: ...


class AlertHeartbeatStore(Protocol):
    def write(self, payload: dict[str, object], *, ttl_seconds: int) -> None: ...


AlertSessionFactory = Callable[[], AbstractContextManager[Session]]
AlertMarketReadFactory = Callable[[Session], MarketReadService]
AlertSubingReadFactory = Callable[[Session], SubingReadService]


@dataclass(frozen=True, slots=True)
class _RuleResult:
    contract: str
    frequency: str
    result_codes: tuple[str, ...]
    lower_tf_confirmation: bool


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
        self.clock = clock or (lambda: datetime.now(UTC))
        self.stop_requested = stop_requested or (lambda: False)

    def run_forever(self) -> None:
        """只消费启动后新到达的 completed 5m/15m Pub/Sub 消息。"""
        if self.message_source is None or self.heartbeat_store is None:
            raise RuntimeError("ALERT_RUNTIME_TRANSPORT_UNAVAILABLE")
        self.message_source.subscribe(_PATTERN)
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
        """处理单条完成 Bar；Rule 故障隔离，Event 提交后只发送一次。"""
        parsed = _parse_event(channel, payload)
        if parsed is None:
            return
        symbol, event_frequency, event_bar = parsed
        if symbol not in self._operational_products:
            return
        try:
            processing_now = self._aware_now()
        except Exception:  # noqa: BLE001 - collapse clock detail
            _LOGGER.warning("ALERT_PROCESSING_FAILED")
            return

        messages: list[AlertNotificationMessage] = []
        try:
            with self._session_factory() as session:
                try:
                    rules = session.scalars(
                        select(AlertRule)
                        .where(AlertRule.enabled.is_(True))
                        .order_by(AlertRule.rule_code)
                        .execution_options(populate_existing=True)
                    ).all()
                    for rule in rules:
                        try:
                            definition = get_alert_rule_definition(rule.rule_code)
                            if (
                                event_frequency.value
                                not in definition.input_frequencies
                                or symbol not in set(rule.scope_products or [])
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
                            created = AlertService(
                                session,
                                operational_products=tuple(
                                    sorted(self._operational_products)
                                ),
                            ).create_event(
                                AlertEventCreate(
                                    rule_id=rule.id,
                                    symbol=symbol,
                                    contract=result.contract,
                                    trading_day=event_bar.trading_day,
                                    frequency=result.frequency,
                                    bar_end=event_bar.bar_end,
                                    result_codes=result.result_codes,
                                    lower_tf_confirmation=(
                                        result.lower_tf_confirmation
                                    ),
                                    detected_at=processing_now,
                                    notification_attempted_at=processing_now,
                                )
                            )
                            if created is None:
                                continue
                            taxonomy = self._taxonomy.get(symbol)
                            if taxonomy is None:
                                _LOGGER.warning("ALERT_PRODUCT_NAME_UNAVAILABLE")
                                continue
                            messages.append(
                                AlertNotificationMessage(
                                    rule_code=definition.rule_code,
                                    symbol=symbol,
                                    product_name=taxonomy.name,
                                    contract=result.contract,
                                    frequency=result.frequency,
                                    bar_end=event_bar.bar_end,
                                    result_codes=result.result_codes,
                                    lower_tf_confirmation=(
                                        result.lower_tf_confirmation
                                    ),
                                )
                            )
                        except Exception:  # noqa: BLE001 - isolate each fixed rule
                            if session.in_transaction():
                                session.rollback()
                            _LOGGER.warning("ALERT_RULE_PROCESSING_FAILED")
                finally:
                    if session.in_transaction():
                        session.rollback()
        except Exception:  # noqa: BLE001 - DB/session failure must not send
            _LOGGER.warning("ALERT_PROCESSING_FAILED")
            return

        for message in messages:
            try:
                self._sender.send(message)
            except Exception:  # noqa: BLE001 - committed Event is never retried
                _LOGGER.warning("ALERT_NOTIFICATION_FAILED")

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
        if rule_code == _HTDY_RULE_CODE:
            return self._evaluate_htdy(session, symbol=symbol, event_bar=event_bar)
        if rule_code == _SUBING_RULE_CODE:
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
        event_bar: CanonicalBar,
    ) -> _RuleResult | None:
        window = self._market_read_factory(session).bars_until(
            SeriesPageQuery(
                SeriesKind.ACTUAL_DOMINANT,
                symbol,
                BarFrequency.M15,
            ),
            trading_day=event_bar.trading_day,
            end=event_bar.bar_end,
            limit=32,
        )
        if not _window_matches_event(window, symbol=symbol, event_bar=event_bar):
            return None
        evaluation = self._htdy_evaluator.evaluate(window)
        if (
            not isinstance(evaluation, AlertEvaluation)
            or not evaluation.observation_types
        ):
            return None
        return _RuleResult(
            contract=window.contract,
            frequency=BarFrequency.M15.value,
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
                scope = {
                    symbol
                    for rule in enabled
                    for symbol in (rule.scope_products or [])
                    if symbol in self._operational_products
                }
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


def _parse_event(
    channel: object,
    payload: object,
) -> tuple[str, BarFrequency, CanonicalBar] | None:
    try:
        if isinstance(channel, bytes):
            channel = channel.decode("utf-8")
        if not isinstance(channel, str):
            return None
        parts = channel.split(":")
        if len(parts) != 4 or parts[:2] != ["live", "bar"]:
            return None
        frequency = BarFrequency(parts[3])
        if frequency not in {BarFrequency.M5, BarFrequency.M15}:
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
    return symbol, frequency, bar


def _window_matches_event(
    window: MarketReadWindow,
    *,
    symbol: str,
    event_bar: CanonicalBar,
) -> bool:
    return bool(
        window.symbol == symbol
        and window.series_kind == "actual_dominant"
        and window.frequency == "15m"
        and window.trading_day == event_bar.trading_day
        and window.cutoff == event_bar.bar_end
        and window.bars
        and window.bars[-1] == event_bar
        and normalize_contract_for_symbol(symbol, window.contract) == window.contract
    )
