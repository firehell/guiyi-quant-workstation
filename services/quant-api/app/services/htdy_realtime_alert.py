from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.signal import HtdyObservationAlert
from app.core.env import PROJECT_ROOT
from app.services.live_signal_context import HistoricalLiveContextResolver
from app.services.live_target_contracts import LiveTargetContractResolver
from guiyi_quant.indicators.htdy_original import (
    HtdyOriginalResult,
    compute_htdy_original,
)
from guiyi_quant.indicators.policy import require_formal_policy


ALERT_POLICY = "htdy_original_repainting_realtime_v1"
INDICATOR_CODE = "huotian_dayou_original_v0"
INDICATOR_VERSION = "original-v0"
STRATEGY_NAME = "huotian_dayou_original"
STRATEGY_VERSION = "v0-observation-only"
SOURCE_MODE = "live_confirmed_repainting_observation"


@dataclass(frozen=True)
class HtdyObservationCandidate:
    symbol: str
    continuous_contract: str
    actual_contract: str
    dominant_mapping_date: date
    period: str
    bar_end: datetime
    trigger_price: float
    direction: str
    bar_status: str
    quality_status: str
    provider: str
    data_role: str
    profile_id: str
    market_data_file_id: int
    live_bar_id: int
    live_bar_revision: int
    confirmed_at: datetime
    lineage: dict[str, object]


@dataclass(frozen=True)
class HtdyObservationWriteResult:
    status: Literal["created", "unchanged", "blocked"]
    alert_id: int | None
    blocked_reason: str | None = None


def candidate_direction(*, buy: bool, sell: bool) -> str | None:
    if buy and sell:
        return "conflict"
    if buy:
        return "long"
    if sell:
        return "short"
    return None


def candidate_from_output(
    output: HtdyOriginalResult,
    *,
    continuous_contract: str,
    actual_contract: str,
    dominant_mapping_date: date,
    live_trigger: dict[str, object],
    profile_id: str,
    market_data_file_id: int,
) -> HtdyObservationCandidate | None:
    if len(output.datetimes) == 0:
        return None
    index = len(output.datetimes) - 1
    direction = candidate_direction(
        buy=bool(output.fields["buy_observation"][index]),
        sell=bool(output.fields["sell_observation"][index]),
    )
    if direction is None:
        return None
    bar_end = _datetime_value(output.datetimes[index], name="bar_end")
    confirmed_at = _datetime_value(live_trigger.get("confirmed_at"), name="confirmed_at")
    live_bar_id = live_trigger.get("live_bar_id", live_trigger.get("id"))
    revision = live_trigger.get("live_bar_revision", live_trigger.get("revision"))
    if not isinstance(live_bar_id, int) or not isinstance(revision, int):
        raise ValueError("live_bar_identity_missing")
    return HtdyObservationCandidate(
        symbol="jm",
        continuous_contract=continuous_contract,
        actual_contract=actual_contract,
        dominant_mapping_date=dominant_mapping_date,
        period="15m",
        bar_end=bar_end,
        trigger_price=float(output.close[index]),
        direction=direction,
        bar_status=str(live_trigger.get("bar_status") or ""),
        quality_status=str(live_trigger.get("quality_status") or ""),
        provider="rqdata",
        data_role="primary",
        profile_id=profile_id,
        market_data_file_id=market_data_file_id,
        live_bar_id=live_bar_id,
        live_bar_revision=revision,
        confirmed_at=confirmed_at,
        lineage={
            "schema_version": "htdy_observation_lineage_v1",
            "indicator_code": INDICATOR_CODE,
            "indicator_version": INDICATOR_VERSION,
            "alert_policy": ALERT_POLICY,
            "future_looking": True,
            "repainting_risk": "known",
            "profile_id": profile_id,
            "market_data_file_id": market_data_file_id,
            "continuous_contract": continuous_contract,
            "actual_contract": actual_contract,
            "dominant_mapping_date": dominant_mapping_date.isoformat(),
            "period": "15m",
            "bar_end": bar_end.isoformat(),
            "live_bar_id": live_bar_id,
            "live_bar_revision": revision,
            "confirmed_at": confirmed_at.isoformat(),
        },
    )


