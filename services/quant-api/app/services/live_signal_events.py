from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from json import dumps

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.signal import SignalEvent, StrategySignal
from app.schemas.signal import LiveSignalEvaluationItem, LiveSignalEvaluationResponse
from app.signal.events import SIGNAL_CHANGED, SIGNAL_CREATED, record_live_signal_event

LIVE_SOURCE_MODE = "live_confirmed"
LIVE_SOURCE = "live_db_actual_contract"
ALLOWED_PERIODS = {"5m", "15m"}


@dataclass(frozen=True)
class LiveSignalEventWriteResult:
    created: int
    changed: int
    unchanged: int
    blocked: int
    event_ids: tuple[int, ...]
    blocked_reasons: tuple[dict[str, object], ...]


class LiveSignalEventService:
    """Persist strict live-confirmed observations; preview remains read-only."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def persist(self, response: LiveSignalEvaluationResponse) -> LiveSignalEventWriteResult:
        counters = {"created": 0, "changed": 0, "unchanged": 0, "blocked": 0}
        event_ids: list[int] = []
        blocked_reasons: list[dict[str, object]] = []
        for item in response.results:
            reasons = _eligibility_blocked_reasons(item)
            if reasons:
                counters["blocked"] += 1
                blocked_reasons.extend(reasons)
                continue
            event, outcome = self._persist_item(item)
            counters[outcome] += 1
            if event.id is not None:
                event_ids.append(event.id)
        return LiveSignalEventWriteResult(
            event_ids=tuple(event_ids),
            blocked_reasons=tuple(blocked_reasons),
            **counters,
        )

    def _persist_item(self, item: LiveSignalEvaluationItem) -> tuple[SignalEvent, str]:
        dedupe_key = _dedupe_key(item)
        state_key = _state_key(item)
        signal = self.session.scalar(select(StrategySignal).where(StrategySignal.dedupe_key == dedupe_key))
        if signal is None:
            signal = _new_signal(item, dedupe_key, state_key)
            self.session.add(signal)
            self.session.flush()
            event = record_live_signal_event(self.session, signal, SIGNAL_CREATED, state_key=state_key)
            if event is None:
                raise RuntimeError("failed to create live-confirmed signal event")
            return event, "created"

        old_state_key = str((signal.features or {}).get("live_state_key") or "")
        if old_state_key == state_key:
            event = self.session.scalar(
                select(SignalEvent).where(SignalEvent.event_key == f"{SIGNAL_CREATED}:{signal.dedupe_key}:created")
            )
            if event is None:
                raise RuntimeError("live signal exists without its created event")
            return event, "unchanged"

        _update_signal(signal, item, state_key)
        self.session.flush()
        event = record_live_signal_event(self.session, signal, SIGNAL_CHANGED, state_key=state_key)
        if event is None:
            raise RuntimeError("failed to create changed live-confirmed signal event")
        return event, "changed"


def _is_eligible(item: LiveSignalEvaluationItem) -> bool:
    return not _eligibility_blocked_reasons(item)


def _eligibility_blocked_reasons(item: LiveSignalEvaluationItem) -> list[dict[str, object]]:
    actual_contract = (item.actual_contract or "").strip()
    source = item.source or {}
    checks = [
        (item.status == "entry_signal", "SIGNAL_NOT_ENTRY"),
        (item.entry_interval in ALLOWED_PERIODS, "SIGNAL_PERIOD_BLOCKED"),
        (item.quality.get("status") == "passed" and not item.warnings, "SIGNAL_QUALITY_BLOCKED"),
        (bool(item.bar_end) and item.trigger_price is not None, "SIGNAL_BAR_EVIDENCE_MISSING"),
        (item.direction in {"long", "short"}, "SIGNAL_DIRECTION_BLOCKED"),
        (bool(actual_contract) and not actual_contract.upper().endswith(".MAIN"), "SIGNAL_ACTUAL_CONTRACT_REQUIRED"),
        (source.get("entry_data_source") == LIVE_SOURCE and source.get("provider") == "rqdata", "SIGNAL_SOURCE_BLOCKED"),
        (source.get("preview_only") is True and source.get("writes_signal_event") is False, "SIGNAL_PREVIEW_CONTRACT_INVALID"),
        (source.get("bar_status") == "confirmed", "SIGNAL_BAR_NOT_CONFIRMED"),
    ]
    reasons = [
        {"code": code, "context": _blocked_context(item)}
        for allowed, code in checks
        if not allowed
    ]
    if not isinstance(source.get("formal_lineage"), dict):
        reasons.append({"code": "SIGNAL_FORMAL_LINEAGE_MISSING", "context": _blocked_context(item)})
    elif not _eligible_lineage(item):
        reasons.append({"code": "SIGNAL_FORMAL_LINEAGE_INVALID", "context": _blocked_context(item)})
    return reasons


def _blocked_context(item: LiveSignalEvaluationItem) -> dict[str, object | None]:
    return {
        "profile_id": ((item.source or {}).get("formal_lineage") or {}).get("primary", {}).get("profile_id")
        if isinstance((item.source or {}).get("formal_lineage"), dict)
        else None,
        "instrument_symbol": item.symbol,
        "actual_contract": item.actual_contract,
        "period": item.entry_interval,
        "bar_end": item.bar_end,
    }


def _eligible_lineage(item: LiveSignalEvaluationItem) -> bool:
    lineage = (item.source or {}).get("formal_lineage")
    if not isinstance(lineage, dict):
        return False
    primary = lineage.get("primary")
    contract = lineage.get("contract")
    bar = lineage.get("bar")
    if not isinstance(primary, dict) or not isinstance(contract, dict) or not isinstance(bar, dict):
        return False
    return all(
        (
            lineage.get("schema_version") == "signal_review_lineage_v1",
            lineage.get("resolver_name") == "ProfileLineageResolver",
            lineage.get("resolver_contract_version") == "signal_profile_v1",
            lineage.get("quality_policy") == "passed_only",
            lineage.get("source_mode") == LIVE_SOURCE_MODE,
            primary.get("profile_id") == "live_observation_v1",
            isinstance(primary.get("market_data_file_id"), int),
            primary.get("instrument_symbol") == item.symbol,
            primary.get("contract_code") == item.actual_contract,
            primary.get("period") == item.entry_interval,
            primary.get("provider") in {"rqdata", "local_parquet"},
            primary.get("data_role") == "primary",
            primary.get("quality_status") == "passed",
            contract.get("continuous_contract") == item.continuous_contract,
            contract.get("actual_contract") == item.actual_contract,
            contract.get("dominant_mapping_date") == item.dominant_mapping_date,
            bar.get("bar_end") == item.bar_end,
            bar.get("trigger_price") == item.trigger_price,
            bar.get("confirmation_mode") == LIVE_SOURCE_MODE,
            bar.get("bar_status") == "confirmed",
            isinstance(bar.get("live_bar_id"), int),
            isinstance(bar.get("live_bar_revision"), int),
        )
    )


def _dedupe_key(item: LiveSignalEvaluationItem) -> str:
    return ":".join(
        (
            "live",
            item.strategy_code,
            item.strategy_version,
            item.symbol,
            str(item.actual_contract),
            item.entry_interval,
            str(item.bar_end),
            "entry",
        )
    )


def _state_key(item: LiveSignalEvaluationItem) -> str:
    lineage = (item.source or {}).get("formal_lineage") or {}
    bar = lineage.get("bar") if isinstance(lineage, dict) else {}
    payload = {
        "direction": item.direction,
        "trigger_price": item.trigger_price,
        "stop_loss_price": item.stop_loss_price,
        "entry_reason": item.entry_reason,
        "quality": item.quality,
        "live_bar_id": bar.get("live_bar_id") if isinstance(bar, dict) else None,
        "live_bar_revision": bar.get("live_bar_revision") if isinstance(bar, dict) else None,
    }
    return sha256(dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:20]


def _new_signal(
    item: LiveSignalEvaluationItem,
    dedupe_key: str,
    state_key: str,
) -> StrategySignal:
    bar_end = _parse_datetime(item.bar_end)
    lineage = _lineage(item)
    primary = lineage["primary"]
    return StrategySignal(
        task_no=None,
        dedupe_key=dedupe_key,
        strategy_name=item.strategy_code,
        strategy_version=item.strategy_version,
        watchlist_code="jm_v1b_live",
        symbol=item.symbol,
        contract=str(item.actual_contract),
        product=item.symbol,
        continuous_contract=item.continuous_contract,
        actual_contract=item.actual_contract,
        dominant_mapping_date=_parse_date(item.dominant_mapping_date),
        exchange="DCE",
        period=item.entry_interval,
        signal_time=bar_end,
        bar_start=bar_end - _period_delta(item.entry_interval),
        bar_end=bar_end,
        trigger_price=float(item.trigger_price),
        provider="rqdata",
        source=LIVE_SOURCE,
        data_role="primary",
        status="entry_signal",
        direction=item.direction,
        signal_level=80,
        score_bucket=80,
        bucket_label="实时确认观察",
        current_price=float(item.trigger_price),
        target_price=None,
        stop_loss_price=item.stop_loss_price,
        risk_reward_ratio=None,
        open_volume=0,
        margin_required=0.0,
        risk_amount=0.0,
        account_equity=100000.0,
        reasons=list(item.reasons),
        features=_features(item, state_key),
        quality_status=dict(item.quality),
        research_contract=False,
        spec_source="live_confirmed_v1",
        alert_status="unread",
        profile_id=str(primary["profile_id"]),
        market_data_file_id=int(primary["market_data_file_id"]),
    )


def _update_signal(signal: StrategySignal, item: LiveSignalEvaluationItem, state_key: str) -> None:
    signal.direction = item.direction
    signal.trigger_price = float(item.trigger_price)
    signal.current_price = float(item.trigger_price)
    signal.stop_loss_price = item.stop_loss_price
    signal.reasons = list(item.reasons)
    signal.features = _features(item, state_key)
    signal.quality_status = dict(item.quality)
    signal.updated_at = datetime.now(UTC)


def _features(item: LiveSignalEvaluationItem, state_key: str) -> dict[str, object]:
    return {
        "source_mode": LIVE_SOURCE_MODE,
        "provider": "rqdata",
        "data_role": "primary",
        "quality_status": "passed",
        "observation_only": True,
        "not_trading_instruction": True,
        "auto_order": False,
        "confirmed_bar": (item.source or {}).get("bar_status") == "confirmed",
        "daily_direction": item.daily_direction,
        "entry_reason": item.entry_reason,
        "live_state_key": state_key,
        "formal_lineage": deepcopy(_lineage(item)),
    }


def _lineage(item: LiveSignalEvaluationItem) -> dict[str, object]:
    value = (item.source or {}).get("formal_lineage")
    if not isinstance(value, dict):
        raise ValueError("formal lineage is required")
    return value


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        raise ValueError("bar_end is required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _period_delta(period: str) -> timedelta:
    return timedelta(minutes=int(period.removesuffix("m")))
