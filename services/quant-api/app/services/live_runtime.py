from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.services.live_1m_ingest import LiveIngestConfig, LiveMinuteIngestService
from app.services.live_multi_tf_aggregation import LiveAggregationConfig, LiveMultiTfAggregationService, SUPPORTED_PERIODS
from app.services.live_target_contracts import LiveTargetContractResolver
from app.services.trading_session_clock import TradingSessionClock


class HtDyRuntimeEventHandler(Protocol):
    def evaluate_and_persist(
        self,
        *,
        trading_day: Any,
        actual_contract: str,
        detected_at: datetime,
    ) -> Any: ...


@dataclass(frozen=True)
class LiveRuntimeCycleResult:
    status: str
    enabled: bool
    product: str
    actual_contract: str | None
    trading_day: str | None
    phase: str
    reason: str
    required_historical_date: str | None = None
    dominant_mapping_date: str | None = None
    ingest: dict[str, Any] | None = None
    aggregation: dict[str, Any] | None = None
    signal_events: dict[str, Any] | None = None
    writes_signal_event: bool = False
    sends_notification: bool = False
    writes_historical_active: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "enabled": self.enabled,
            "product": self.product,
            "actual_contract": self.actual_contract,
            "trading_day": self.trading_day,
            "phase": self.phase,
            "reason": self.reason,
            "required_historical_date": self.required_historical_date,
            "dominant_mapping_date": self.dominant_mapping_date,
            "ingest": self.ingest,
            "aggregation": self.aggregation,
            "signal_events": self.signal_events,
            "writes_signal_event": self.writes_signal_event,
            "sends_notification": self.sends_notification,
            "writes_historical_active": self.writes_historical_active,
        }


class LiveRuntimeCycleService:
    """Run one JM-only live ingest/aggregation cycle without signal or notification side effects."""

    def __init__(
        self,
        *,
        session: Session,
        client: Any,
        now: datetime | None = None,
        target_resolver: Any | None = None,
        trading_clock: TradingSessionClock | None = None,
    ) -> None:
        self.session = session
        self.client = client
        self.now = now or datetime.now(UTC)
        self.target_resolver = target_resolver or LiveTargetContractResolver(session)
        self.trading_clock = trading_clock or TradingSessionClock(session)

    def run_once(
        self,
        *,
        enabled: bool,
        product: str = "jm",
        persist_signal_events: bool = False,
        signal_event_handler: HtDyRuntimeEventHandler | None = None,
    ) -> LiveRuntimeCycleResult:
        if persist_signal_events:
            raise RuntimeError("legacy_signal_event_runtime_disabled")
        normalized_product = str(product).strip().lower()
        if normalized_product != "jm":
            raise ValueError("V1 live runtime only permits product=jm")
        if not enabled:
            return LiveRuntimeCycleResult(
                status="disabled",
                enabled=False,
                product=normalized_product,
                actual_contract=None,
                trading_day=None,
                phase="disabled",
                reason="GUIYI_LIVE_RUNTIME_ENABLED is false",
            )

        exchange = "DCE"
        decision = self.trading_clock.decision(product=normalized_product, exchange=exchange, now=self.now)
        if not decision.should_poll:
            return LiveRuntimeCycleResult(
                status="idle",
                enabled=True,
                product=normalized_product,
                actual_contract=None,
                trading_day=None,
                phase=decision.phase,
                reason=decision.reason,
            )

        required_date = self.trading_clock.latest_completed_trading_day(
            product=normalized_product,
            exchange=exchange,
            now=self.now,
        )
        target = self.target_resolver.resolve_ready_actual_contract(
            product=normalized_product,
            required_date=required_date,
        )
        parameter_status = target.get("trading_parameter_status") or {}
        exchange = str(parameter_status.get("exchange_code") or exchange).upper()

        client = self.client() if callable(self.client) else self.client
        ingest_result = LiveMinuteIngestService(session=self.session, client=client, now=self.now).poll_once(
            LiveIngestConfig(
                contract=target["actual_contract"],
                symbol=normalized_product,
                exchange=exchange,
                expected_trading_day=decision.trading_day,
            )
        )
        if ingest_result.error_type is not None:
            return LiveRuntimeCycleResult(
                status="failed",
                enabled=True,
                product=normalized_product,
                actual_contract=target["actual_contract"],
                trading_day=decision.trading_day.isoformat() if decision.trading_day else None,
                phase=decision.phase,
                reason=ingest_result.error_type,
                required_historical_date=required_date.isoformat(),
                dominant_mapping_date=target.get("dominant_mapping_date"),
                ingest=ingest_result.to_dict(),
            )
        if ingest_result.max_trading_day != decision.trading_day:
            return LiveRuntimeCycleResult(
                status="failed",
                enabled=True,
                product=normalized_product,
                actual_contract=target["actual_contract"],
                trading_day=decision.trading_day.isoformat() if decision.trading_day else None,
                phase=decision.phase,
                reason="current_trading_day_confirmed_bar_missing",
                required_historical_date=required_date.isoformat(),
                dominant_mapping_date=target.get("dominant_mapping_date"),
                ingest=ingest_result.to_dict(),
            )

        aggregation_config = LiveAggregationConfig(
            contract=target["actual_contract"],
            symbol=normalized_product,
            exchange=exchange,
            periods=SUPPORTED_PERIODS,
        )
        aggregation_result = LiveMultiTfAggregationService(
            session=self.session,
            now=self.now,
            trading_clock=self.trading_clock,
        ).aggregate_once(aggregation_config)
        signal_event_result = None
        writes_signal_event = False
        if signal_event_handler is not None:
            raw_result = signal_event_handler.evaluate_and_persist(
                trading_day=decision.trading_day,
                actual_contract=target["actual_contract"],
                detected_at=self.now,
            )
            signal_event_result = _signal_event_result(raw_result)
            writes_signal_event = bool(signal_event_result["created"])
        return LiveRuntimeCycleResult(
            status="success",
            enabled=True,
            product=normalized_product,
            actual_contract=target["actual_contract"],
            trading_day=decision.trading_day.isoformat() if decision.trading_day else None,
            phase=decision.phase,
            reason="live_ingest_and_aggregation_completed",
            required_historical_date=required_date.isoformat(),
            dominant_mapping_date=target.get("dominant_mapping_date"),
            ingest=ingest_result.to_dict(),
            aggregation=aggregation_result.to_dict(),
            signal_events=signal_event_result,
            writes_signal_event=writes_signal_event,
        )


def _signal_event_result(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        result = dict(value)
    else:
        result = {
            "created": getattr(value, "created", None),
            "changed": getattr(value, "changed", 0),
            "unchanged": getattr(value, "unchanged", None),
            "blocked": getattr(value, "blocked", None),
            "event_ids": list(getattr(value, "event_ids", ())),
        }
    expected = {"created", "changed", "unchanged", "blocked", "event_ids"}
    if set(result) != expected or result.get("changed") != 0:
        raise RuntimeError("htdy_signal_event_result_invalid")
    for key in ("created", "changed", "unchanged", "blocked"):
        if (
            isinstance(result.get(key), bool)
            or not isinstance(result.get(key), int)
            or result[key] < 0
        ):
            raise RuntimeError("htdy_signal_event_result_invalid")
    if not isinstance(result.get("event_ids"), list):
        raise RuntimeError("htdy_signal_event_result_invalid")
    return result