class HtdyRealtimeObservationEvaluator:
    """Read-only JM 15m original-XMA observation preview."""

    def __init__(
        self,
        session: Session | None,
        *,
        project_root: Path = PROJECT_ROOT,
        target_resolver: object | None = None,
        context_resolver: object | None = None,
        kernel: object = compute_htdy_original,
    ) -> None:
        self.session = session
        self.target_resolver = target_resolver or LiveTargetContractResolver(session)
        self.context_resolver = context_resolver or HistoricalLiveContextResolver(
            session,
            project_root=project_root,
        )
        self.kernel = kernel

    def preview(
        self,
        *,
        contract: str | None = None,
        profile_id: str = "live_observation_v1",
        provider: str = "rqdata",
        source_mode: str | None = None,
        limit: int = 500,
    ) -> dict[str, object]:
        candidate = self.evaluate_candidate(
            contract=contract,
            profile_id=profile_id,
            provider=provider,
            source_mode=source_mode,
            limit=limit,
        )
        return {
            "status": "candidate" if candidate else "no_observation",
            "writes": False,
            "candidate": asdict(candidate) if candidate else None,
            "metadata": {
                "indicator_code": INDICATOR_CODE,
                "indicator_version": INDICATOR_VERSION,
                "alert_policy": ALERT_POLICY,
                "future_looking": True,
                "repainting_risk": "known",
                "repaint_followup": "none",
                "not_trading_instruction": True,
            },
        }

    def evaluate_candidate(
        self,
        *,
        contract: str | None = None,
        profile_id: str = "live_observation_v1",
        provider: str = "rqdata",
        source_mode: str | None = None,
        limit: int = 500,
    ) -> HtdyObservationCandidate | None:
        target = self.target_resolver.resolve_ready_actual_contract(
            product="jm",
            requested_contract=contract,
        )
        context = self.context_resolver.resolve(
            symbol="jm",
            actual_contract=target["actual_contract"],
            period="15m",
            profile_id=profile_id,
            provider=provider,
            source_mode=source_mode,
            limit=max(128, min(limit, 10000)),
        )
        bars = context.merged_bars
        output = self.kernel(
            [row["datetime"] for row in bars],
            [row["open"] for row in bars],
            [row["high"] for row in bars],
            [row["low"] for row in bars],
            [row["close"] for row in bars],
            [row["volume"] for row in bars],
        )
        mapping_date = target["dominant_mapping_date"]
        if isinstance(mapping_date, str):
            mapping_date = date.fromisoformat(mapping_date)
        return candidate_from_output(
            output,
            continuous_contract=target["continuous_contract"],
            actual_contract=target["actual_contract"],
            dominant_mapping_date=mapping_date,
            live_trigger=context.live_trigger,
            profile_id=profile_id,
            market_data_file_id=context.historical_context_file_id,
        )
class HtdyObservationAlertService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def persist(self, candidate: HtdyObservationCandidate) -> HtdyObservationWriteResult:
        blocked_reason = _blocked_reason(candidate)
        if blocked_reason:
            return HtdyObservationWriteResult("blocked", None, blocked_reason)

        require_formal_policy(
            "huotian_dayou_original_v0",
            consumer="live_repainting_observation_alert",
        )
        alert_key = _alert_key(candidate)
        existing = self.session.scalar(
            select(HtdyObservationAlert).where(HtdyObservationAlert.alert_key == alert_key)
        )
        if existing is not None:
            return HtdyObservationWriteResult("unchanged", existing.id)

        alert = HtdyObservationAlert(
            alert_key=alert_key,
            alert_policy=ALERT_POLICY,
            indicator_code=INDICATOR_CODE,
            indicator_version=INDICATOR_VERSION,
            strategy_name=STRATEGY_NAME,
            strategy_version=STRATEGY_VERSION,
            symbol=candidate.symbol.lower(),
            continuous_contract=candidate.continuous_contract.upper(),
            actual_contract=candidate.actual_contract.upper(),
            dominant_mapping_date=candidate.dominant_mapping_date,
            period=candidate.period,
            bar_end=candidate.bar_end,
            trigger_price=float(candidate.trigger_price),
            direction=candidate.direction,
            source_mode=SOURCE_MODE,
            provider=candidate.provider,
            data_role=candidate.data_role,
            quality_status=candidate.quality_status,
            profile_id=candidate.profile_id,
            market_data_file_id=candidate.market_data_file_id,
            live_bar_id=candidate.live_bar_id,
            live_bar_revision=candidate.live_bar_revision,
            confirmed_at=candidate.confirmed_at,
            future_looking=True,
            repainting_risk="known",
            alert_status="created",
            notification_status="not_sent",
            payload={
                "lineage": dict(candidate.lineage),
                "future_looking": True,
                "repainting_risk": "known",
                "repaint_followup": "none",
                "observation_only": True,
                "not_trading_instruction": True,
                "auto_order": False,
            },
        )
        self.session.add(alert)
        self.session.flush()
        return HtdyObservationWriteResult("created", alert.id)


def _blocked_reason(candidate: HtdyObservationCandidate) -> str | None:
    checks = (
        (candidate.symbol.lower() == "jm", "symbol_not_jm"),
        (candidate.period == "15m", "period_not_15m"),
        (candidate.bar_status == "confirmed", "bar_not_confirmed"),
        (candidate.quality_status == "passed", "quality_not_passed"),
        (candidate.provider == "rqdata", "provider_not_rqdata"),
        (candidate.data_role == "primary", "data_role_not_primary"),
        (bool(candidate.actual_contract) and not candidate.actual_contract.upper().endswith(".MAIN"), "actual_contract_required"),
        (candidate.direction in {"long", "short", "conflict"}, "direction_invalid"),
        (candidate.trigger_price > 0, "trigger_price_invalid"),
        (candidate.lineage.get("schema_version") == "htdy_observation_lineage_v1", "lineage_invalid"),
    )
    return next((reason for allowed, reason in checks if not allowed), None)


def _alert_key(candidate: HtdyObservationCandidate) -> str:
    return ":".join(
        (
            "htdy-original-realtime",
            candidate.symbol.lower(),
            candidate.actual_contract.upper(),
            candidate.period,
            candidate.bar_end.isoformat(),
        )
    )


def _datetime_value(value: object, *, name: str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(value, datetime):
        return value
    raise ValueError(f"{name}_missing")


__all__ = [
    "ALERT_POLICY",
    "HtdyObservationAlertService",
    "HtdyObservationCandidate",
    "HtdyObservationWriteResult",
    "HtdyRealtimeObservationEvaluator",
    "candidate_from_output",
    "candidate_direction",
]
