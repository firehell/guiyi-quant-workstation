from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.schemas.signal import LiveSignalEvaluationRequest
from app.services.live_1m_ingest import LiveIngestConfig, LiveMinuteIngestService
from app.services.live_multi_tf_aggregation import LiveAggregationConfig, LiveMultiTfAggregationService, SUPPORTED_PERIODS
from app.services.live_target_contracts import LiveTargetContractResolver
from app.services.trading_session_clock import TradingSessionClock


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
    ) -> LiveRuntimeCycleResult:
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
        decision = self.trading_clock.decision(product=normalized_product, exchange=exchange, now=self.now)
        if not decision.should_poll:
            return LiveRuntimeCycleResult(
                status="idle",
                enabled=True,
                product=normalized_product,
                actual_contract=target["actual_contract"],
                trading_day=None,
                phase=decision.phase,
                reason=decision.reason,
                required_historical_date=required_date.isoformat(),
                dominant_mapping_date=target.get("dominant_mapping_date"),
            )

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
        if persist_signal_events:
            from app.services.live_signal_evaluator import LiveSignalEvaluator
            from app.services.live_signal_events import LiveSignalEventService

            preview = LiveSignalEvaluator(self.session).preview(
                LiveSignalEvaluationRequest(
                    symbol=normalized_product,
                    contract=target["actual_contract"],
                    entry_intervals=["5m", "15m"],
                    provider="rqdata",
                    source_mode=aggregation_config.source_mode,
                )
            )
            write_result = LiveSignalEventService(self.session).persist(preview)
            signal_event_result = {
                "created": write_result.created,
                "changed": write_result.changed,
                "unchanged": write_result.unchanged,
                "blocked": write_result.blocked,
                "event_ids": list(write_result.event_ids),
            }
            writes_signal_event = bool(write_result.created or write_result.changed)
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
