#!/usr/bin/env python3
"""Frozen-window OOS validation runner for JM V1B report 14 baseline.

Read-only by default: does not write to backtest_tasks / backtest_reports.

Outputs JSON/Markdown under data/reports/oos_validation_<timestamp>/.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from math import isclose
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.backtest.drawdown_curve_generator import generate_drawdown_curve  # noqa: E402
from app.backtest.equity_curve_generator import generate_equity_curve  # noqa: E402
from app.backtest.jm_v1b_result_enricher import enrich_jm_v1b_result, should_enrich_jm_v1b_result  # noqa: E402
from app.backtest.report_metrics import compute_report_metrics  # noqa: E402
from app.backtest.v1b_jm_tasks import build_jm_v1b_task_config  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.backtest import BacktestReportModel  # noqa: E402
from app.schemas.backtest import BacktestTaskConfig  # noqa: E402
from app.vnpy_integration.backtest_runner import GuiyiBacktestRequest, VnpyBacktestRunner  # noqa: E402
from app.vnpy_integration.result_converter import convert_vnpy_result  # noqa: E402

DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "oos" / "jm_v1b_report14_frozen.json"
SENSITIVE_MARKERS = ("/Users/", "/Volumes/", "/private/", "webhook", "token", "password", "license", "secret")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JM V1B frozen-window OOS validation (no DB write by default).")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Frozen OOS config JSON")
    parser.add_argument("--list-windows", action="store_true", help="List configured windows and exit")
    parser.add_argument("--window", action="append", dest="windows", help="Run only these window id(s); repeatable")
    parser.add_argument("--run", action="store_true", help="Execute vn.py backtests (otherwise plan-only JSON)")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: data/reports/oos_validation_<utc>)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_payload = json.loads(args.config.read_text(encoding="utf-8"))
    windows = config_payload.get("windows") or []
    if args.list_windows:
        print(json.dumps({"windows": windows}, ensure_ascii=False, indent=2))
        return 0

    selected = _select_windows(windows, args.windows)
    if not selected:
        print(json.dumps({"ok": False, "error": "no windows selected"}, ensure_ascii=False))
        return 1

    output_dir = args.output_dir or (
        PROJECT_ROOT / "data" / "reports" / f"oos_validation_{datetime.utcnow():%Y%m%d_%H%M%S}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    baseline_report_id = int(config_payload.get("baseline_report_id") or 14)
    plan: dict[str, Any] = {
        "ok": True,
        "readonly": not args.run,
        "persist_to_db": False,
        "would_write_db": False,
        "would_run_rqdata": False,
        "would_send_notifications": False,
        "baseline_report_id": baseline_report_id,
        "frozen_strategy": config_payload.get("frozen_strategy"),
        "frozen_data_policy": config_payload.get("frozen_data_policy"),
        "frozen_costs": config_payload.get("frozen_costs"),
        "config_path": str(args.config),
        "windows": [],
    }

    if not args.run:
        for window in selected:
            plan["windows"].append({"window_id": window.get("id"), "window": window, "status": "plan_only"})
        _write_outputs(output_dir, plan, args.format)
        return 0

    runner = VnpyBacktestRunner()
    with SessionLocal() as session:
        baseline = _load_baseline_summary(session, baseline_report_id)
        plan["baseline"] = baseline
        base_spec = build_jm_v1b_task_config(session, entry_interval="15m")
        for window in selected:
            plan["windows"].append(_run_window(session, runner, base_spec.config, window, baseline))

    plan["baseline_vs_oos"] = [
        _baseline_vs_oos(baseline, window)
        for window in plan["windows"]
        if window.get("status") == "success"
    ]
    plan["overall_status"] = _overall_status(plan["windows"])
    plan["ok"] = plan["overall_status"] in {"passed", "partial"}

    _write_outputs(output_dir, plan, args.format)
    _write_gpt_review_package(output_dir, plan)
    return 0 if plan["overall_status"] in {"passed", "partial"} else 1


def _select_windows(windows: list[dict[str, Any]], ids: list[str] | None) -> list[dict[str, Any]]:
    if not ids:
        return windows
    allowed = set(ids)
    return [w for w in windows if w.get("id") in allowed]


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return _ensure_utc(parsed)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _load_baseline_summary(session: Any, report_id: int) -> dict[str, Any]:
    report = session.get(BacktestReportModel, report_id)
    if report is None:
        return {"report_id": report_id, "status": "missing"}
    quality = report.quality_status
    quality_status = quality.get("status") if isinstance(quality, dict) else str(quality or "")
    return {
        "report_id": report.id,
        "task_no": report.task_no,
        "strategy_code": report.strategy_code,
        "strategy_version": report.strategy_version,
        "period": report.period,
        "data_source": report.data_source,
        "data_role": report.data_role,
        "data_version": report.data_version,
        "quality_status": quality_status or "passed",
        "start": (report.summary or {}).get("start"),
        "end": (report.summary or {}).get("end"),
        "trade_count": report.trade_count,
        "order_count": len(report.order_rows),
        "total_return": report.total_return,
        "total_return_pct": report.total_return * 100 if report.total_return is not None else None,
        "max_drawdown_pct": report.max_drawdown_pct,
        "max_drawdown_amount": report.max_drawdown_amount,
        "win_rate": report.win_rate,
        "profit_loss_ratio": report.profit_loss_ratio,
        "max_consecutive_losses": report.max_consecutive_losses,
        "total_commission": report.total_commission,
        "total_slippage": report.total_slippage,
        "initial_capital": report.initial_capital,
        "final_equity": report.final_equity,
        "lineage_summary": (report.summary or {}).get("lineage_summary"),
        "trust_audit_note": "Stage 13-G passed; baseline is reference only, not rewritten.",
    }


def _run_window(
    session: Any,
    runner: VnpyBacktestRunner,
    base_config: BacktestTaskConfig,
    window: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    window_id = str(window.get("id"))
    start = _parse_dt(str(window["start"]))
    end = _parse_dt(str(window["end"]))
    if start >= end:
        return {"window_id": window_id, "status": "failed", "error": "invalid window: start >= end"}

    config = base_config.model_copy(
        update={
            "start": start,
            "end": end,
            "request_payload": {
                **dict(base_config.request_payload),
                "oos_window": window,
                "baseline_report_id": baseline.get("report_id"),
            },
        }
    )
    request = GuiyiBacktestRequest(
        symbol=config.symbol,
        exchange=config.exchange,
        interval=config.interval,
        start=config.start,
        end=config.end,
        rate=config.rate,
        slippage=config.slippage,
        size=config.size,
        pricetick=config.pricetick,
        capital=config.capital,
        strategy_class_path=config.strategy_class_path,
        strategy_parameters=dict(config.strategy_parameters),
        bar_data_path=config.bar_data_path,
        auxiliary_bar_data_paths=dict(config.auxiliary_bar_data_paths),
        execution_timing=config.execution_timing,
    )
    try:
        raw = runner.run(request)
        normalized = convert_vnpy_result(raw)
        if should_enrich_jm_v1b_result(config):
            normalized = enrich_jm_v1b_result(session, config, normalized)
        trades = normalized.get("trades") or []
        orders = normalized.get("orders") or []
        metrics = _full_metrics(normalized, config)
        summary = _summarize(metrics, trades, orders, normalized, config)
        trust_checks = _run_memory_trust_checks(normalized, config, metrics)
        return _sanitize_window_result(
            {
                "window_id": window_id,
                "label": window.get("label"),
                "purpose": window.get("purpose"),
                "train_window": window.get("train_window"),
                "start": start.isoformat(),
                "end": end.isoformat(),
                "status": "success",
                "summary": summary,
                "lineage_summary": normalized.get("lineage_summary"),
                "trust_checks": trust_checks,
                "data_version": config.data_version,
                "quality_status": config.quality_status,
                "execution_timing": config.execution_timing,
                "frozen_costs": {
                    "rate": config.rate,
                    "slippage": config.slippage,
                    "size": config.size,
                    "pricetick": config.pricetick,
                    "capital": config.capital,
                },
                "baseline_comparison": _baseline_vs_oos(
                    baseline,
                    {
                        "summary": summary,
                        "window_id": window_id,
                        "data_version": config.data_version,
                        "quality_status": config.quality_status,
                    },
                ),
            }
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        return {
            "window_id": window_id,
            "label": window.get("label"),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "preserved": True,
        }


def _full_metrics(normalized: dict[str, Any], config: BacktestTaskConfig) -> dict[str, Any]:
    trades = normalized.get("trades") or []
    equity_curve = normalized.get("equity_curve") or []
    drawdown_curve = normalized.get("drawdown_curve") or []
    summary = normalized.get("summary") or normalized.get("report") or {}
    return compute_report_metrics(
        summary=summary,
        trades=trades,
        equity_curve=equity_curve,
        drawdown_curve=drawdown_curve,
        start=_ensure_utc(config.start),
        end=_ensure_utc(config.end),
        default_initial_capital=config.capital,
    )


def _summarize(
    metrics: dict[str, Any],
    trades: list[Any],
    orders: list[Any],
    normalized: dict[str, Any],
    config: BacktestTaskConfig,
) -> dict[str, Any]:
    total_return = metrics.get("total_return")
    largest_loss = _largest_loss_trade(trades)
    return {
        "trade_count": len(trades),
        "order_count": len(orders),
        "total_return": total_return,
        "total_return_pct": total_return * 100 if total_return is not None else None,
        "annual_return": metrics.get("annual_return"),
        "max_drawdown": metrics.get("max_drawdown_pct") or metrics.get("max_drawdown"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct") or metrics.get("max_drawdown"),
        "max_drawdown_amount": metrics.get("max_drawdown_amount"),
        "max_consecutive_losses": metrics.get("max_consecutive_losses"),
        "win_rate": metrics.get("win_rate"),
        "profit_factor": _profit_factor(trades),
        "profit_loss_ratio": metrics.get("profit_loss_ratio"),
        "expectancy": metrics.get("expectancy"),
        "total_fee": metrics.get("total_commission"),
        "total_commission": metrics.get("total_commission"),
        "total_slippage": metrics.get("total_slippage"),
        "total_net_pnl": metrics.get("total_net_pnl"),
        "initial_capital": metrics.get("initial_capital") or config.capital,
        "final_equity": metrics.get("final_equity"),
        "equity_curve_points": len(normalized.get("equity_curve") or []),
        "drawdown_curve_points": len(normalized.get("drawdown_curve") or []),
        "largest_loss_trade": largest_loss,
        "contract_multiplier_check": _contract_multiplier_check(trades, expected=config.size),
        "price_tick_check": _price_tick_check(trades, expected=config.pricetick),
        "rollover_exit_count": metrics.get("rollover_exit_count"),
        "delivery_risk_exit_count": metrics.get("delivery_risk_exit_count"),
    }


def _profit_factor(trades: list[dict[str, Any]]) -> float | None:
    wins = sum(float(trade.get("net_pnl") or 0) for trade in trades if float(trade.get("net_pnl") or 0) > 0)
    losses = abs(sum(float(trade.get("net_pnl") or 0) for trade in trades if float(trade.get("net_pnl") or 0) < 0))
    if losses <= 0:
        return None
    if wins <= 0:
        return 0.0
    return wins / losses


def _largest_loss_trade(trades: list[dict[str, Any]]) -> dict[str, Any] | None:
    losses = [trade for trade in trades if float(trade.get("net_pnl") or 0) < 0]
    if not losses:
        return None
    worst = min(losses, key=lambda trade: float(trade.get("net_pnl") or 0))
    return {
        "trade_id": worst.get("trade_id") or worst.get("tradeid"),
        "net_pnl": float(worst.get("net_pnl") or 0),
        "contract": worst.get("contract") or worst.get("contract_code"),
        "entry_time": worst.get("entry_time") or worst.get("open_time"),
        "exit_time": worst.get("exit_time") or worst.get("close_time"),
    }


def _contract_multiplier_check(trades: list[dict[str, Any]], *, expected: float) -> dict[str, Any]:
    values = {int(trade.get("contract_multiplier") or trade.get("size") or 0) for trade in trades if trades}
    invalid = [value for value in values if value <= 0]
    mismatched = [value for value in values if value and not isclose(value, expected, rel_tol=0, abs_tol=0)]
    return {
        "expected": expected,
        "observed": sorted(values),
        "passed": not invalid and not mismatched,
    }


def _price_tick_check(trades: list[dict[str, Any]], *, expected: float) -> dict[str, Any]:
    values = {float(trade.get("price_tick") or trade.get("pricetick") or 0) for trade in trades if trades}
    invalid = [value for value in values if value <= 0]
    mismatched = [value for value in values if value and not isclose(value, expected, rel_tol=0, abs_tol=1e-9)]
    return {
        "expected": expected,
        "observed": sorted(values),
        "passed": not invalid and not mismatched,
    }


def _run_memory_trust_checks(
    normalized: dict[str, Any],
    config: BacktestTaskConfig,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    trades = normalized.get("trades") or []
    orders = normalized.get("orders") or []
    checks: dict[str, Any] = {}

    trade_count_status = "passed" if metrics.get("trade_count") == len(trades) else "failed"
    checks["trade_count_consistency"] = {
        "status": trade_count_status,
        "summary_trade_count": metrics.get("trade_count"),
        "trade_rows": len(trades),
    }

    equity_status = "passed"
    equity_details: dict[str, Any] = {}
    try:
        equity_curve = generate_equity_curve(trades, initial_capital=config.capital)
        recomputed_final = equity_curve[-1]["equity"] if equity_curve else config.capital
        if not _near(recomputed_final, metrics.get("final_equity")):
            equity_status = "failed"
        drawdown_curve = normalized.get("drawdown_curve") or []
        if drawdown_curve:
            recomputed_max_dd_pct = max(abs(float(point.get("drawdown_pct") or 0)) for point in drawdown_curve)
        else:
            drawdown_result = generate_drawdown_curve(equity_curve)
            recomputed_max_dd_pct = drawdown_result["max_drawdown_pct"]
        if not _near(recomputed_max_dd_pct, metrics.get("max_drawdown_pct"), tolerance=1e-4):
            equity_status = "failed"
        equity_details = {
            "recomputed_final_equity": recomputed_final,
            "recomputed_max_drawdown_pct": recomputed_max_dd_pct,
            "equity_curve_points": len(equity_curve),
            "drawdown_curve_points": len(drawdown_curve) or len(normalized.get("drawdown_curve") or []),
        }
    except ValueError as exc:
        equity_status = "failed"
        equity_details = {"error": str(exc)}
    checks["equity_consistency"] = {"status": equity_status, **equity_details}

    fee_status = "passed"
    total_commission = sum(float(trade.get("commission") or 0) for trade in trades)
    total_slippage = sum(float(trade.get("slippage") or 0) for trade in trades)
    if trades and total_commission == 0:
        fee_status = "warning"
    if trades and total_slippage == 0:
        fee_status = "warning"
    if not _near(total_commission, metrics.get("total_commission")):
        fee_status = "failed"
    if not _near(total_slippage, metrics.get("total_slippage")):
        fee_status = "failed"
    checks["fee_slippage"] = {
        "status": fee_status,
        "total_commission": total_commission,
        "total_slippage": total_slippage,
        "rate": config.rate,
        "slippage_setting": config.slippage,
    }

    execution_status = "passed"
    execution_issues: list[str] = []
    for trade in trades:
        signal_time = trade.get("entry_signal_time")
        fill_time = trade.get("entry_time") or trade.get("open_time")
        if signal_time and fill_time:
            signal_dt = _normalize_optional_dt(signal_time)
            fill_dt = _normalize_optional_dt(fill_time)
            if signal_dt and fill_dt and fill_dt <= signal_dt:
                execution_status = "failed"
                execution_issues.append(f"{trade.get('trade_id')}: fill not after signal")
    checks["execution_policy"] = {
        "status": execution_status,
        "execution_timing": config.execution_timing,
        "issues": execution_issues,
    }

    lineage = normalized.get("lineage_summary") or {}
    lineage_status = "passed"
    if trades and lineage:
        if lineage.get("missing_trades") or lineage.get("ambiguous_trades"):
            lineage_status = "warning"
        if lineage.get("unmapped_orders"):
            lineage_status = "warning"
    checks["lineage_mapping"] = {
        "status": lineage_status,
        "lineage_summary": lineage,
        "order_count": len(orders),
    }

    multiplier_check = _contract_multiplier_check(trades, expected=config.size)
    tick_check = _price_tick_check(trades, expected=config.pricetick)
    cost_status = "passed" if multiplier_check["passed"] and tick_check["passed"] else "warning"
    if trades and (not multiplier_check["passed"] or not tick_check["passed"]):
        cost_status = "failed"
    checks["contract_multiplier"] = {
        "status": cost_status,
        "multiplier_check": multiplier_check,
        "price_tick_check": tick_check,
    }

    statuses = [check["status"] for check in checks.values()]
    overall = "passed"
    if any(status == "failed" for status in statuses):
        overall = "failed"
    elif any(status == "warning" for status in statuses):
        overall = "warning"
    return {"audit_status": overall, "checks": checks}


def _baseline_vs_oos(baseline: dict[str, Any], window: dict[str, Any]) -> dict[str, Any]:
    summary = window.get("summary") or {}
    return {
        "window_id": window.get("window_id"),
        "baseline_report_id": baseline.get("report_id"),
        "baseline_trade_count": baseline.get("trade_count"),
        "window_trade_count": summary.get("trade_count"),
        "baseline_total_return_pct": baseline.get("total_return_pct"),
        "window_total_return_pct": summary.get("total_return_pct"),
        "delta_total_return_pct": _delta(summary.get("total_return_pct"), baseline.get("total_return_pct")),
        "baseline_max_drawdown_pct": baseline.get("max_drawdown_pct"),
        "window_max_drawdown_pct": summary.get("max_drawdown_pct"),
        "baseline_win_rate": baseline.get("win_rate"),
        "window_win_rate": summary.get("win_rate"),
        "baseline_total_commission": baseline.get("total_commission"),
        "window_total_commission": summary.get("total_commission"),
        "baseline_total_slippage": baseline.get("total_slippage"),
        "window_total_slippage": summary.get("total_slippage"),
        "baseline_data_version": baseline.get("data_version"),
        "window_data_version": window.get("data_version"),
        "baseline_quality_status": baseline.get("quality_status"),
        "window_quality_status": window.get("quality_status"),
        "interpretation_note": (
            "Differences reflect window slicing and market regime only; "
            "frozen parameters and strategy logic were not changed."
        ),
    }


def _delta(current: Any, baseline: Any) -> float | None:
    if current is None or baseline is None:
        return None
    return float(current) - float(baseline)


def _overall_status(windows: list[dict[str, Any]]) -> str:
    statuses = [window.get("status") for window in windows]
    if all(status == "success" for status in statuses):
        trust_statuses = [
            (window.get("trust_checks") or {}).get("audit_status")
            for window in windows
            if window.get("status") == "success"
        ]
        if any(status == "failed" for status in trust_statuses):
            return "partial"
        if any(status == "warning" for status in trust_statuses):
            return "partial"
        return "passed"
    if any(status == "success" for status in statuses):
        return "partial"
    return "failed"


def _near(left: Any, right: Any, *, tolerance: float = 1e-6) -> bool:
    if left is None or right is None:
        return left == right
    return isclose(float(left), float(right), rel_tol=0, abs_tol=tolerance)


def _normalize_optional_dt(value: Any) -> datetime | None:
    parsed = _parse_optional_dt(value)
    if parsed is None:
        return None
    return _ensure_utc(parsed)


def _parse_optional_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _sanitize_window_result(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False, default=str)
    if any(marker.lower() in encoded.lower() for marker in SENSITIVE_MARKERS):
        return json.loads(_redact_sensitive(encoded))
    return payload


def _redact_sensitive(text: str) -> str:
    redacted = re.sub(r"/Users/[^\"\\s]+", "<redacted_path>", text)
    redacted = re.sub(r"/Volumes/[^\"\\s]+", "<redacted_path>", redacted)
    return redacted


def _write_outputs(output_dir: Path, plan: dict[str, Any], fmt: str) -> None:
    json_path = output_dir / "oos_validation.json"
    json_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if fmt == "markdown":
        md_path = output_dir / "oos_validation.md"
        md_path.write_text(_render_markdown(plan), encoding="utf-8")
        print(md_path.read_text(encoding="utf-8"), end="")
    else:
        print(json.dumps(plan, ensure_ascii=False, indent=2, default=str))


def _render_markdown(plan: dict[str, Any]) -> str:
    lines = [
        "# JM V1B OOS Validation (frozen config)",
        "",
        f"- baseline_report_id: {plan.get('baseline_report_id')}",
        f"- readonly: {plan.get('readonly')}",
        f"- persist_to_db: {plan.get('persist_to_db')}",
        f"- overall_status: {plan.get('overall_status', 'plan_only')}",
        "",
        "## Windows",
    ]
    for window in plan.get("windows") or []:
        lines.append(f"### {window.get('window_id')}")
        for key in (
            "label",
            "start",
            "end",
            "status",
            "summary",
            "trust_checks",
            "baseline_comparison",
            "error",
        ):
            if key in window:
                lines.append(f"- {key}: {window[key]}")
        lines.append("")
    if plan.get("baseline_vs_oos"):
        lines.extend(["", "## Baseline vs OOS"])
        for row in plan["baseline_vs_oos"]:
            lines.append(f"- {row}")
    return "\n".join(lines)


def _write_gpt_review_package(output_dir: Path, plan: dict[str, Any]) -> None:
    lines = [
        "# GPT Review Package: JM V1B OOS Full Window",
        "",
        "## Frozen Config",
        f"- baseline_report_id: {plan.get('baseline_report_id')}",
        f"- strategy: {plan.get('frozen_strategy')}",
        f"- data_policy: {plan.get('frozen_data_policy')}",
        f"- costs: {plan.get('frozen_costs')}",
        f"- persist_to_db: {plan.get('persist_to_db')}",
        "",
        "## Execution Commands",
        "```bash",
        "PYTHONPATH=services/quant-api:packages/quant-core \\",
        "uv run --project services/quant-api python scripts/backtest_trust_audit.py \\",
        f"  --report-id {plan.get('baseline_report_id')} --format markdown",
        "",
        "PYTHONPATH=services/quant-api:packages/quant-core \\",
        "uv run --project services/quant-api python scripts/oos_validation_run.py \\",
        "  --run --format markdown --output-dir <output_dir>",
        "```",
        "",
        "## Overall Status",
        f"- overall_status: {plan.get('overall_status')}",
        f"- readonly: {plan.get('readonly')}",
        f"- would_write_db: {plan.get('would_write_db')}",
        "",
        "## Window Results",
    ]
    for window in plan.get("windows") or []:
        lines.append(f"### {window.get('window_id')} ({window.get('status')})")
        summary = window.get("summary") or {}
        if summary:
            lines.append(
                "- metrics: "
                f"trades={summary.get('trade_count')}, "
                f"return_pct={summary.get('total_return_pct')}, "
                f"mdd_pct={summary.get('max_drawdown_pct')}, "
                f"win_rate={summary.get('win_rate')}, "
                f"profit_factor={summary.get('profit_factor')}"
            )
        trust = window.get("trust_checks") or {}
        if trust:
            lines.append(f"- trust_audit_status: {trust.get('audit_status')}")
        if window.get("error"):
            lines.append(f"- error: {window.get('error')}")
        lines.append("")

    lines.extend(["## Baseline vs OOS", ""])
    for row in plan.get("baseline_vs_oos") or []:
        lines.append(f"- {row.get('window_id')}: delta_return_pct={row.get('delta_total_return_pct')}")

    lines.extend(
        [
            "",
            "## Risks and Boundaries",
            "- Trust passed on report 14 does not imply strategy profitability or live readiness.",
            "- OOS losses and drawdown expansion must be preserved; no parameter tuning was applied.",
            "- OOS runs do not write formal backtest reports to PostgreSQL.",
            "- Walk-forward windows are test-only slices; train windows are metadata only in this CLI.",
            "",
            "## Review Questions for External GPT",
            "1. Are trade/order/equity/fee checks sufficient for non-DB OOS evidence?",
            "2. Do OOS deteriorations look like regime shift rather than implementation drift?",
            "3. Should any window be blocked from further research despite frozen parameters?",
        ]
    )
    (output_dir / "GPT_REVIEW_PACKAGE.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
