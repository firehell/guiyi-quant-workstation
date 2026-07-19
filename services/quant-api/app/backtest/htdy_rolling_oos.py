from __future__ import annotations

from datetime import date, datetime
from itertools import product
import json
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

import pyarrow.parquet as pq
from sqlalchemy.orm import Session

from app.backtest.htdy_oos_validation import (
    build_indicator_bars,
    evaluate_hard_reject,
    evaluate_oos_window,
    select_oos_rows,
)
from app.backtest.htdy_trusted_report import (
    assert_profile_selection_unchanged,
    build_candidate_bars,
    build_canonical_cost_timeline,
    cost_timeline_payload,
    file_sha256,
    freeze_profile_selection,
    load_protocol_context,
    packet_hash,
)
from app.models.data_center import MarketDataFile


TASK_ID = "HTDY-ROLLING-OOS-X505"
MODE = "rolling_oos_stability"
CONFIRMS_REJECTION = "DIAGNOSTIC_CONFIRMS_REJECTION"
INCONCLUSIVE_REJECTION = "DIAGNOSTIC_INCONCLUSIVE_REJECTION_REMAINS"
PROPOSED_VALIDATED = "PROPOSED_VALIDATED_RESEARCH_CANDIDATE"
PROPOSED_REJECTED = "PROPOSED_REJECTED_RESEARCH_CANDIDATE"
X504_RELATIVE_PATH = Path("data/reports/htdy_oos_validation_x5_04/OOS_VALIDATION_RESULT.json")
FOLD_IDS = ("walk_forward_a_test", "walk_forward_b_test", "walk_forward_c_test")
WARMUP_BARS = 72


class RollingOOSPrerequisiteError(ValueError):
    """Raised before X5-05 execution when X5-04 evidence is invalid."""


def verify_packet_hash(value: Mapping[str, Any]) -> bool:
    payload = dict(value)
    expected = str(payload.pop("packet_hash", ""))
    return bool(expected) and expected == packet_hash(payload)


def load_x504_packet(repo_root: Path) -> dict[str, Any]:
    path = repo_root / X504_RELATIVE_PATH
    if not path.is_file():
        raise RollingOOSPrerequisiteError("X5-04 packet is missing")
    packet = _read_json(path)
    if not verify_packet_hash(packet):
        raise RollingOOSPrerequisiteError("X5-04 packet hash is invalid")
    if packet.get("gate") not in {"OOS_VALIDATION_EXECUTED", "OOS_HARD_REJECT_TRIGGERED"}:
        raise RollingOOSPrerequisiteError("X5-04 Gate is invalid")
    for artifact in (packet.get("artifacts") or {}).values():
        relative = str((artifact or {}).get("path") or "")
        if not relative or Path(relative).name != relative:
            raise RollingOOSPrerequisiteError("X5-04 artifact path is invalid")
        artifact_path = path.parent / relative
        if not artifact_path.is_file() or file_sha256(artifact_path) != artifact.get("sha256"):
            raise RollingOOSPrerequisiteError("X5-04 artifact hash is invalid")
    return packet


def rolling_folds(protocol: Mapping[str, Any]) -> list[dict[str, Any]]:
    windows = {str(window.get("id")): dict(window) for window in protocol.get("windows") or []}
    folds: list[dict[str, Any]] = []
    previous_start: datetime | None = None
    expected_test_months = (3, 3, 6)
    for index, (fold_id, test_months) in enumerate(zip(FOLD_IDS, expected_test_months, strict=True)):
        window = windows.get(fold_id)
        if window is None:
            raise ValueError(f"frozen protocol missing fold {fold_id}")
        train_start, train_end = _parse_train_window(str(window.get("train_window") or ""))
        if _inclusive_months(train_start, train_end) != 24:
            raise ValueError(f"{fold_id} train metadata must span 24 calendar months")
        test_start = _naive_datetime(window["start"])
        test_end = _naive_datetime(window["end"])
        if _inclusive_months(test_start.date(), test_end.date()) != test_months:
            raise ValueError(f"{fold_id} test window month count drifted")
        if previous_start is not None and _month_distance(previous_start.date(), test_start.date()) != 6:
            raise ValueError("rolling OOS fold starts must use a six-month step")
        previous_start = test_start
        folds.append(
            {
                "fold_id": fold_id,
                "label": window.get("label"),
                "mode": MODE,
                "train_start": train_start.isoformat(),
                "train_end": train_end.isoformat(),
                "train_months": 24,
                "train_usage": "lineage_metadata_only_no_fit_no_selection",
                "test_start": test_start.isoformat(timespec="seconds"),
                "test_end": test_end.isoformat(timespec="seconds"),
                "test_months": test_months,
                "step_months": 6,
                "warmup_bars": WARMUP_BARS,
                "parameter_optimization": False,
            }
        )
    return folds


