#!/usr/bin/env python3
"""Frozen-window OOS validation runner for JM V1B report 14 baseline.

Read-only by default: does not write to backtest_tasks / backtest_reports.

Outputs JSON/Markdown under data/reports/oos_validation_<timestamp>/.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "oos" / "jm_v1b_report14_frozen.json"


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

    if args.run:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "BACKTEST_LEGACY_OOS_EXECUTION_DISABLED",
                    "message": (
                        "Profile/file OOS execution is disabled pending canonical "
                        "MarketDataService cutover"
                    ),
                },
                ensure_ascii=False,
            )
        )
        return 2

    output_dir = args.output_dir or (
        PROJECT_ROOT
        / "data"
        / "reports"
        / f"oos_validation_{datetime.now(UTC):%Y%m%d_%H%M%S}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    plan: dict[str, Any] = {
        "ok": True,
        "readonly": not args.run,
        "persist_to_db": False,
        "baseline_report_id": config_payload.get("baseline_report_id"),
        "frozen_strategy": config_payload.get("frozen_strategy"),
        "config_path": str(args.config),
        "windows": [],
    }

    for window in selected:
        plan["windows"].append({"window_id": window.get("id"), "window": window, "status": "plan_only"})
    _write_outputs(output_dir, plan, args.format)
    return 0



def _select_windows(windows: list[dict[str, Any]], ids: list[str] | None) -> list[dict[str, Any]]:
    if not ids:
        return windows
    allowed = set(ids)
    return [w for w in windows if w.get("id") in allowed]


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _run_window(
    session: Any,
    runner: Any,
    base_config: Any,
    window: dict[str, Any],
) -> dict[str, Any]:
    del session, runner, base_config
    window_id = str(window.get("id"))
    start = _parse_dt(str(window["start"]))
    end = _parse_dt(str(window["end"]))
    if start >= end:
        return {"window_id": window_id, "status": "failed", "error": "invalid window: start >= end"}
    return {
        "window_id": window_id,
        "status": "failed",
        "error": "BACKTEST_LEGACY_OOS_EXECUTION_DISABLED",
    }


def _summarize(metrics: dict[str, Any], trades: list[Any]) -> dict[str, Any]:
    return {
        "trade_count": len(trades),
        "total_return": metrics.get("total_return") or metrics.get("total_return_pct"),
        "total_return_pct": metrics.get("total_return_pct"),
        "max_drawdown": metrics.get("max_drawdown") or metrics.get("max_drawdown_pct"),
        "max_consecutive_losses": metrics.get("max_consecutive_losses"),
        "win_rate": metrics.get("win_rate"),
        "profit_factor": metrics.get("profit_factor"),
        "total_fee": metrics.get("total_fee") or metrics.get("total_commission"),
        "total_slippage": metrics.get("total_slippage"),
        "total_net_pnl": metrics.get("total_net_pnl"),
    }


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
        "",
        "## Windows",
    ]
    for window in plan.get("windows") or []:
        lines.append(f"### {window.get('window_id')}")
        for key in ("label", "start", "end", "status", "summary", "error"):
            if key in window:
                lines.append(f"- {key}: {window[key]}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
