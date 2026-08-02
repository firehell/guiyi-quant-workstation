from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
import sys
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.backtest.v1b_jm_tasks import JM_V1B_DATA_SOURCE, JM_V1B_EXCHANGE, JM_V1B_STRATEGY_CODE, JM_V1B_STRATEGY_VERSION, JM_V1B_SYMBOL
from app.core.env import PROJECT_ROOT
from app.models.signal import SignalEvent
from app.services.live_target_contracts import LiveTargetContractResolver
from app.services.market_data_reader import MarketDataReader
from app.services.profile_lineage import INTRADAY_RESEARCH_PROFILE, LONG_HORIZON_DAILY_PROFILE, ProfileLineageResolver
from app.services.signal_lineage import SignalFormalLineageResolver
from app.signal.events import SIGNAL_CREATED
from app.signal.stage9_gate import evaluate_stage9_signal_event_gate

ENTRY_STATUS = "entry_signal"
REPLAY_SOURCE_MODE = "jm_v1b_historical_replay"
REPLAY_SOURCE = "historical_actual_contract_replay"
REPLAY_WATCHLIST_CODE = "jm_v1b"
REPLAY_PERIODS = ("15m", "5m")


@dataclass(frozen=True)
class ReplayCandidate:
    product: str
    continuous_contract: str
    actual_contract: str
    dominant_mapping_date: str
    exchange: str
    period: str
    bar_start: datetime
    bar_end: datetime
    trigger_price: float
    direction: str
    daily_direction: str
    entry_reason: str
    stop_loss_price: float
    quality_status: dict[str, Any]
    daily_quality: dict[str, Any]
    strategy_params: dict[str, Any]
    formal_lineage: dict[str, Any]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "status": ENTRY_STATUS,
            "product": self.product,
            "continuous_contract": self.continuous_contract,
            "actual_contract": self.actual_contract,
            "dominant_mapping_date": self.dominant_mapping_date,
            "exchange": self.exchange,
            "period": self.period,
            "bar_start": self.bar_start.isoformat(),
            "bar_end": self.bar_end.isoformat(),
            "trigger_price": self.trigger_price,
            "direction": self.direction,
            "daily_direction": self.daily_direction,
            "entry_reason": self.entry_reason,
            "stop_loss_price": self.stop_loss_price,
            "provider": JM_V1B_DATA_SOURCE,
            "source": REPLAY_SOURCE,
            "data_role": "primary",
            "quality_status": self.quality_status,
            "profile_id": self.formal_lineage["primary"]["profile_id"],
            "market_data_file_id": self.formal_lineage["primary"]["market_data_file_id"],
        }


