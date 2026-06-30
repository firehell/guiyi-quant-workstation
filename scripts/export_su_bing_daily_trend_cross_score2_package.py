from __future__ import annotations

import argparse
from collections import Counter
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

from export_su_bing_daily_score2of4_package import (  # noqa: E402
    SUMMARY_FIELDS,
    TRADE_FIELDS,
    build_scene_tag_summary,
    build_score_distribution_markdown,
    build_score_distribution_summary,
    score2of4_trade_row,
    sorted_fields,
)
from export_su_bing_report_10_review_package import (  # noqa: E402
    build_trusted_exclusion_summary,
    order_to_dict,
    report_to_dict,
    task_to_dict,
    trade_to_dict,
    write_csv,
)


STRATEGY_CODE = "su_bing_jm_daily_ema21_macd_volume"
STRATEGY_VERSION = "v0.3.1-daily-trend-cross-score2"
SPEC_DIR = PROJECT_ROOT / "docs" / "strategy_specs" / STRATEGY_CODE
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "backtests" / "reports" / "su_bing_daily_trend_cross_score2"
OUTPUT_PREFIX = "v0_3_1_trend_cross_score2"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR
    with SessionLocal() as session:
        package = load_report_package(session, args.report_id)
        baseline = load_optional_report_package(session, args.baseline_report_id)
        score2of4 = load_optional_report_package(session, args.score2of4_report_id)
    export_package(package, output_dir=output_dir, baseline=baseline, score2of4=score2of4)
    print(json.dumps({"report_id": args.report_id, "output_dir": str(output_dir)}, ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Su Bing daily trend-cross score2 review package.")
    parser.add_argument("--report-id", type=int, required=True)
    parser.add_argument("--baseline-report-id", type=int, default=10)
    parser.add_argument("--score2of4-report-id", type=int, default=11)
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
        trend_cross_score2_trade_row(trade_to_dict(row))
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


def export_package(
    package: dict[str, Any],
    *,
    output_dir: Path,
    baseline: dict[str, Any] | None,
    score2of4: dict[str, Any] | None,
) -> None:
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
        "V0.3.1 trend-cross score2 trusted metrics exclude cross-contract PnL; raw metrics are shown for audit only."
    )
    score_summary = build_score_distribution_summary(trades, candidates)
    scene_summary = build_scene_tag_summary(trades)

    write_csv(output_dir / f"{OUTPUT_PREFIX}_trades.csv", trades, TRADE_FIELDS)
    write_csv(output_dir / f"{OUTPUT_PREFIX}_orders.csv", package["orders"], sorted_fields(package["orders"]))
    write_csv(output_dir / f"{OUTPUT_PREFIX}_execution_events.csv", package["execution_events"], sorted_fields(package["execution_events"]))
    write_csv(output_dir / f"{OUTPUT_PREFIX}_signal_candidates.csv", candidates, sorted_fields(candidates))
    write_csv(output_dir / f"{OUTPUT_PREFIX}_rejected_signals.csv", package["rejected_signals"], sorted_fields(package["rejected_signals"]))
    write_csv(output_dir / f"{OUTPUT_PREFIX}_trusted_excluding_cross_contract.csv", [trusted_summary], SUMMARY_FIELDS)
    (output_dir / f"{OUTPUT_PREFIX}_summary.json").write_text(
        json.dumps(package["summary"], ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (output_dir / f"{OUTPUT_PREFIX}_signal_funnel.md").write_text(
        build_trend_cross_signal_funnel_markdown(candidates, package["rejected_signals"]),
        encoding="utf-8",
    )
    (output_dir / f"{OUTPUT_PREFIX}_score_distribution.md").write_text(
        build_score_distribution_markdown(score_summary),
        encoding="utf-8",
    )
    (output_dir / f"{OUTPUT_PREFIX}_trade_review.md").write_text(
        build_trade_review_markdown(package, trusted_summary, score_summary, scene_summary),
        encoding="utf-8",
    )
    (output_dir / f"{OUTPUT_PREFIX}_trusted_excluding_cross_contract.md").write_text(
        build_trusted_markdown(trusted_summary),
        encoding="utf-8",
    )
    (output_dir / "v0_2_vs_v0_3_vs_v0_3_1_trend_cross_score2_comparison.md").write_text(
        build_three_version_comparison_markdown(package, baseline, score2of4, trusted_summary),
        encoding="utf-8",
    )

    review = build_backtest_review_markdown(package, trusted_summary, score_summary, scene_summary, baseline, score2of4)
    handoff = build_handoff_markdown(package, trusted_summary, score_summary, scene_summary, baseline, score2of4)
    (SPEC_DIR / "V0_3_1_TREND_CROSS_SCORE2_BACKTEST_REVIEW.md").write_text(review, encoding="utf-8")
    (SPEC_DIR / "V0_3_1_TREND_CROSS_SCORE2_HANDOFF_FOR_CHATGPT.md").write_text(handoff, encoding="utf-8")


def trend_cross_score2_trade_row(row: dict[str, Any]) -> dict[str, Any]:
    return score2of4_trade_row(row)


def build_trend_cross_signal_funnel_markdown(candidates: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> str:
    accepted = [row for row in candidates if str(row.get("final_signal") or "") in {"long", "short"}]
    rejected_counts = Counter(str(row.get("rejected_reason") or row.get("reject_reason") or "") for row in rejected)
    lines = [
        "# V0.3.1 Trend Cross Score2 Signal Funnel",
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
    return "\n".join(
        [
            "# V0.3.1 Trend Cross Score2 Trade Review",
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
    )


def build_trusted_markdown(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# V0.3.1 Trusted Excluding Cross Contract",
            "",
            f"- metric_scope: `{summary['metric_scope']}`",
            f"- raw_trade_count: `{summary['raw_trade_count']}`",
            f"- trusted_trade_count: `{summary['trusted_trade_count']}`",
            f"- excluded_trade_count: `{summary['excluded_trade_count']}`",
            f"- trusted_net_pnl: `{summary['trusted_net_pnl']}`",
            "",
        ]
    )


def build_three_version_comparison_markdown(
    package: dict[str, Any],
    baseline: dict[str, Any] | None,
    score2of4: dict[str, Any] | None,
    trusted_summary: dict[str, Any],
) -> str:
    lines = ["# V0.2 vs V0.3 vs V0.3.1 Trend Cross Score2 Comparison", ""]
    baseline_summary = _optional_trusted_summary(baseline)
    score2of4_summary = _optional_trusted_summary(score2of4)
    lines.extend(
        [
            "| metric | v0.2 trusted baseline | v0.3.0 score2of4 trusted | v0.3.1 trend-cross trusted |",
            "|---|---:|---:|---:|",
            _comparison_row("trade_count", baseline_summary, score2of4_summary, trusted_summary, "trusted_trade_count"),
            _comparison_row("net_pnl", baseline_summary, score2of4_summary, trusted_summary, "trusted_net_pnl"),
            _comparison_row("win_rate", baseline_summary, score2of4_summary, trusted_summary, "trusted_win_rate"),
            _comparison_row(
                "profit_loss_ratio",
                baseline_summary,
                score2of4_summary,
                trusted_summary,
                "trusted_profit_loss_ratio",
            ),
            _comparison_row(
                "max_consecutive_losses",
                baseline_summary,
                score2of4_summary,
                trusted_summary,
                "trusted_max_consecutive_losses",
            ),
            "",
        ]
    )
    lines.append("")
    return "\n".join(lines)


def _optional_trusted_summary(package: dict[str, Any] | None) -> dict[str, Any] | None:
    if package is None:
        return None
    report = package.get("report") or {}
    return build_trusted_exclusion_summary(
        package.get("trades") or [],
        report_id=int(report.get("id") or 0),
        strategy_code=str(report.get("strategy_code") or STRATEGY_CODE),
        strategy_version=str(report.get("strategy_version") or ""),
    )


def _comparison_row(
    label: str,
    baseline: dict[str, Any] | None,
    score2of4: dict[str, Any] | None,
    trend_cross: dict[str, Any],
    key: str,
) -> str:
    return (
        f"| {label} | {_comparison_value(baseline, key)} | "
        f"{_comparison_value(score2of4, key)} | {_comparison_value(trend_cross, key)} |"
    )


def _comparison_value(summary: dict[str, Any] | None, key: str) -> Any:
    if summary is None:
        return "n/a"
    return summary.get(key, "n/a")


def build_backtest_review_markdown(
    package: dict[str, Any],
    trusted_summary: dict[str, Any],
    score_summary: dict[str, Any],
    scene_summary: dict[str, Any],
    baseline: dict[str, Any] | None,
    score2of4: dict[str, Any] | None,
) -> str:
    report = package["report"]
    return "\n".join(
        [
            "# V0_3_1_TREND_CROSS_SCORE2_BACKTEST_REVIEW",
            "",
            "## 1. 回测配置",
            "",
            f"- strategy_code: `{report['strategy_code']}`",
            f"- strategy_version: `{report['strategy_version']}`",
            f"- symbol: `{report['symbol']}`",
            f"- period: `{report['period']}`",
            f"- data_source: `{report['data_source']}`",
            f"- data_role: `{report['data_role']}`",
            "- entry_gate: `trend_alignment + matching_macd_cross`",
            "- metric_scope: `raw_and_trusted_excluding_cross_contract`",
            "",
            "## 2. 核心指标",
            "",
            json.dumps(trusted_summary, ensure_ascii=False, indent=2),
            "",
            "## 3. 三版本对比",
            "",
            build_three_version_comparison_markdown(package, baseline, score2of4, trusted_summary),
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
            "- 本版本只改变入场 gate，不启用止损、止盈、time exit 或自动反手。",
            "",
        ]
    )


def build_handoff_markdown(
    package: dict[str, Any],
    trusted_summary: dict[str, Any],
    score_summary: dict[str, Any],
    scene_summary: dict[str, Any],
    baseline: dict[str, Any] | None,
    score2of4: dict[str, Any] | None,
) -> str:
    return "\n".join(
        [
            "# V0_3_1_TREND_CROSS_SCORE2_HANDOFF_FOR_CHATGPT",
            "",
            "## 本轮做了什么",
            "",
            "- 新增并回测 `v0.3.1-daily-trend-cross-score2`。",
            "- 保留 `v0.2.0-daily` 与 `v0.3.0-daily-score2of4` 历史行为。",
            "- 输出 raw 与 trusted excluding cross-contract 指标。",
            "",
            "## 规则摘要",
            "",
            "- 开仓至少满足 2 分。",
            "- 默认必须同时满足趋势方向环境和对应方向 MACD 交叉。",
            "- MACD 近零轴和放量作为得分与复盘标签。",
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
            build_three_version_comparison_markdown(package, baseline, score2of4, trusted_summary),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