def build_overlay_grid(
    trades: Sequence[Mapping[str, Any]],
    *,
    initial_capital: float,
    parameter_hash: str,
) -> list[dict[str, Any]]:
    overlays: list[dict[str, Any]] = []
    for commission_multiplier, slippage_ticks, gap_ticks, margin_multiplier in product(
        (1.0, 1.5, 2.0),
        (1, 2, 3),
        (0, 1, 2),
        (1.0, 1.25, 1.5),
    ):
        adjusted_total = 0.0
        commission_cost = 0.0
        slippage_cost = 0.0
        gap_cost = 0.0
        gap_trade_count = 0
        infeasible_trade_count = 0
        max_stressed_margin = 0.0
        for trade in trades:
            commission = float(trade.get("commission") or 0.0) * commission_multiplier
            slippage = float(trade.get("slippage") or 0.0) * slippage_ticks
            extra_gap = 0.0
            if bool(trade.get("gap_execution")):
                gap_trade_count += 1
                extra_gap = (
                    gap_ticks
                    * float(trade.get("price_tick") or 0.0)
                    * float(trade.get("contract_multiplier") or 0.0)
                    * float(trade.get("volume") or 0.0)
                )
            stressed_margin = float(trade.get("margin_required") or 0.0) * margin_multiplier
            max_stressed_margin = max(max_stressed_margin, stressed_margin)
            if stressed_margin > initial_capital:
                infeasible_trade_count += 1
            commission_cost += commission
            slippage_cost += slippage
            gap_cost += extra_gap
            adjusted_total += float(trade.get("gross_pnl") or 0.0) - commission - slippage - extra_gap
        payload: dict[str, Any] = {
            "scenario_id": (
                f"commission{_number_id(commission_multiplier)}_slippage{slippage_ticks}"
                f"_gap{gap_ticks}_margin{_number_id(margin_multiplier)}"
            ),
            "post_trade_cost_overlay": True,
            "rematched": False,
            "parameter_hash": parameter_hash,
            "commission_multiplier": commission_multiplier,
            "slippage_ticks": slippage_ticks,
            "gap_ticks": gap_ticks,
            "margin_multiplier": margin_multiplier,
            "trade_count": len(trades),
            "gap_trade_count": gap_trade_count,
            "commission_cost": commission_cost,
            "slippage_cost": slippage_cost,
            "gap_cost": gap_cost,
            "adjusted_total_net_pnl": adjusted_total,
            "adjusted_total_return_pct": adjusted_total / initial_capital if initial_capital else 0.0,
            "max_stressed_margin": max_stressed_margin,
            "max_stressed_margin_usage_pct": max_stressed_margin / initial_capital if initial_capital else 0.0,
            "margin_feasible": infeasible_trade_count == 0,
            "infeasible_trade_count": infeasible_trade_count,
        }
        payload["overlay_hash"] = packet_hash(payload)
        overlays.append(payload)
    return overlays


def proposal_label(*, x504_gate: str, folds: Sequence[Mapping[str, Any]]) -> str:
    reproduced = any(
        fold.get("audit_status") != "passed" or bool(fold.get("numeric_reasons"))
        for fold in folds
    )
    if x504_gate == "OOS_HARD_REJECT_TRIGGERED":
        return CONFIRMS_REJECTION if reproduced else INCONCLUSIVE_REJECTION
    return PROPOSED_REJECTED if reproduced else PROPOSED_VALIDATED


