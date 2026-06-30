from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import select


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.backtest import BacktestOrderModel, BacktestReportModel, BacktestTask, BacktestTradeModel  # noqa: E402

from export_su_bing_report_10_review_package import (  # noqa: E402
    build_trusted_exclusion_summary,
    is_untrusted_cross_contract_trade,
    order_to_dict,
    report_to_dict,
    task_to_dict,
    trade_level_metrics,
    trade_to_dict,
    write_csv,
)


STRATEGY_CODE = "su_bing_jm_daily_ema21_macd_volume"
STRATEGY_VERSION = "v0.3.0-daily-score2of4"
SPEC_DIR = PROJECT_ROOT / "docs" / "strategy_specs" / STRATEGY_CODE
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "backtests" / "reports" / "su_bing_daily_score2of4"

TRADE_FIELDS = [
    "trade_id",
    "direction",
    "entry_signal_time",
    "open_time",
    "open_price",
    "exit_signal_time",
    "close_time",
    "close_price",
    "entry_contract",
    "exit_contract",
    "is_cross_contract",
    "net_pnl",
    "gross_pnl",
    "commission",
    "slippage",
    "holding_bars",
    "entry_score",
    "entry_grade",
    "long_score",
    "short_score",
    "satisfied_conditions",
    "failed_conditions",
    "scene_tags",
    "skill_notes",
    "entry_reason",
    "exit_reason",
    "pnl_trust_status",
]
SUMMARY_FIELDS = [
    "report_id",
    "strategy_code",
    "strategy_version",
    "metric_scope",
    "raw_trade_count",
    "trusted_trade_count",
    "excluded_trade_count",
    "raw_net_pnl",
    "trusted_net_pnl",
    "raw_win_rate",
    "trusted_win_rate",
    "raw_profit_loss_ratio",
    "trusted_profit_loss_ratio",
    "raw_max_drawdown",
    "trusted_max_drawdown",
    "raw_max_consecutive_losses",
    "trusted_max_consecutive_losses",
    "cross_contract_trades",
    "excluded_trade_ids",
    "conclusion",
]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR
    with SessionLocal() as session:
        package = load_report_package(session, args.report_id)
        baseline = load_optional_report_package(session, args.baseline_report_id)
    export_package(package, output_dir=output_dir, baseline=baseline)
    print(json.dumps({"report_id": args.report_id, "output_dir": str(output_dir)}, ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Su Bing daily score2of4 review package.")
    parser.add_argument("--report-id", type=int, required=True)
    parser.add_argument("--baseline-report-id", type=int, default=10)
    parser.add_argument("--output-dir", type=str, default="")
    return parser.parse_args(argv)


def load_report_package(session, report_id: int) -> dict[str, Any]:
    report = session.get(BacktestReportModel, report_id)
    if report is None:
        raise SystemExit(f"report_id={report_id} does not exist")
    if report.strategy_code != STRATEGY_CODE or report.strategy_version != STRATEGY_VERSION:
        raise SystemExit(f"report_id={report_id} is not {STRATEGY_CODE}/{STRATEGY_VERSION}")
    task = session.get(BacktestTask, report.task_id)
    if task is None:
        raise SystemExit(f"task_id={report.task_id} does not exist")
    return _package_from_report(session, report, task)


def load_optional_report_package(session, report_id: int | None) -> dict[str, Any] | None:
    if not report_id:
        return None
    report = session.get(BacktestReportModel, report_id)
    if report is None:
        return None
    task = session.get(BacktestTask, report.task_id)
    if task is None:
        return None
    return _package_from_report(session, report, task)


def _package_from_report(session, report: BacktestReportModel, task: BacktestTask) -> dict[str, Any]:
    trades = [
        score2of4_trade_row(trade_to_dict(row))
        for row in session.scalars(
            select(BacktestTradeModel).where(BacktestTradeModel.report_id == report.id).order_by(BacktestTradeModel.sequence)
        )
    ]
    orders = [
        order_to_dict(row)
        for row in session.scalars(select(BacktestOrderModel).where(BacktestOrderModel.report_id == report.id).order_by(BacktestOrderModel.id))
    ]
    normalized = (task.result_payload or {}).get("normalized_result") or {}
    return {
        "report": report_to_dict(report),
        "task": task_to_dict(task),
        "trades": trades,
        "orders": orders,
        "execution_events": [dict(item) for item in normalized.get("strategy_execution_events") or []],
        "signal_candidates": [dict(item) for item in normalized.get("signal_candidates") or []],
        "rejected_signals": [dict(item) for item in normalized.get("rejected_signals") or []],
        "summary": dict(report.summary or {}),
    }


def export_package(package: dict[str, Any], *, output_dir: Path, baseline: dict[str, Any] | None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    SPEC_DIR.mkdir(parents=True, exist_ok=True)

    trades = package["trades"]
    candidates = package["signal_candidates"]
    trusted_summary = build_trusted_exclusion_summary(
        trades,
        report_id=int(package["report"]["id"]),
        strategy_code=str(package["report"]["strategy_code"]),
        strategy_version=str(package["report"]["strategy_version"]),
    )
    trusted_summary["conclusion"] = (
        "V0.3 score2of4 trusted metrics exclude cross-contract PnL; raw metrics are shown for audit only."
    )
    score_summary = build_score_distribution_summary(trades, candidates)
    scene_summary = build_scene_tag_summary(trades)

    write_csv(output_dir / "v0_3_score2of4_trades.csv", trades, TRADE_FIELDS)
    write_csv(output_dir / "v0_3_score2of4_orders.csv", package["orders"], sorted_fields(package["orders"]))
    write_csv(output_dir / "v0_3_score2of4_execution_events.csv", package["execution_events"], sorted_fields(package["execution_events"]))
    write_csv(output_dir / "v0_3_score2of4_signal_candidates.csv", candidates, sorted_fields(candidates))
    write_csv(output_dir / "v0_3_score2of4_rejected_signals.csv", package["rejected_signals"], sorted_fields(package["rejected_signals"]))
    write_csv(output_dir / "v0_3_score2of4_trusted_excluding_cross_contract.csv", [trusted_summary], SUMMARY_FIELDS)
    (output_dir / "v0_3_score2of4_summary.json").write_text(json.dumps(package["summary"], ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (output_dir / "v0_3_score2of4_signal_funnel.md").write_text(build_signal_funnel_markdown(candidates, package["rejected_signals"]), encoding="utf-8")
    (output_dir / "v0_3_score2of4_score_distribution.md").write_text(build_score_distribution_markdown(score_summary), encoding="utf-8")
    (output_dir / "v0_3_score2of4_trade_review.md").write_text(build_trade_review_markdown(package, trusted_summary, score_summary, scene_summary), encoding="utf-8")
    (output_dir / "v0_3_score2of4_trusted_excluding_cross_contract.md").write_text(build_trusted_markdown(trusted_summary, trades), encoding="utf-8")
    (output_dir / "v0_2_vs_v0_3_score2of4_comparison.md").write_text(build_comparison_markdown(package, baseline, trusted_summary), encoding="utf-8")

    review = build_backtest_review_markdown(package, trusted_summary, score_summary, scene_summary, baseline)
    handoff = build_handoff_markdown(package, trusted_summary, score_summary, scene_summary, baseline)
    (SPEC_DIR / "V0_3_SCORE2OF4_BACKTEST_REVIEW.md").write_text(review, encoding="utf-8")
    (SPEC_DIR / "V0_3_SCORE2OF4_HANDOFF_FOR_CHATGPT.md").write_text(handoff, encoding="utf-8")


def score2of4_trade_row(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("raw_payload") if isinstance(row.get("raw_payload"), dict) else {}
    out = dict(row)
    out["trade_id"] = row.get("trade_no") or row.get("trade_id")
    out["is_cross_contract"] = bool(row.get("entry_contract") and row.get("exit_contract") and row.get("entry_contract") != row.get("exit_contract"))
    out["entry_score"] = _int_value(row.get("entry_score", raw.get("entry_score")))
    out["entry_grade"] = row.get("entry_grade") or raw.get("entry_grade") or ""
    out["long_score"] = _int_value(row.get("long_score", raw.get("long_score")))
    out["short_score"] = _int_value(row.get("short_score", raw.get("short_score")))
    out["satisfied_conditions"] = _list_value(row.get("satisfied_conditions", raw.get("satisfied_conditions")))
    out["failed_conditions"] = _list_value(row.get("failed_conditions", raw.get("failed_conditions")))
    out["scene_tags"] = _list_value(row.get("scene_tags", raw.get("scene_tags")))
    out["skill_notes"] = _list_value(row.get("skill_notes", raw.get("skill_notes")))
    out["pnl_trust_status"] = "cross_contract_needs_review" if out["is_cross_contract"] else "traceable_same_contract"
    return out


def build_score_distribution_summary(trades: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_score_counts: Counter[int] = Counter()
    condition_combo_counts: Counter[str] = Counter()
    for row in candidates:
        score = _entry_score(row)
        if score:
            candidate_score_counts[score] += 1
            combo = _condition_combo(row)
            if combo:
                condition_combo_counts[combo] += 1

    trade_score_stats: dict[int, dict[str, Any]] = {}
    for score in (2, 3, 4):
        score_rows = [row for row in trades if _entry_score(row) == score]
        trusted_rows = [row for row in score_rows if not is_untrusted_cross_contract_trade(row)]
        raw_metrics = trade_level_metrics(score_rows, initial_capital=100000.0)
        trusted_metrics = trade_level_metrics(trusted_rows, initial_capital=100000.0)
        trade_score_stats[score] = {
            "trade_count": raw_metrics["trade_count"],
            "trusted_trade_count": trusted_metrics["trade_count"],
            "net_pnl": raw_metrics["net_pnl"],
            "trusted_net_pnl": trusted_metrics["net_pnl"],
            "win_rate": raw_metrics["win_rate"],
            "trusted_win_rate": trusted_metrics["win_rate"],
        }
    return {
        "candidate_score_counts": dict(candidate_score_counts),
        "condition_combo_counts": dict(condition_combo_counts),
        "trade_score_stats": trade_score_stats,
    }


def build_score_distribution_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# V0.3 Score Distribution",
        "",
        "| score | signal_count | trade_count | trusted_net_pnl |",
        "|---|---:|---:|---:|",
    ]
    candidate_counts = summary.get("candidate_score_counts", {})
    trade_stats = summary.get("trade_score_stats", {})
    for score in (2, 3, 4):
        stats = trade_stats.get(score, {})
        lines.append(
            f"| score={score} | {candidate_counts.get(score, 0)} | {stats.get('trade_count', 0)} | {stats.get('trusted_net_pnl', 0.0)} |"
        )
    lines.extend(["", "## Condition Combos", "", "| combo | count |", "|---|---:|"])
    for combo, count in sorted(summary.get("condition_combo_counts", {}).items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {combo} | {count} |")
    lines.append("")
    return "\n".join(lines)


def build_scene_tag_summary(trades: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in trades:
        for tag in _list_value(row.get("scene_tags")):
            grouped[tag].append(row)
    summary: dict[str, dict[str, Any]] = {}
    for tag, rows in grouped.items():
        trusted_rows = [row for row in rows if not is_untrusted_cross_contract_trade(row)]
        pnls = [_float_value(row.get("net_pnl")) for row in rows]
        trusted_pnls = [_float_value(row.get("net_pnl")) for row in trusted_rows]
        summary[tag] = {
            "trade_count": len(rows),
            "trusted_trade_count": len(trusted_rows),
            "net_pnl": round(sum(pnls), 10),
            "trusted_net_pnl": round(sum(trusted_pnls), 10),
            "win_rate": round(sum(1 for value in pnls if value > 0) / len(rows), 10) if rows else 0.0,
            "average_pnl": round(sum(pnls) / len(rows), 10) if rows else 0.0,
            "max_loss": min(pnls) if pnls else 0.0,
            "suggested_action": _scene_suggested_action(tag),
        }
    return summary


def build_signal_funnel_markdown(candidates: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> str:
    accepted = [row for row in candidates if str(row.get("final_signal") or "") in {"long", "short"}]
    rejected_counts = Counter(str(row.get("rejected_reason") or row.get("reject_reason") or "") for row in rejected)
    lines = [
        "# V0.3 Score2Of4 Signal Funnel",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| signal_candidates | {len(candidates)} |",
        f"| accepted_signals | {len(accepted)} |",
        f"| rejected_signals | {len(rejected)} |",
    ]
    for reason, count in sorted(rejected_counts.items()):
        if reason:
            lines.append(f"| rejected reason: {reason} | {count} |")
    lines.append("")
    return "\n".join(lines)


def build_trade_review_markdown(
    package: dict[str, Any],
    trusted_summary: dict[str, Any],
    score_summary: dict[str, Any],
    scene_summary: dict[str, Any],
) -> str:
    lines = [
        "# V0.3 Score2Of4 Trade Review",
        "",
        f"- report_id: `{package['report']['id']}`",
        f"- strategy: `{package['report']['strategy_code']} / {package['report']['strategy_version']}`",
        f"- raw_trade_count: `{trusted_summary['raw_trade_count']}`",
        f"- trusted_trade_count: `{trusted_summary['trusted_trade_count']}`",
        f"- trusted_net_pnl: `{trusted_summary['trusted_net_pnl']}`",
        "",
        "## Score Distribution",
        "",
        build_score_distribution_markdown(score_summary),
        "",
        "## Scene Tags",
        "",
        json.dumps(scene_summary, ensure_ascii=False, indent=2),
        "",
    ]
    return "\n".join(lines)


def build_trusted_markdown(summary: dict[str, Any], trades: list[dict[str, Any]]) -> str:
    excluded = [row for row in trades if is_untrusted_cross_contract_trade(row)]
    lines = [
        "# V0.3 Trusted Excluding Cross Contract",
        "",
        f"- metric_scope: `{summary['metric_scope']}`",
        f"- raw_trade_count: `{summary['raw_trade_count']}`",
        f"- trusted_trade_count: `{summary['trusted_trade_count']}`",
        f"- excluded_trade_count: `{summary['excluded_trade_count']}`",
        f"- trusted_net_pnl: `{summary['trusted_net_pnl']}`",
        "",
        "| trade_id | entry_contract | exit_contract | net_pnl |",
        "|---|---|---|---:|",
    ]
    for row in excluded:
        lines.append(f"| {row.get('trade_id')} | {row.get('entry_contract')} | {row.get('exit_contract')} | {row.get('net_pnl')} |")
    lines.append("")
    return "\n".join(lines)


def build_comparison_markdown(package: dict[str, Any], baseline: dict[str, Any] | None, trusted_summary: dict[str, Any]) -> str:
    lines = ["# V0.2 vs V0.3 Score2Of4 Comparison", ""]
    if baseline is None:
        lines.append("No baseline report package was available for comparison.")
        return "\n".join(lines)
    baseline_metrics = trade_level_metrics(baseline["trades"], initial_capital=100000.0)
    lines.extend(
        [
            "| metric | v0.2 baseline | v0.3 score2of4 trusted |",
            "|---|---:|---:|",
            f"| trade_count | {baseline_metrics['trade_count']} | {trusted_summary['trusted_trade_count']} |",
            f"| net_pnl | {baseline_metrics['net_pnl']} | {trusted_summary['trusted_net_pnl']} |",
            f"| win_rate | {baseline_metrics['win_rate']} | {trusted_summary['trusted_win_rate']} |",
            f"| profit_loss_ratio | {baseline_metrics['profit_loss_ratio']} | {trusted_summary['trusted_profit_loss_ratio']} |",
            f"| max_consecutive_losses | {baseline_metrics['max_consecutive_losses']} | {trusted_summary['trusted_max_consecutive_losses']} |",
            "",
        ]
    )
    return "\n".join(lines)


def build_backtest_review_markdown(
    package: dict[str, Any],
    trusted_summary: dict[str, Any],
    score_summary: dict[str, Any],
    scene_summary: dict[str, Any],
    baseline: dict[str, Any] | None,
) -> str:
    report = package["report"]
    summary = package["summary"]
    lines = [
        "# V0_3_SCORE2OF4_BACKTEST_REVIEW",
        "",
        "## 1. 回测配置",
        "",
        f"- strategy_code: `{report['strategy_code']}`",
        f"- strategy_version: `{report['strategy_version']}`",
        f"- symbol: `{report['symbol']}`",
        f"- period: `{report['period']}`",
        f"- data_source: `{report['data_source']}`",
        f"- data_role: `{report['data_role']}`",
        "- rollover_mode: `no_forced_rollover_exit`",
        "- metric_scope: `raw_and_trusted_excluding_cross_contract`",
        "",
        "## 2. 核心指标",
        "",
        json.dumps(trusted_summary, ensure_ascii=False, indent=2),
        "",
        "## 3. v0.2.0 vs v0.3.0 对比",
        "",
        build_comparison_markdown(package, baseline, trusted_summary),
        "",
        "## 4. score 分布",
        "",
        build_score_distribution_markdown(score_summary),
        "",
        "## 5. Skill 标签复盘",
        "",
        json.dumps(scene_summary, ensure_ascii=False, indent=2),
        "",
        "## 6. 结论",
        "",
        "- 本文件只记录研究回测结论，不给实盘建议。",
        "- 可信收益结论只使用 excluding cross-contract metrics。",
        f"- raw summary fields: `{', '.join(sorted(str(key) for key in summary.keys())[:20])}`",
        "",
    ]
    return "\n".join(lines)


def build_handoff_markdown(
    package: dict[str, Any],
    trusted_summary: dict[str, Any],
    score_summary: dict[str, Any],
    scene_summary: dict[str, Any],
    baseline: dict[str, Any] | None,
) -> str:
    return "\n".join(
        [
            "# V0_3_SCORE2OF4_HANDOFF_FOR_CHATGPT",
            "",
            "## 本轮做了什么",
            "",
            "- 新增并回测 `v0.3.0-daily-score2of4`。",
            "- 保留 `v0.2.0-daily` 冻结基线。",
            "- 输出 raw 与 trusted excluding cross-contract 指标。",
            "",
            "## 规则摘要",
            "",
            "- 4 个条件任意 2 个满足，且必须有方向锚点。",
            "- 同分方向冲突拒绝。",
            "- 离场沿用 EMA21 失败退出。",
            "",
            "## raw vs trusted",
            "",
            json.dumps(trusted_summary, ensure_ascii=False, indent=2),
            "",
            "## score 分布",
            "",
            build_score_distribution_markdown(score_summary),
            "",
            "## Skill 标签结论",
            "",
            json.dumps(scene_summary, ensure_ascii=False, indent=2),
            "",
            "## 下一步建议",
            "",
            "- A. 调整 2-of-4 规则",
            "- B. 增加 v0.3.1 ATR stop / fast-fail",
            "- C. 做 rollover-safe 数据任务",
            "- D. 做条件组合消融",
            "- E. 回到日线方向 + 5m/15m 入场",
            "",
            build_comparison_markdown(package, baseline, trusted_summary),
        ]
    )


def sorted_fields(rows: list[dict[str, Any]]) -> list[str]:
    fields = sorted({str(key) for row in rows for key in row})
    return fields or ["empty"]


def _entry_score(row: dict[str, Any]) -> int:
    return _int_value(row.get("entry_score") or row.get("score"))


def _condition_combo(row: dict[str, Any]) -> str:
    values = _list_value(row.get("satisfied_conditions"))
    return "+".join(values)


def _list_value(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return [item for item in (part.strip() for part in stripped.split(";")) if item]
        return _list_value(parsed)
    return [str(value)]


def _float_value(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def _int_value(value: Any) -> int:
    if value in (None, ""):
        return 0
    return int(float(value))


def _scene_suggested_action(tag: str) -> str:
    if tag in {"weak_two_condition", "range_risk", "no_trend_alignment"}:
        return "review_or_restrict"
    if tag == "chase_risk":
        return "consider_anti_chase_filter_in_v0_3_1"
    return "keep_for_review"


if __name__ == "__main__":
    raise SystemExit(main())
