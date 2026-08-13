"""Alert V1 的前台、无 replay 编排循环。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json
import logging
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.evaluators import AlertEvaluation, AlertEvaluator
from app.alerts.models import AlertRule
from app.alerts.service import AlertEventCreate, AlertService
from app.alerts.wecom import AlertEventMessage, WeComWebhookSender
from app.market_data.domain import CanonicalBar, SeriesPageQuery, normalize_contract_for_symbol
from app.market_data.market_read_service import MarketReadService, MarketReadWindow
from app.market_data.product_retirement import normalize_symbol
from app.market_data.product_taxonomy import ProductTaxonomyEntry


_LOGGER = logging.getLogger(__name__)
_PATTERN = "live:bar:*:15m"
_HEARTBEAT_INTERVAL = timedelta(seconds=10)
_HEARTBEAT_TTL_SECONDS = 30


class AlertMessageSource(Protocol):
    def subscribe(self, pattern: str) -> None: ...
    def get_message(self, *, timeout_seconds: float) -> tuple[object, object] | None: ...
    def close(self) -> None: ...


class AlertHeartbeatStore(Protocol):
    def write(self, payload: dict[str, object], *, ttl_seconds: int) -> None: ...


class AlertRuntime:
    def __init__(
        self,
        *,
        session: Session,
        market_read: MarketReadService,
        evaluator: AlertEvaluator,
        sender: WeComWebhookSender,
        operational_products: tuple[str, ...],
        taxonomy: Mapping[str, ProductTaxonomyEntry],
        message_source: AlertMessageSource | None = None,
        heartbeat_store: AlertHeartbeatStore | None = None,
        clock: Callable[[], datetime] | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> None:
        self._session = session
        self._market_read = market_read
        self._evaluator = evaluator
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
        """只消费启动后新到达的 completed 15m Pub/Sub 消息。"""
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

    def process_message(self, channel: str, payload: object) -> None:
        """处理单条实时事件；任一输入/依赖异常都在发送前 fail closed。"""
        parsed = _parse_event(channel, payload)
        if parsed is None:
            return
        symbol, event_bar = parsed
        if symbol not in self._operational_products:
            return
        rule = self._enabled_rule(symbol)
        if rule is None:
            return
        try:
            window = self._market_read.bars_until(
                SeriesPageQuery("actual_dominant", symbol, "15m"),
                trading_day=event_bar.trading_day,
                end=event_bar.bar_end,
                limit=32,
            )
            if not _window_matches_event(window, symbol=symbol, event_bar=event_bar):
                return
            evaluation = self._evaluator.evaluate(window)
            if not isinstance(evaluation, AlertEvaluation) or not evaluation.observation_types:
                return
            now = self._aware_now()
            created = AlertService(
                self._session,
                operational_products=tuple(self._operational_products),
            ).create_event(
                AlertEventCreate(
                    rule_id=rule.id,
                    symbol=symbol,
                    contract=window.contract,
                    frequency="15m",
                    bar_end=event_bar.bar_end,
                    observation_types=evaluation.observation_types,
                    detected_at=now,
                    notified_at=now,
                )
            )
            if created is None:
                return
        except Exception:  # noqa: BLE001 - fail closed without external detail
            self._session.rollback()
            _LOGGER.warning("ALERT_PROCESSING_FAILED")
            return

        taxonomy = self._taxonomy.get(symbol)
        if taxonomy is None:
            _LOGGER.warning("ALERT_PRODUCT_NAME_UNAVAILABLE")
            return
        try:
            self._sender.send(
                AlertEventMessage(
                    symbol=symbol,
                    product_name=taxonomy.name,
                    contract=window.contract,
                    frequency="15m",
                    bar_end=event_bar.bar_end,
                    observation_types=evaluation.observation_types,
                )
            )
        except Exception:  # noqa: BLE001 - Event stays committed; V1 never retries
            _LOGGER.warning("ALERT_NOTIFICATION_FAILED")

    def _enabled_rule(self, symbol: str) -> AlertRule | None:
        try:
            rule = self._session.scalar(
                select(AlertRule).where(AlertRule.rule_code == "htdy_original_15m")
            )
        except Exception:  # noqa: BLE001 - DB read failure must not send
            self._session.rollback()
            return None
        if (
            rule is None
            or rule.enabled is not True
            or rule.indicator_code != self._evaluator.indicator_code
            or rule.frequency != self._evaluator.frequency
            or symbol not in set(rule.scope_products or [])
        ):
            return None
        return rule

    def _write_heartbeat(self, now: datetime) -> None:
        assert self.heartbeat_store is not None
        enabled = self._session.scalars(select(AlertRule).where(AlertRule.enabled.is_(True))).all()
        scope = {
            symbol
            for rule in enabled
            for symbol in (rule.scope_products or [])
            if symbol in self._operational_products
        }
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


def _parse_event(channel: object, payload: object) -> tuple[str, CanonicalBar] | None:
    try:
        if isinstance(channel, bytes):
            channel = channel.decode("utf-8")
        if not isinstance(channel, str):
            return None
        parts = channel.split(":")
        if len(parts) != 4 or parts[:2] != ["live", "bar"] or parts[3] != "15m":
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
                None if raw["open_interest"] is None else Decimal(str(raw["open_interest"]))
            ),
        )
    except (KeyError, TypeError, ValueError, UnicodeError):
        return None
    return symbol, bar


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
        and window.bars[-1].bar_end == event_bar.bar_end
        and normalize_contract_for_symbol(symbol, window.contract) == window.contract
    )