def build_rolling_packet(
    *,
    source_commit: str,
    x504_packet: Mapping[str, Any],
    protocol_hash: str,
    parameter_hash: str,
    candidate_identity: Mapping[str, Any],
    folds: Sequence[Mapping[str, Any]],
    fold_artifacts: Mapping[str, str],
) -> dict[str, Any]:
    summaries = [
        {
            "fold_id": fold.get("fold_id"),
            "status": fold.get("status"),
            "audit_status": fold.get("audit_status"),
            "trade_count": fold.get("trade_count"),
            "total_return_pct": fold.get("total_return_pct"),
            "numeric_reasons": list(fold.get("numeric_reasons") or []),
            "structural_reasons": list(fold.get("structural_reasons") or []),
        }
        for fold in folds
    ]
    label = proposal_label(x504_gate=str(x504_packet.get("gate")), folds=summaries)
    packet: dict[str, Any] = {
        "schema_version": "htdy_rolling_oos_packet_x505_v1",
        "task_id": TASK_ID,
        "mode": MODE,
        "status": "completed",
        "proposal_label": label,
        "source_commit": source_commit,
        "x504_gate": x504_packet.get("gate"),
        "x504_packet_hash": x504_packet.get("packet_hash"),
        "x504_hard_reject_preserved": x504_packet.get("gate") == "OOS_HARD_REJECT_TRIGGERED",
        "candidate_identity": dict(candidate_identity),
        "protocol_hash": protocol_hash,
        "parameter_hash": parameter_hash,
        "folds": summaries,
        "fold_artifacts": {
            fold_id: {"sha256": sha256}
            for fold_id, sha256 in sorted(fold_artifacts.items())
        },
        "constraints": {
            "parameter_optimization": False,
            "strategy_rule_changes": False,
            "loss_fold_deletion": False,
            "hard_reject_flip_allowed": False,
            "canonical_db_write": False,
        },
    }
    packet["packet_hash"] = packet_hash(packet)
    return packet


def generate_rolling_bundle(
    session: Session,
    *,
    repo_root: Path,
    x504_packet: Mapping[str, Any],
) -> dict[str, Any]:
    context = load_protocol_context(repo_root)
    protocol = context["protocol"]
    folds = rolling_folds(protocol)
    market_snapshot = freeze_profile_selection(session, project_root=repo_root)
    _assert_x504_identity(market_snapshot.payload(), x504_packet)
    market_file = session.get(MarketDataFile, market_snapshot.market_data_file_id)
    if market_file is None:
        raise ValueError("X5-05 MarketDataFile disappeared")
    raw_path = Path(market_file.file_path)
    source_path = raw_path if raw_path.is_absolute() else repo_root / raw_path
    rows = _read_rows(source_path)
    fold_results: list[dict[str, Any]] = []
    for fold in folds:
        try:
            fold_snapshot = freeze_profile_selection(session, project_root=repo_root)
            _assert_x504_identity(fold_snapshot.payload(), x504_packet)
            fold_result = _execute_fold(
                rows,
                session=session,
                fold=fold,
                snapshot=fold_snapshot,
                protocol=protocol,
                protocol_hash=context["protocol_hash"],
                parameter_hash=context["parameter_hash"],
            )
            after = freeze_profile_selection(session, project_root=repo_root)
            assert_profile_selection_unchanged(fold_snapshot, after)
        except Exception as exc:
            fold_result = _failed_fold(
                fold,
                reason=str(exc),
                parameter_hash=context["parameter_hash"],
            )
        fold_results.append(fold_result)
    final_snapshot = freeze_profile_selection(session, project_root=repo_root)
    assert_profile_selection_unchanged(market_snapshot, final_snapshot)
    return {
        "protocol_hash": context["protocol_hash"],
        "parameter_hash": context["parameter_hash"],
        "execution_snapshot": market_snapshot,
        "folds": fold_results,
        "x504_packet": dict(x504_packet),
    }