class Stage9JmV1bReplayService:
    """Evaluate the retired Stage 9 historical replay as preview-only evidence."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.reader = MarketDataReader(session)

    def run(
        self,
        *,
        period: Literal["auto", "15m", "5m"] = "auto",
        strategy_params: dict[str, Any] | None = None,
        run_write: bool = False,
        confirm_historical_replay: bool = False,
        confirm_observation_only: bool = False,
        limit: int = 5000,
    ) -> dict[str, Any]:
        if run_write and (not confirm_historical_replay or not confirm_observation_only):
            raise ValueError("--run-write requires --confirm-historical-replay and --confirm-observation-only")

        try:
            candidate = self.find_latest_candidate(period=period, strategy_params=strategy_params or {}, limit=limit)
        except ValueError as exc:
            return {
                "ok": False,
                "dry_run": True,
                "mode": "replay",
                "persistence_allowed": False,
                "candidate_found": False,
                "blocked_reasons": [str(exc)],
                "would_write_signal_event": False,
            }

        if candidate is None:
            return {
                "ok": True,
                "dry_run": True,
                "mode": "replay",
                "persistence_allowed": False,
                "candidate_found": False,
                "blocked_reasons": ["entry_signal_not_found"],
                "would_write_signal_event": False,
            }

        preview_event = self._event_from_candidate(candidate, signal_id=None, task_no="dry-run")
        gate = evaluate_stage9_signal_event_gate(preview_event)
        payload = {
            "ok": True,
            "dry_run": True,
            "mode": "replay",
            "persistence_allowed": False,
            "candidate_found": True,
            "candidate": candidate.to_public_dict(),
            "gate": {
                "allowed": gate["allowed"],
                "blocked_reasons": gate["blocked_reasons"],
                "payload_basis": gate["payload_basis"],
            },
            "would_write_signal_event": False,
            "event_id": None,
            "signal_id": None,
        }
        return payload

    def find_latest_candidate(
        self,
        *,
        period: Literal["auto", "15m", "5m"],
        strategy_params: dict[str, Any],
        limit: int,
    ) -> ReplayCandidate | None:
        _ensure_quant_core_path()
        target = LiveTargetContractResolver(self.session).resolve_ready_actual_contract(product="jm")
        periods = REPLAY_PERIODS if period == "auto" else (period,)
        candidates: list[ReplayCandidate] = []
        for item_period in periods:
            candidates.extend(self._period_candidates(target=target, period=item_period, strategy_params=strategy_params, limit=limit))
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.bar_end)

    def _period_candidates(
        self,
        *,
        target: dict[str, Any],
        period: str,
        strategy_params: dict[str, Any],
        limit: int,
    ) -> list[ReplayCandidate]:
        from guiyi_quant.strategies.jm_v1b_daily_direction_fast_entry.config_schema import validate_params
        from guiyi_quant.strategies.jm_v1b_daily_direction_fast_entry.vnpy_strategy import (
            _bar_datetime,
            _indicator_window,
            _min_intraday_bars,
            calculate_indicators,
            confirmed_daily_direction_snapshot,
            decide_entry,
        )

        params = validate_params(
            {
                **strategy_params,
                "entry_interval": period,
                "max_hold_bars_min": 5,
                "max_hold_bars_max": 8,
                "submit_vnpy_orders": False,
            }
        )
        entry_bars, entry_asset = self._profile_bars(
            profile_id=INTRADAY_RESEARCH_PROFILE,
            contract=target["actual_contract"],
            period=period,
            limit=limit,
        )
        if not entry_bars:
            return []
        if entry_asset is None:
            return []
        quality = {
            "status": "passed",
            "market_data_file_id": entry_asset["market_data_file_id"],
            "data_version": entry_asset["data_version"],
        }
        daily_bars, daily_context = self._profile_bars(
            profile_id=LONG_HORIZON_DAILY_PROFILE,
            contract=JM_V1B_SYMBOL,
            period="1d",
            limit=500,
        )
        daily_quality = {
            "status": "passed" if daily_context is not None else "missing",
            "market_data_file_id": daily_context["market_data_file_id"] if daily_context else None,
            "data_version": daily_context["data_version"] if daily_context else None,
        }
        if not daily_bars or daily_context is None:
            return []
        if entry_asset["quality_status"] != "passed" or daily_context["quality_status"] != "passed":
            return []
        min_bars = _min_intraday_bars(params)
        candidates: list[ReplayCandidate] = []
        for index in range(min_bars, len(entry_bars) + 1):
            current_bar = entry_bars[index - 1]
            current_time = _bar_datetime(current_bar).replace(tzinfo=None)
            available_daily = [row for row in daily_bars if _bar_datetime(row).replace(tzinfo=None) <= current_time]
            if not available_daily:
                continue
            daily = confirmed_daily_direction_snapshot(current_bar=current_bar, daily_bars=available_daily, params=params)
            if daily.direction not in {"long", "short"}:
                continue
            recent = entry_bars[max(0, index - _indicator_window(params)) : index]
            decision = decide_entry(recent, calculate_indicators(recent, params), daily, params)
            if decision.direction == "none":
                continue
            trigger_price = float(current_bar["close"])
            lineage = SignalFormalLineageResolver(self.session).resolve(
                profile_id=INTRADAY_RESEARCH_PROFILE,
                symbol="jm",
                continuous_contract=target["continuous_contract"],
                actual_contract=target["actual_contract"],
                period=period,
                dominant_mapping_date=datetime.fromisoformat(target["dominant_mapping_date"]).date(),
                bar_start=current_time - _period_delta(period),
                bar_end=current_time,
                trigger_price=trigger_price,
                source_mode=REPLAY_SOURCE_MODE,
                confirmation={"confirmation_mode": "historical_canonical"},
                context_assets=[daily_context],
            )
            if lineage.snapshot is None:
                continue
            candidates.append(
                ReplayCandidate(
                    product="jm",
                    continuous_contract=target["continuous_contract"],
                    actual_contract=target["actual_contract"],
                    dominant_mapping_date=target["dominant_mapping_date"],
                    exchange=JM_V1B_EXCHANGE,
                    period=period,
                    bar_start=current_time - _period_delta(period),
                    bar_end=current_time,
                    trigger_price=trigger_price,
                    direction=decision.direction,
                    daily_direction=decision.daily_direction,
                    entry_reason=decision.entry_reason,
                    stop_loss_price=float(decision.stop_loss_price),
                    quality_status=quality,
                    daily_quality=daily_quality,
                    strategy_params=dict(strategy_params),
                    formal_lineage=lineage.snapshot,
                )
            )
        return candidates

    def _profile_bars(
        self,
        *,
        profile_id: str,
        contract: str,
        period: str,
        limit: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        lineage = ProfileLineageResolver(self.session).resolve(
            consumer="signal",
            symbol="jm",
            contract=contract,
            period=period,
            profile_id=profile_id,
            allow_warning_quality=False,
        )
        market_file = lineage.market_file
        if lineage.blocked or market_file is None or market_file.quality_status != "passed" or market_file.data_role != "primary":
            return [], None
        try:
            bars = self.reader.load_bars_from_market_file(
                market_data_file_id=market_file.id,
                symbol="jm",
                contract=contract,
                period=period,
                start=market_file.start_time,
                end=market_file.end_time,
                passed_only=True,
                expected_provider=market_file.provider,
                expected_data_role="primary",
                expected_quality_status="passed",
                expected_data_version=market_file.data_version,
                expected_checksum=market_file.checksum,
            )
        except ValueError:
            return [], None
        asset = {
            **(lineage.binding_snapshot or {}),
            "profile_id": lineage.profile_id,
            "market_data_file_id": market_file.id,
            "instrument_symbol": market_file.instrument_symbol,
            "contract_code": market_file.contract_code,
            "period": market_file.period,
            "data_version": lineage.data_version,
            "provider": market_file.provider,
            "data_role": market_file.data_role,
            "quality_status": market_file.quality_status,
            "coverage_start": market_file.start_time.isoformat(),
            "coverage_end": market_file.end_time.isoformat(),
            "checksum": market_file.checksum,
        }
        return bars[-limit:], asset

    def _event_from_candidate(self, candidate: ReplayCandidate, *, signal_id: int | None, task_no: str | None) -> SignalEvent:
        return SignalEvent(
            event_key=f"{SIGNAL_CREATED}:{_dedupe_key(candidate)}",
            event_type=SIGNAL_CREATED,
            signal_id=signal_id,
            task_no=task_no,
            source_mode=REPLAY_SOURCE_MODE,
            strategy_name=JM_V1B_STRATEGY_CODE,
            strategy_version=JM_V1B_STRATEGY_VERSION,
            watchlist_code=REPLAY_WATCHLIST_CODE,
            symbol="jm",
            contract=candidate.actual_contract,
            product=candidate.product,
            continuous_contract=candidate.continuous_contract,
            actual_contract=candidate.actual_contract,
            dominant_mapping_date=datetime.fromisoformat(candidate.dominant_mapping_date).date(),
            exchange=candidate.exchange,
            period=candidate.period,
            signal_time=candidate.bar_end,
            bar_start=candidate.bar_start,
            bar_end=candidate.bar_end,
            trigger_price=candidate.trigger_price,
            provider=JM_V1B_DATA_SOURCE,
            source=REPLAY_SOURCE,
            direction=candidate.direction,
            signal_status=ENTRY_STATUS,
            lifecycle_status="new",
            score_bucket=80,
            data_role="primary",
            quality_status=candidate.quality_status,
            profile_id=INTRADAY_RESEARCH_PROFILE,
            market_data_file_id=int(candidate.formal_lineage["primary"]["market_data_file_id"]),
            payload={"signal": _candidate_features(candidate), "formal_lineage": deepcopy(candidate.formal_lineage)},
        )


def _candidate_features(candidate: ReplayCandidate) -> dict[str, Any]:
    return {
        "product": candidate.product,
        "continuous_contract": candidate.continuous_contract,
        "actual_contract": candidate.actual_contract,
        "dominant_mapping_date": candidate.dominant_mapping_date,
        "bar_start": candidate.bar_start.isoformat(),
        "bar_end": candidate.bar_end.isoformat(),
        "trigger_price": candidate.trigger_price,
        "provider": JM_V1B_DATA_SOURCE,
        "source": REPLAY_SOURCE,
        "data_role": "primary",
        "strategy_code": JM_V1B_STRATEGY_CODE,
        "strategy_version": JM_V1B_STRATEGY_VERSION,
        "entry_interval": candidate.period,
        "signal_price": candidate.trigger_price,
        "daily_direction": candidate.daily_direction,
        "entry_reason": candidate.entry_reason,
        "stop_loss_price": candidate.stop_loss_price,
        "max_hold_bars_min": 5,
        "max_hold_bars_max": 8,
        "status": ENTRY_STATUS,
        "source_mode": REPLAY_SOURCE_MODE,
        "historical_replay": True,
        "observation_only": True,
        "not_trading_instruction": True,
        "signal_only": True,
        "auto_order": False,
        "daily_quality": candidate.daily_quality,
        "formal_lineage": deepcopy(candidate.formal_lineage),
    }


def _dedupe_key(candidate: ReplayCandidate) -> str:
    return (
        f"stage9_b2_replay:{JM_V1B_STRATEGY_CODE}:{JM_V1B_STRATEGY_VERSION}:"
        f"{candidate.actual_contract}:{candidate.period}:{candidate.bar_end.isoformat()}"
    )


def _period_delta(period: str) -> timedelta:
    if period == "15m":
        return timedelta(minutes=15)
    if period == "5m":
        return timedelta(minutes=5)
    raise ValueError(f"unsupported replay period: {period}")


def _ensure_quant_core_path() -> None:
    path = str(PROJECT_ROOT / "packages" / "quant-core")
    if path not in sys.path:
        sys.path.insert(0, path)
