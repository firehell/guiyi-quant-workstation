from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping, Sequence

import pyarrow.parquet as pq
from sqlalchemy.orm import Session

from app.backtest.drawdown_curve_generator import generate_drawdown_curve
from app.backtest.equity_curve_generator import generate_equity_curve
from app.backtest.htdy_trusted_report import (
    CanonicalCostDay,
    CandidateBar,
    FrozenProfileSelection,
    build_candidate_bars,
    build_canonical_cost_timeline,
    cost_timeline_payload,
    file_sha256,
    freeze_profile_selection,
    load_protocol_context,
    packet_hash,
)
from app.backtest.report_metrics import compute_report_metrics
from app.models.data_center import MarketDataFile
from guiyi_quant.strategies.huotian_dayou_strict import (
    HuoTianDaYouStrictStrategy,
    build_normalized_result,
    build_strict_snapshot_series,
    validate_params,
)


TASK_ID = "HTDY-OOS-VALIDATION-X504"
EXECUTED_GATE = "OOS_VALIDATION_EXECUTED"
HARD_REJECT_GATE = "OOS_HARD_REJECT_TRIGGERED"
PREREQUISITE_GATE = "HTDY_TRUSTED_BACKTEST_CANDIDATE"
WINDOW_ID = "oos_fixed"
WARMUP_BARS = 72
X502_PACKET_RELATIVE_PATH = Path(
    "data/reports/htdy_trusted_report_x5_02/HTDY_TRUSTED_REPORT_APPLY_PACKET.json"
)
DEFAULT_CANDIDATE_PACKET_RELATIVE_PATH = Path(
    "data/reports/htdy_trusted_backtest_candidate_x5_03/HTDY_TRUSTED_BACKTEST_CANDIDATE.json"
)


class OOSPrerequisiteError(ValueError):
    """Raised before OOS execution when the X5-03 success Gate is absent or invalid."""


@dataclass(frozen=True)
class IndicatorBar:
    datetime: datetime
    open: float
    high: float
    low: float
    close: float


def verify_canonical_packet_hash(packet: Mapping[str, Any]) -> bool:
    payload = dict(packet)
    expected = str(payload.pop("packet_hash", ""))
    return bool(expected) and expected == packet_hash(payload)