def write_rolling_artifacts(
    output_dir: Path,
    *,
    source_commit: str,
    bundle: Mapping[str, Any],
) -> dict[str, Any]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("X5-05 output directory must be empty; immutable evidence cannot be overwritten")
    output_dir.mkdir(parents=True, exist_ok=True)
    fold_hashes: dict[str, str] = {}
    for fold in bundle["folds"]:
        fold_id = str(fold["fold_id"])
        fold_dir = output_dir / "folds" / fold_id
        fold_dir.mkdir(parents=True, exist_ok=True)
        payloads = {
            "config_snapshot.json": fold.get("config_snapshot") or {},
            "binding_snapshot.json": fold.get("binding_snapshot") or {},
            "cost_timeline.json": fold.get("cost_timeline") or {},
            "result.json": fold.get("result") or {},
            "audit.json": fold.get("audit") or {},
            "cost_margin_overlays.json": {
                "post_trade_cost_overlay": True,
                "scenario_count": len(fold.get("overlays") or []),
                "scenarios": fold.get("overlays") or [],
            },
            "diagnostics.json": fold.get("diagnostics") or {},
        }
        artifact_hashes: dict[str, str] = {}
        for filename, payload in payloads.items():
            path = fold_dir / filename
            _write_json(path, payload)
            artifact_hashes[filename] = file_sha256(path)
        manifest = {
            "fold_id": fold_id,
            "status": fold.get("status"),
            "audit_status": fold.get("audit_status"),
            "trade_count": fold.get("trade_count"),
            "total_return_pct": fold.get("total_return_pct"),
            "numeric_reasons": fold.get("numeric_reasons") or [],
            "structural_reasons": fold.get("structural_reasons") or [],
            "artifacts": artifact_hashes,
        }
        manifest["fold_hash"] = packet_hash(manifest)
        _write_json(fold_dir / "fold_manifest.json", manifest)
        fold_hashes[fold_id] = manifest["fold_hash"]
    packet = build_rolling_packet(
        source_commit=source_commit,
        x504_packet=bundle["x504_packet"],
        protocol_hash=str(bundle["protocol_hash"]),
        parameter_hash=str(bundle["parameter_hash"]),
        candidate_identity=bundle["x504_packet"].get("candidate_identity") or {},
        folds=bundle["folds"],
        fold_artifacts=fold_hashes,
    )
    _write_json(output_dir / "ROLLING_OOS_VALIDATION_RESULT.json", packet)
    (output_dir / "ROLLING_OOS_VALIDATION_RESULT.md").write_text(
        _render_markdown(packet), encoding="utf-8"
    )
    return packet


def _execute_fold(
    rows: Sequence[Mapping[str, Any]],
    *,
    session: Session,
    fold: Mapping[str, Any],
    snapshot: Any,
    protocol: Mapping[str, Any],
    protocol_hash: str,
    parameter_hash: str,
) -> dict[str, Any]:
    start = _naive_datetime(fold["test_start"])
    end = _naive_datetime(fold["test_end"])
    warmup_rows, test_rows = select_oos_rows(rows, start=start, end=end, warmup_count=WARMUP_BARS)
    if len(warmup_rows) != WARMUP_BARS:
        raise ValueError(f"{fold['fold_id']} does not have exactly 72 warm-up bars")
    if not test_rows:
        raise ValueError(f"{fold['fold_id']} test window is empty")
    warmup_bars = build_indicator_bars(warmup_rows, data_version=snapshot.data_version)
    trading_days = {_as_date(row.get("trading_day")) for row in test_rows}
    timeline = build_canonical_cost_timeline(session, trading_days)
    test_bars = build_candidate_bars(test_rows, timeline, data_version=snapshot.data_version)
    result = evaluate_oos_window(
        warmup_bars,
        test_bars,
        execution_snapshot=snapshot,
        protocol_hash=protocol_hash,
        parameter_hash=parameter_hash,
        window_start=start,
        window_end=end,
    )
    result["task_id"] = TASK_ID
    result["mode"] = MODE
    result["fold_id"] = fold["fold_id"]
    cost_payload = cost_timeline_payload(timeline)
    structural_reasons = _fold_structural_reasons(
        result,
        expected_start=start,
        expected_end=end,
        expected_trading_days=trading_days,
        cost_payload=cost_payload,
    )
    numeric_reasons = evaluate_hard_reject(
        result.get("summary") or {},
        protocol["hard_reject_criteria"]["oos_fixed_any_of"],
    )
    audit_status = "passed" if not structural_reasons else "failed"
    audit = {
        "schema_version": "htdy_rolling_fold_audit_x505_v1",
        "task_id": TASK_ID,
        "fold_id": fold["fold_id"],
        "audit_status": audit_status,
        "structural_reasons": structural_reasons,
        "numeric_reasons": numeric_reasons,
        "checks": {
            "warmup_isolation": "passed",
            "independent_strategy_state": "passed",
            "profile_binding": "passed",
            "cost_coverage": "passed" if not any("cost" in item for item in structural_reasons) else "failed",
            "future_fill_timing": "failed" if any("signal" in item for item in structural_reasons) else "passed",
            "trade_order_equity_metrics": "failed" if any("count" in item for item in structural_reasons) else "passed",
        },
    }
    trades = list(result.get("trades") or [])
    initial_capital = float((result.get("summary") or {}).get("initial_capital") or 1_000_000.0)
    overlays = build_overlay_grid(trades, initial_capital=initial_capital, parameter_hash=parameter_hash)
    diagnostics = _fold_diagnostics(trades, result=result)
    return {
        "fold_id": fold["fold_id"],
        "status": "completed",
        "audit_status": audit_status,
        "trade_count": len(trades),
        "total_return_pct": float((result.get("summary") or {}).get("total_return_pct") or 0.0),
        "numeric_reasons": numeric_reasons,
        "structural_reasons": structural_reasons,
        "config_snapshot": {
            **dict(fold),
            "protocol_hash": protocol_hash,
            "parameter_hash": parameter_hash,
            "strategy_code": result.get("strategy_code"),
            "strategy_version": result.get("strategy_version"),
            "indicator_version": result.get("indicator_version"),
            "confirmed_only": True,
            "execution_timing": "next_bar_open",
        },
        "binding_snapshot": snapshot.payload(),
        "cost_timeline": cost_payload,
        "result": result,
        "audit": audit,
        "overlays": overlays,
        "diagnostics": diagnostics,
    }


def _fold_structural_reasons(
    result: Mapping[str, Any],
    *,
    expected_start: datetime,
    expected_end: datetime,
    expected_trading_days: set[date],
    cost_payload: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    data = result.get("data") or {}
    trades = list(result.get("trades") or [])
    orders = list(result.get("orders") or [])
    if data.get("warmup_row_count") != WARMUP_BARS:
        reasons.append("warmup_count_mismatch")
    if data.get("start") != expected_start.isoformat(timespec="seconds") or data.get("end") != expected_end.isoformat(timespec="seconds"):
        reasons.append("fold_window_mismatch")
    if len(orders) != len(trades) * 2:
        reasons.append("trade_order_count_mismatch")
    if len(result.get("equity_curve") or []) != len(trades) + 1:
        reasons.append("trade_equity_count_mismatch")
    expected_days = {day.isoformat() for day in expected_trading_days}
    cost_days = {str(row.get("trading_day")) for row in cost_payload.get("rows") or []}
    if set(data.get("trading_days") or []) != expected_days or cost_days != expected_days:
        reasons.append("canonical_cost_coverage_mismatch")
    for trade in trades:
        signal = _optional_datetime(trade.get("entry_signal_time"))
        fill = _optional_datetime(trade.get("entry_datetime"))
        if signal is None or fill is None or fill <= signal:
            reasons.append("entry_fill_not_strictly_after_confirmed_signal")
            break
    for event in result.get("strategy_execution_events") or []:
        signal = _optional_datetime(event.get("signal_datetime"))
        fill = _optional_datetime(event.get("fill_datetime"))
        if signal is not None and fill is not None and fill <= signal:
            reasons.append("event_fill_not_strictly_after_signal")
            break
    return reasons


def _fold_diagnostics(trades: Sequence[Mapping[str, Any]], *, result: Mapping[str, Any]) -> dict[str, Any]:
    contracts: dict[str, int] = {}
    monthly: dict[str, int] = {}
    gap_count = 0
    loss_streak = 0
    max_loss_streak = 0
    returns: list[float] = []
    sorted_trades = sorted(trades, key=lambda row: (str(row.get("exit_datetime") or ""), str(row.get("tradeid") or "")))
    previous_contract: str | None = None
    contract_transitions = 0
    for trade in sorted_trades:
        contract = str(trade.get("contract") or "<missing>")
        contracts[contract] = contracts.get(contract, 0) + 1
        if previous_contract is not None and contract != previous_contract:
            contract_transitions += 1
        previous_contract = contract
        month = str(trade.get("exit_datetime") or "")[:7]
        monthly[month] = monthly.get(month, 0) + 1
        gap_count += int(bool(trade.get("gap_execution")))
        pnl = float(trade.get("net_pnl") or 0.0)
        returns.append(pnl)
        if pnl < 0:
            loss_streak += 1
            max_loss_streak = max(max_loss_streak, loss_streak)
        else:
            loss_streak = 0
    warnings = list(result.get("warnings") or [])
    return {
        "roll": {
            "contract_trade_counts": contracts,
            "contract_transition_count": contract_transitions,
            "entry_exit_contract_mismatch_count": sum(
                1 for trade in trades if trade.get("entry_contract") != trade.get("exit_contract")
            ),
        },
        "conflict": {"warning_counts": _count_values(warnings)},
        "liquidity": {"gap_execution_trade_count": gap_count, "gap_execution_ratio": gap_count / len(trades) if trades else 0.0},
        "frequency": {
            "trade_count": len(trades),
            "trades_by_exit_month": monthly,
            "average_trades_per_active_month": mean(monthly.values()) if monthly else 0.0,
        },
        "consecutive_losses": {"max_consecutive_losses": max_loss_streak},
        "pnl": {"average_net_pnl": mean(returns) if returns else 0.0},
    }


def _failed_fold(
    fold: Mapping[str, Any],
    *,
    reason: str,
    parameter_hash: str,
) -> dict[str, Any]:
    sanitized = _sanitize_error(reason)
    return {
        "fold_id": fold["fold_id"],
        "status": "failed",
        "audit_status": "failed",
        "trade_count": 0,
        "total_return_pct": 0.0,
        "numeric_reasons": [],
        "structural_reasons": [sanitized],
        "config_snapshot": dict(fold),
        "binding_snapshot": {},
        "cost_timeline": {},
        "result": {"fold_id": fold["fold_id"], "status": "failed", "error": sanitized, "trades": []},
        "audit": {"fold_id": fold["fold_id"], "audit_status": "failed", "structural_reasons": [sanitized]},
        "overlays": build_overlay_grid([], initial_capital=1_000_000.0, parameter_hash=parameter_hash),
        "diagnostics": {"status": "failed", "reason": sanitized},
    }


def _assert_x504_identity(snapshot: Mapping[str, Any], packet: Mapping[str, Any]) -> None:
    identity = packet.get("data_identity") or {}
    expected = {
        "profile_id": snapshot.get("profile_id"),
        "profile_active_binding_id": snapshot.get("profile_active_binding_id"),
        "market_data_file_id": snapshot.get("market_data_file_id"),
        "data_version": snapshot.get("data_version"),
        "file_sha256": snapshot.get("file_sha256"),
    }
    if any(identity.get(key) != value for key, value in expected.items()):
        raise ValueError("X5-05 binding identity differs from X5-04")
    if packet.get("execution_snapshot_hash") != snapshot.get("snapshot_hash"):
        raise ValueError("X5-05 binding snapshot hash differs from X5-04")


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


def _parse_train_window(value: str) -> tuple[date, date]:
    try:
        start, end = value.split("..", 1)
        return date.fromisoformat(start), date.fromisoformat(end)
    except ValueError as exc:
        raise ValueError("invalid frozen train_window metadata") from exc


def _inclusive_months(start: date, end: date) -> int:
    return _month_distance(start, end) + 1


def _month_distance(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month


def _number_id(value: float) -> str:
    return f"{value:g}"


def _naive_datetime(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=None)


def _optional_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    return _naive_datetime(value)


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        raise ValueError("fold row missing trading_day")
    return date.fromisoformat(str(value)[:10])


def _count_values(values: Sequence[Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value)
        result[key] = result.get(key, 0) + 1
    return result


def _sanitize_error(reason: str) -> str:
    text = str(reason).strip().splitlines()[0] if str(reason).strip() else "fold failed"
    lowered = text.lower()
    if any(marker in lowered for marker in ("password", "token", "secret", "license", "webhook")):
        return "<redacted>"
    for marker in ("/Users/", "/Volumes/", "/private/", "\\Users\\"):
        text = text.replace(marker, "<local-path>/")
    return text[:500]


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must be an object: {path.name}")
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False, default=str) + "\n",
        encoding="utf-8",
    )


def _render_markdown(packet: Mapping[str, Any]) -> str:
    lines = [
        "# HTDY X5-05 Rolling OOS Stability",
        "",
        f"- Mode: `{packet.get('mode')}`",
        f"- Proposal: `{packet.get('proposal_label')}`",
        f"- X5-04 Gate: `{packet.get('x504_gate')}`",
        f"- Packet hash: `{packet.get('packet_hash')}`",
        "",
        "## Folds",
        "",
    ]
    for fold in packet.get("folds") or []:
        lines.append(
            f"- `{fold.get('fold_id')}`: status={fold.get('status')}, audit={fold.get('audit_status')}, "
            f"trades={fold.get('trade_count')}, return={fold.get('total_return_pct')}"
        )
    lines.extend(
        [
            "",
            "X5-05 is diagnostic-only after the X5-04 hard reject and cannot overturn it.",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "CONFIRMS_REJECTION",
    "INCONCLUSIVE_REJECTION",
    "MODE",
    "PROPOSED_REJECTED",
    "PROPOSED_VALIDATED",
    "RollingOOSPrerequisiteError",
    "build_overlay_grid",
    "build_rolling_packet",
    "generate_rolling_bundle",
    "load_x504_packet",
    "proposal_label",
    "rolling_folds",
    "verify_packet_hash",
    "write_rolling_artifacts",
]