def load_candidate_prerequisite(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise OOSPrerequisiteError(f"X5-03 prerequisite packet is missing: {path.name}")
    packet = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(packet, dict) or not verify_canonical_packet_hash(packet):
        raise OOSPrerequisiteError("X5-03 prerequisite packet hash is invalid")
    _validate_candidate_packet(packet)
    return packet


def _validate_candidate_packet(packet: Mapping[str, Any]) -> None:
    if packet.get("gate") != PREREQUISITE_GATE:
        raise OOSPrerequisiteError(f"X5-03 prerequisite Gate must be {PREREQUISITE_GATE}")
    if (packet.get("transaction") or {}).get("status") != "committed":
        raise OOSPrerequisiteError("X5-03 candidate transaction was not committed")
    identity = packet.get("candidate_identity") or {}
    task_identity = identity.get("task") or {}
    report_identity = identity.get("report") or {}
    if not task_identity.get("id") or not task_identity.get("task_no"):
        raise OOSPrerequisiteError("X5-03 prerequisite is missing task identity")
    if not report_identity.get("id") or not report_identity.get("report_no"):
        raise OOSPrerequisiteError("X5-03 prerequisite is missing report identity")
    audits = packet.get("audits") or {}
    if (audits.get("candidate") or {}).get("audit_status") != "passed":
        raise OOSPrerequisiteError("X5-03 candidate trust audit is not passed")
    if (audits.get("report14") or {}).get("audit_status") != "passed":
        raise OOSPrerequisiteError("X5-03 report14 trust audit is not passed")
    snapshot = packet.get("execution_snapshot") or {}
    required_snapshot_fields = (
        "snapshot_hash",
        "profile_id",
        "profile_active_binding_id",
        "market_data_file_id",
        "data_version",
    )
    if any(snapshot.get(field) in (None, "") for field in required_snapshot_fields):
        raise OOSPrerequisiteError("X5-03 prerequisite is missing execution snapshot identity")


def load_x502_packet(repo_root: Path) -> dict[str, Any]:
    path = repo_root / X502_PACKET_RELATIVE_PATH
    if not path.is_file():
        raise OOSPrerequisiteError("X5-02 trusted-report apply packet is missing")
    packet = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(packet, dict) or not verify_canonical_packet_hash(packet):
        raise OOSPrerequisiteError("X5-02 trusted-report apply packet hash is invalid")
    if packet.get("gate") != "HTDY_TRUSTED_REPORT_APPLY_PACKET_READY":
        raise OOSPrerequisiteError("X5-02 trusted-report apply packet Gate is invalid")
    return packet


def assert_selection_unchanged(before: FrozenProfileSelection, after: FrozenProfileSelection) -> None:
    if before.payload() != after.payload():
        raise ValueError("active Profile binding or file changed during X5-04 OOS execution")


def select_oos_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    start: datetime,
    end: datetime,
    warmup_count: int = WARMUP_BARS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = sorted((dict(row) for row in rows), key=lambda row: _naive_datetime(row["datetime"]))
    warmup = [row for row in ordered if _naive_datetime(row["datetime"]) < start][-warmup_count:]
    oos = [row for row in ordered if start <= _naive_datetime(row["datetime"]) <= end]
    return warmup, oos


def build_indicator_bars(
    rows: Sequence[Mapping[str, Any]],
    *,
    data_version: str,
) -> list[IndicatorBar]:
    bars: list[IndicatorBar] = []
    seen: set[datetime] = set()
    for index, row in enumerate(rows):
        _validate_lineage_row(row, data_version=data_version, index=index)
        bar_datetime = _naive_datetime(row["datetime"])
        if bar_datetime in seen:
            raise ValueError(f"OOS input contains duplicate datetime: {bar_datetime.isoformat()}")
        seen.add(bar_datetime)
        open_, high, low, close = (float(row[name]) for name in ("open", "high", "low", "close"))
        if high < max(open_, close) or low > min(open_, close) or high < low:
            raise ValueError(f"OOS warm-up input has invalid OHLC at index {index}")
        bars.append(IndicatorBar(datetime=bar_datetime, open=open_, high=high, low=low, close=close))
    return bars


def evaluate_oos_window(
    warmup_bars: Sequence[IndicatorBar],
    oos_bars: Sequence[CandidateBar],
    *,
    execution_snapshot: FrozenProfileSelection,
    protocol_hash: str,
    parameter_hash: str,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, Any]:
    started = perf_counter()
    params = validate_params()
    combined = [*warmup_bars, *oos_bars]
    all_snapshots = build_strict_snapshot_series(combined, params)
    oos_snapshots = all_snapshots[len(warmup_bars) :]
    strategy = HuoTianDaYouStrictStrategy(
        None,
        "htdy-oos-validation-x504",
        "jm_MAIN.DCE",
        {"_guiyi_strict_snapshots": oos_snapshots},
    )
    for bar in oos_bars:
        strategy.on_bar(bar)
    strategy.finalize_sample_end()
    normalized = build_normalized_result(strategy)
    trades = list(normalized["trades"])
    orders = list(normalized["orders"])
    equity_curve = generate_equity_curve(trades, initial_capital=params.initial_capital)
    drawdown = generate_drawdown_curve(equity_curve)
    metrics = compute_report_metrics(
        summary=normalized["summary"],
        trades=trades,
        equity_curve=equity_curve,
        drawdown_curve=drawdown["drawdown_curve"],
        start=window_start,
        end=window_end,
        default_initial_capital=params.initial_capital,
    )
    losses = [float(trade["net_pnl"]) for trade in trades if float(trade["net_pnl"]) < 0]
    gains = [float(trade["net_pnl"]) for trade in trades if float(trade["net_pnl"]) > 0]
    metrics.update(
        {
            "total_return_pct": metrics["total_return"],
            "profit_factor": sum(gains) / abs(sum(losses)) if losses else 0.0,
            "profit_factor_defined": bool(losses),
            "winning_trade_count": len(gains),
            "losing_trade_count": len(losses),
            "largest_loss_trade": min(losses) if losses else 0.0,
            "signal_count": sum(
                1
                for event in normalized["strategy_execution_events"]
                if event.get("action") in {"open_long", "open_short"}
            ),
            "no_trade_reasons": _count_values(normalized["warnings"]),
            "fee_totals": metrics["total_commission"],
            "slippage_totals": metrics["total_slippage"],
        }
    )
    return {
        "schema_version": "htdy_oos_fixed_result_x504_v1",
        "task_id": TASK_ID,
        "window_id": WINDOW_ID,
        "status": "executed",
        "strategy_code": params.strategy_code,
        "strategy_version": params.strategy_version,
        "candidate_policy": params.candidate_policy,
        "indicator_version": params.indicator_version,
        "execution_policy": {
            "confirmed_only": params.confirmed_only,
            "execution_timing": params.execution_timing,
            "fill_policy": params.fill_policy,
        },
        "protocol_hash": protocol_hash,
        "parameter_hash": parameter_hash,
        "execution_snapshot_hash": execution_snapshot.snapshot_hash,
        "data": {
            "warmup_row_count": len(warmup_bars),
            "row_count": len(oos_bars),
            "start": window_start.isoformat(timespec="seconds"),
            "end": window_end.isoformat(timespec="seconds"),
            "actual_start": oos_bars[0].datetime.isoformat(timespec="seconds") if oos_bars else None,
            "actual_end": oos_bars[-1].datetime.isoformat(timespec="seconds") if oos_bars else None,
            "trading_days": sorted({bar.trading_day.isoformat() for bar in oos_bars}),
            "data_version": execution_snapshot.data_version,
            "market_data_file_id": execution_snapshot.market_data_file_id,
            "profile_active_binding_id": execution_snapshot.profile_active_binding_id,
        },
        "warmup_policy": {
            "mode": "indicator_only_no_inherited_state",
            "required_bars": WARMUP_BARS,
            "indicator_observations_at_first_oos_bar": WARMUP_BARS + 1,
            "signals_orders_trades_returns_positions_allowed": False,
            "strategy_state_reset_at_oos_start": True,
        },
        "summary": metrics,
        "trades": trades,
        "orders": orders,
        "strategy_execution_events": normalized["strategy_execution_events"],
        "warnings": normalized["warnings"],
        "equity_curve": equity_curve,
        "drawdown_curve": drawdown["drawdown_curve"],
        "runner": {
            "complexity_mode": "single_warmup_plus_oos_vector_then_oos_only_event_loop",
            "strict_vector_evaluations": 1,
            "strategy_event_bars": len(oos_bars),
            "duration_ms": round((perf_counter() - started) * 1000, 3),
        },
        "boundaries": {
            "readonly_db": True,
            "would_write_db": False,
            "would_create_backtest_task": False,
            "would_create_backtest_report": False,
            "would_touch_report14": False,
            "would_modify_parquet": False,
            "would_send_notification": False,
            "would_place_order": False,
        },
    }


def evaluate_hard_reject(summary: Mapping[str, Any], criteria: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    checks = (
        ("max_drawdown_pct", "max_drawdown_pct_gt", lambda value, threshold: value > threshold),
        ("max_consecutive_losses", "max_consecutive_losses_gte", lambda value, threshold: value >= threshold),
        ("trade_count", "trade_count_lt", lambda value, threshold: value < threshold),
        ("profit_factor", "profit_factor_lt", lambda value, threshold: value < threshold),
        ("total_return_pct", "total_return_pct_lte", lambda value, threshold: value <= threshold),
    )
    for metric, rule, predicate in checks:
        if (
            metric == "profit_factor"
            and int(summary.get("losing_trade_count") or 0) == 0
            and int(summary.get("winning_trade_count") or 0) > 0
        ):
            continue
        value = float(summary.get(metric, 0))
        threshold = float(criteria[rule])
        if predicate(value, threshold):
            reasons.append(f"{metric}:{value}:{rule}:{threshold}")
    return reasons


def build_oos_audit(
    result: Mapping[str, Any],
    *,
    execution_snapshot: FrozenProfileSelection,
    cost_payload: Mapping[str, Any],
    expected_trading_days: set[date],
    protocol: Mapping[str, Any],
    candidate_packet: Mapping[str, Any],
) -> dict[str, Any]:
    blocked: list[str] = []
    summary = dict(result.get("summary") or {})
    trades = list(result.get("trades") or [])
    orders = list(result.get("orders") or [])
    events = list(result.get("strategy_execution_events") or [])
    data = dict(result.get("data") or {})
    boundaries = dict(result.get("boundaries") or {})
    window = _oos_window(protocol)
    window_start = _naive_datetime(window["start"])
    window_end = _naive_datetime(window["end"])

    if data.get("warmup_row_count") != WARMUP_BARS:
        blocked.append(f"warm-up row count must be exactly {WARMUP_BARS}")
    if int(data.get("row_count") or 0) == 0:
        blocked.append("oos_fixed window is empty")
    if summary.get("trade_count") != len(trades):
        blocked.append("trade_count does not match trade rows")
    if len(orders) != len(trades) * 2:
        blocked.append("order_count does not equal two rows per closed trade")
    if len(result.get("equity_curve") or []) != len(trades) + 1:
        blocked.append("equity curve does not equal initial point plus closed trades")
    total_commission = sum(float(trade.get("commission") or 0) for trade in trades)
    total_slippage = sum(float(trade.get("slippage") or 0) for trade in trades)
    if not _near(total_commission, summary.get("total_commission")):
        blocked.append("total commission does not match trade rows")
    if not _near(total_slippage, summary.get("total_slippage")):
        blocked.append("total slippage does not match trade rows")
    if data.get("start") != window_start.isoformat(timespec="seconds"):
        blocked.append("result start does not match frozen oos_fixed")
    if data.get("end") != window_end.isoformat(timespec="seconds"):
        blocked.append("result end does not match frozen oos_fixed")
    expected_days = {day.isoformat() for day in expected_trading_days}
    cost_days = {str(row.get("trading_day")) for row in cost_payload.get("rows") or []}
    if set(data.get("trading_days") or []) != expected_days or cost_days != expected_days:
        blocked.append("canonical cost timeline does not cover exact OOS trading days")
    if execution_snapshot.data_role != "primary" or execution_snapshot.quality_status != "passed":
        blocked.append("execution snapshot lineage is not primary/passed")
    if execution_snapshot.quality_policy != "passed_only" or execution_snapshot.binding_status != "active":
        blocked.append("execution snapshot is not an active passed-only binding")
    candidate_snapshot = candidate_packet.get("execution_snapshot") or {}
    snapshot_comparison = {
        "snapshot_hash": execution_snapshot.snapshot_hash,
        "profile_id": execution_snapshot.profile_id,
        "profile_active_binding_id": execution_snapshot.profile_active_binding_id,
        "market_data_file_id": execution_snapshot.market_data_file_id,
        "data_version": execution_snapshot.data_version,
    }
    if any(candidate_snapshot.get(field) != value for field, value in snapshot_comparison.items()):
        blocked.append("X5-04 execution snapshot does not match X5-03 candidate")
    frozen_strategy = protocol.get("frozen_strategy") or {}
    if result.get("strategy_code") != frozen_strategy.get("strategy_code"):
        blocked.append("strategy code drifted from frozen protocol")
    if result.get("strategy_version") != frozen_strategy.get("strategy_version"):
        blocked.append("strategy version drifted from frozen protocol")
    if result.get("indicator_version") != frozen_strategy.get("indicator_version"):
        blocked.append("indicator version drifted from frozen protocol")
    execution_policy = result.get("execution_policy") or {}
    if execution_policy.get("confirmed_only") is not True:
        blocked.append("confirmed-only policy drifted from frozen protocol")
    if execution_policy.get("execution_timing") != "next_bar_open":
        blocked.append("execution timing drifted from frozen protocol")
    if execution_policy.get("fill_policy") != frozen_strategy.get("fill_policy"):
        blocked.append("fill policy drifted from frozen protocol")
    if result.get("parameter_hash") != protocol.get("parameter_hash"):
        blocked.append("parameter hash drifted from frozen protocol")
    try:
        if not verify_canonical_packet_hash(candidate_packet):
            raise OOSPrerequisiteError("X5-03 prerequisite packet hash is invalid")
        _validate_candidate_packet(candidate_packet)
    except OOSPrerequisiteError as exc:
        blocked.append(str(exc))
    for event in events:
        signal_time = _optional_datetime(event.get("signal_datetime"))
        fill_time = _optional_datetime(event.get("fill_datetime"))
        if signal_time is not None and signal_time < window_start:
            blocked.append("warm-up period produced a strategy event")
        if fill_time is not None and not (window_start <= fill_time <= window_end):
            blocked.append("strategy fill is outside oos_fixed")
        if signal_time is not None and fill_time is not None and fill_time <= signal_time:
            blocked.append("fill is not strictly after its confirmed signal")
    for trade in trades:
        entry_signal = _optional_datetime(trade.get("entry_signal_time"))
        entry_fill = _optional_datetime(trade.get("entry_datetime"))
        exit_fill = _optional_datetime(trade.get("exit_datetime"))
        if entry_signal is None or entry_fill is None or entry_fill <= entry_signal:
            blocked.append("trade entry fill is not strictly after its confirmed signal")
        if entry_fill is not None and not (window_start <= entry_fill <= window_end):
            blocked.append("trade entry fill is outside oos_fixed")
        if exit_fill is not None and not (window_start <= exit_fill <= window_end):
            blocked.append("trade exit fill is outside oos_fixed")
    if any(boundaries.get(name) for name in boundaries if name.startswith("would_")):
        blocked.append("zero-write boundary was violated")
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
    if any(marker in encoded for marker in ("/Users/", "/Volumes/", "/private/", "password", "token", "secret")):
        blocked.append("sensitive output marker is present")

    checks = {
        "warmup_isolation": "passed" if not any("warm-up" in reason for reason in blocked) else "failed",
        "window_nonempty": "passed" if int(data.get("row_count") or 0) > 0 else "failed",
        "profile_lineage": "passed"
        if execution_snapshot.data_role == "primary"
        and execution_snapshot.quality_status == "passed"
        and execution_snapshot.quality_policy == "passed_only"
        and execution_snapshot.binding_status == "active"
        else "failed",
        "cost_coverage": "passed"
        if set(data.get("trading_days") or []) == expected_days == cost_days
        else "failed",
        "trade_order_equity_metrics": "passed"
        if summary.get("trade_count") == len(trades)
        and len(orders) == len(trades) * 2
        and len(result.get("equity_curve") or []) == len(trades) + 1
        and _near(total_commission, summary.get("total_commission"))
        and _near(total_slippage, summary.get("total_slippage"))
        else "failed",
        "future_fill_timing": "failed"
        if any(
            "signal" in reason or "fill" in reason or "confirmed-only" in reason or "execution timing" in reason
            for reason in blocked
        )
        else "passed",
        "frozen_config": "failed"
        if any("frozen protocol" in reason for reason in blocked)
        else "passed",
        "candidate_binding_snapshot": "failed"
        if "X5-04 execution snapshot does not match X5-03 candidate" in blocked
        else "passed",
        "candidate_and_report14_prerequisite": "failed"
        if any("X5-03" in reason for reason in blocked)
        else "passed",
        "zero_write_report14_isolation": "failed" if "zero-write boundary was violated" in blocked else "passed",
        "sensitive_output": "failed" if "sensitive output marker is present" in blocked else "passed",
    }
    return {
        "schema_version": "htdy_oos_trust_audit_x504_v1",
        "task_id": TASK_ID,
        "audit_status": "passed" if not blocked else "failed",
        "checks": checks,
        "blocked_reasons": blocked,
        "readonly": True,
        "would_write_db": False,
    }


def generate_oos_bundle(
    session: Session,
    *,
    repo_root: Path,
    candidate_packet: Mapping[str, Any],
    x502_packet: Mapping[str, Any],
) -> dict[str, Any]:
    context = load_protocol_context(repo_root)
    protocol = context["protocol"]
    window = _oos_window(protocol)
    before = freeze_profile_selection(session, project_root=repo_root)
    market_file = session.get(MarketDataFile, before.market_data_file_id)
    if market_file is None:
        raise ValueError("frozen MarketDataFile disappeared before OOS execution")
    raw_path = Path(market_file.file_path)
    source_path = raw_path if raw_path.is_absolute() else repo_root / raw_path
    rows = _read_rows(source_path)
    start = _naive_datetime(window["start"])
    end = _naive_datetime(window["end"])
    warmup_rows, oos_rows = select_oos_rows(rows, start=start, end=end)
    warmup_bars = build_indicator_bars(warmup_rows, data_version=before.data_version)
    if len(warmup_bars) != WARMUP_BARS:
        raise ValueError(f"oos_fixed requires exactly {WARMUP_BARS} preceding warm-up bars")
    if not oos_rows:
        result = _empty_oos_result(before, context, start=start, end=end)
        timeline: dict[date, CanonicalCostDay] = {}
    else:
        trading_days = {_as_date(row.get("trading_day")) for row in oos_rows}
        timeline = build_canonical_cost_timeline(session, trading_days)
        if set(timeline) != trading_days:
            raise ValueError("canonical cost timeline is incomplete for oos_fixed")
        oos_bars = build_candidate_bars(oos_rows, timeline, data_version=before.data_version)
        result = evaluate_oos_window(
            warmup_bars,
            oos_bars,
            execution_snapshot=before,
            protocol_hash=context["protocol_hash"],
            parameter_hash=context["parameter_hash"],
            window_start=start,
            window_end=end,
        )
    cost_payload = _x504_cost_payload(timeline)
    expected_days = {_as_date(row.get("trading_day")) for row in oos_rows}
    audit = build_oos_audit(
        result,
        execution_snapshot=before,
        cost_payload=cost_payload,
        expected_trading_days=expected_days,
        protocol=protocol,
        candidate_packet=candidate_packet,
    )
    numeric_reasons = evaluate_hard_reject(
        result.get("summary") or {},
        protocol["hard_reject_criteria"]["oos_fixed_any_of"],
    )
    structural_reasons = list(audit["blocked_reasons"])
    gate = HARD_REJECT_GATE if structural_reasons or numeric_reasons else EXECUTED_GATE
    session.expire_all()
    after = freeze_profile_selection(session, project_root=repo_root)
    assert_selection_unchanged(before, after)
    return {
        "protocol_hash": context["protocol_hash"],
        "parameter_hash": context["parameter_hash"],
        "protocol": protocol,
        "execution_snapshot": before,
        "cost_payload": cost_payload,
        "result": result,
        "audit": audit,
        "gate": gate,
        "structural_reasons": structural_reasons,
        "numeric_reasons": numeric_reasons,
        "candidate_packet": candidate_packet,
        "x502_packet": x502_packet,
    }


def write_oos_artifacts(output_dir: Path, *, source_commit: str, bundle: Mapping[str, Any]) -> dict[str, Any]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("X5-04 output directory must be empty; immutable artifacts cannot be overwritten")
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot = bundle["execution_snapshot"]
    payloads: dict[str, tuple[str, Mapping[str, Any]]] = {
        "execution_snapshot": ("execution_input_snapshot.json", snapshot.payload()),
        "cost_timeline": ("oos_canonical_cost_timeline.json", bundle["cost_payload"]),
        "window_result": ("oos_fixed_result.json", bundle["result"]),
        "trust_audit": ("oos_trust_audit.json", bundle["audit"]),
    }
    artifacts: dict[str, dict[str, str]] = {}
    for name, (filename, payload) in payloads.items():
        path = output_dir / filename
        _write_json(path, payload)
        artifacts[name] = {"path": filename, "sha256": file_sha256(path)}
    packet: dict[str, Any] = {
        "schema_version": "htdy_oos_validation_packet_x504_v1",
        "task_id": TASK_ID,
        "gate": bundle["gate"],
        "status": "completed_with_hard_reject" if bundle["gate"] == HARD_REJECT_GATE else "completed",
        "source_commit": source_commit,
        "x502_packet_hash": bundle["x502_packet"]["packet_hash"],
        "x503_candidate_packet_hash": bundle["candidate_packet"]["packet_hash"],
        "candidate_identity": bundle["candidate_packet"]["candidate_identity"],
        "protocol_hash": bundle["protocol_hash"],
        "parameter_hash": bundle["parameter_hash"],
        "execution_snapshot_hash": snapshot.snapshot_hash,
        "data_identity": {
            "profile_id": snapshot.profile_id,
            "profile_active_binding_id": snapshot.profile_active_binding_id,
            "market_data_file_id": snapshot.market_data_file_id,
            "data_version": snapshot.data_version,
            "file_sha256": snapshot.file_sha256,
            "data_role": snapshot.data_role,
            "quality_status": snapshot.quality_status,
            "quality_policy": snapshot.quality_policy,
        },
        "strategy_identity": {
            "strategy_code": bundle["result"]["strategy_code"],
            "strategy_version": bundle["result"]["strategy_version"],
            "indicator_version": bundle["result"]["indicator_version"],
            "candidate_policy": bundle["result"]["candidate_policy"],
        },
        "execution_policy": bundle["result"]["execution_policy"],
        "window_id": WINDOW_ID,
        "warmup_policy": bundle["result"]["warmup_policy"],
        "row_counts": {
            "warmup": bundle["result"]["data"]["warmup_row_count"],
            "bars": bundle["result"]["data"]["row_count"],
            "trades": len(bundle["result"].get("trades") or []),
            "orders": len(bundle["result"].get("orders") or []),
            "events": len(bundle["result"].get("strategy_execution_events") or []),
            "equity": len(bundle["result"].get("equity_curve") or []),
        },
        "result_hash": packet_hash(bundle["result"]),
        "trust_audit_hash": packet_hash(bundle["audit"]),
        "cost_timeline_hash": bundle["cost_payload"]["timeline_hash"],
        "hard_reject": {
            "triggered": bundle["gate"] == HARD_REJECT_GATE,
            "structural_reasons": bundle["structural_reasons"],
            "numeric_reasons": bundle["numeric_reasons"],
        },
        "boundaries": bundle["result"]["boundaries"],
        "artifacts": artifacts,
    }
    packet["packet_hash"] = packet_hash(packet)
    _write_json(output_dir / "OOS_VALIDATION_RESULT.json", packet)
    markdown = output_dir / "OOS_VALIDATION_RESULT.md"
    markdown.write_text(_render_markdown(packet, bundle["result"], bundle["audit"]), encoding="utf-8")
    return packet


def build_sanitized_failure_packet(*, source_commit: str, reason: str) -> dict[str, Any]:
    sanitized = _sanitize_error(reason)
    packet: dict[str, Any] = {
        "schema_version": "htdy_oos_validation_failure_x504_v1",
        "task_id": TASK_ID,
        "gate": HARD_REJECT_GATE,
        "status": "failed_review_required",
        "source_commit": source_commit,
        "windows": [{"window_id": WINDOW_ID, "status": "failed", "error": sanitized}],
        "hard_reject": {"triggered": True, "structural_reasons": [sanitized], "numeric_reasons": []},
        "boundaries": {
            "would_write_db": False,
            "would_create_backtest_task": False,
            "would_create_backtest_report": False,
            "would_touch_report14": False,
            "would_modify_parquet": False,
        },
    }
    packet["packet_hash"] = packet_hash(packet)
    return packet


def _oos_window(protocol: Mapping[str, Any]) -> dict[str, Any]:
    windows = [dict(window) for window in protocol.get("windows") or [] if window.get("id") == WINDOW_ID]
    if len(windows) != 1:
        raise ValueError("frozen protocol must contain exactly one oos_fixed window")
    return windows[0]


def _read_rows(path: Path) -> list[dict[str, Any]]:
    columns = [
        "datetime",
        "trading_day",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "provider",
        "source",
        "data_role",
        "quality_status",
        "data_version",
        "symbol",
        "contract",
        "period",
    ]
    return pq.ParquetFile(path).read(columns=columns).to_pylist()


def _validate_lineage_row(row: Mapping[str, Any], *, data_version: str, index: int) -> None:
    expected = {
        "provider": "rqdata",
        "source": "rqdata",
        "data_role": "primary",
        "quality_status": "passed",
        "data_version": data_version,
        "symbol": "jm",
        "contract": "jm.MAIN",
        "period": "15m",
    }
    for field, value in expected.items():
        if str(row.get(field)) != value:
            raise ValueError(
                f"OOS input lineage mismatch at index {index}: "
                f"{field} expected={value!r} actual={row.get(field)!r}"
            )


def _empty_oos_result(
    selection: FrozenProfileSelection,
    context: Mapping[str, Any],
    *,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    params = validate_params()
    equity = generate_equity_curve([], initial_capital=params.initial_capital)
    drawdown = generate_drawdown_curve(equity)
    metrics = compute_report_metrics(
        summary={},
        trades=[],
        equity_curve=equity,
        drawdown_curve=drawdown["drawdown_curve"],
        start=start,
        end=end,
        default_initial_capital=params.initial_capital,
    )
    metrics.update(
        {
            "total_return_pct": 0.0,
            "profit_factor": 0.0,
            "profit_factor_defined": False,
            "winning_trade_count": 0,
            "losing_trade_count": 0,
            "largest_loss_trade": 0.0,
            "signal_count": 0,
            "no_trade_reasons": {"empty_oos_window": 1},
            "fee_totals": 0.0,
            "slippage_totals": 0.0,
        }
    )
    return {
        "schema_version": "htdy_oos_fixed_result_x504_v1",
        "task_id": TASK_ID,
        "window_id": WINDOW_ID,
        "status": "failed",
        "strategy_code": params.strategy_code,
        "strategy_version": params.strategy_version,
        "candidate_policy": params.candidate_policy,
        "indicator_version": params.indicator_version,
        "execution_policy": {
            "confirmed_only": params.confirmed_only,
            "execution_timing": params.execution_timing,
            "fill_policy": params.fill_policy,
        },
        "protocol_hash": context["protocol_hash"],
        "parameter_hash": context["parameter_hash"],
        "execution_snapshot_hash": selection.snapshot_hash,
        "data": {
            "warmup_row_count": WARMUP_BARS,
            "row_count": 0,
            "start": start.isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds"),
            "actual_start": None,
            "actual_end": None,
            "trading_days": [],
            "data_version": selection.data_version,
            "market_data_file_id": selection.market_data_file_id,
            "profile_active_binding_id": selection.profile_active_binding_id,
        },
        "warmup_policy": {
            "mode": "indicator_only_no_inherited_state",
            "required_bars": WARMUP_BARS,
            "indicator_observations_at_first_oos_bar": WARMUP_BARS + 1,
            "signals_orders_trades_returns_positions_allowed": False,
            "strategy_state_reset_at_oos_start": True,
        },
        "summary": metrics,
        "trades": [],
        "orders": [],
        "strategy_execution_events": [],
        "warnings": ["empty_oos_window"],
        "equity_curve": equity,
        "drawdown_curve": drawdown["drawdown_curve"],
        "runner": {"strict_vector_evaluations": 0, "strategy_event_bars": 0},
        "boundaries": {
            "readonly_db": True,
            "would_write_db": False,
            "would_create_backtest_task": False,
            "would_create_backtest_report": False,
            "would_touch_report14": False,
            "would_modify_parquet": False,
            "would_send_notification": False,
            "would_place_order": False,
        },
    }


def _x504_cost_payload(timeline: Mapping[date, CanonicalCostDay]) -> dict[str, Any]:
    payload = cost_timeline_payload(timeline)
    return {
        **payload,
        "schema_version": "htdy_oos_canonical_cost_timeline_x504_v1",
        "task_id": TASK_ID,
        "window_id": WINDOW_ID,
    }


def _naive_datetime(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=None)


def _optional_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    return _naive_datetime(value)


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        raise ValueError("OOS input missing trading_day")
    return date.fromisoformat(str(value)[:10])


def _count_values(values: Sequence[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _near(left: Any, right: Any, tolerance: float = 1e-8) -> bool:
    try:
        return abs(float(left) - float(right)) <= tolerance
    except (TypeError, ValueError):
        return False


def _sanitize_error(reason: str) -> str:
    sanitized = str(reason)
    for prefix in ("/Users/", "/Volumes/", "/private/"):
        if prefix in sanitized:
            sanitized = "sanitized_runtime_error"
    lowered = sanitized.lower()
    if any(marker in lowered for marker in ("password", "token", "secret", "webhook")):
        return "sanitized_sensitive_runtime_error"
    return sanitized[:500]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False, default=str) + "\n",
        encoding="utf-8",
    )


def _render_markdown(packet: Mapping[str, Any], result: Mapping[str, Any], audit: Mapping[str, Any]) -> str:
    summary = result.get("summary") or {}
    return "\n".join(
        [
            "# HTDY X5-04 OOS Validation",
            "",
            f"- Gate: `{packet.get('gate')}`",
            f"- Window: `{WINDOW_ID}`",
            f"- Audit: `{audit.get('audit_status')}`",
            f"- Bars: `{(result.get('data') or {}).get('row_count')}`",
            f"- Trades: `{summary.get('trade_count')}`",
            f"- Total return: `{summary.get('total_return_pct')}`",
            f"- Max drawdown: `{summary.get('max_drawdown_pct')}`",
            "- Warm-up: `72 indicator-only bars; no inherited strategy state`",
            "",
            "## Boundary",
            "",
            "- No canonical database, BacktestTask, BacktestReport, report14, Parquet, live, or notification write.",
            "- This Gate is research validation evidence, not a live-trading or profitability approval.",
            "",
        ]
    )


__all__ = [
    "DEFAULT_CANDIDATE_PACKET_RELATIVE_PATH",
    "EXECUTED_GATE",
    "HARD_REJECT_GATE",
    "IndicatorBar",
    "OOSPrerequisiteError",
    "PREREQUISITE_GATE",
    "TASK_ID",
    "WARMUP_BARS",
    "assert_selection_unchanged",
    "build_indicator_bars",
    "build_oos_audit",
    "build_sanitized_failure_packet",
    "evaluate_hard_reject",
    "evaluate_oos_window",
    "generate_oos_bundle",
    "load_candidate_prerequisite",
    "load_x502_packet",
    "select_oos_rows",
    "verify_canonical_packet_hash",
    "write_oos_artifacts",
]
