from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, date, datetime
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.backtest import BacktestOrderModel, BacktestReportModel, BacktestTask, BacktestTradeModel  # noqa: E402
from app.models.data_center import MarketDataFile  # noqa: E402


STRATEGY_CODE = "su_bing_jm_daily_ema21_macd_volume"
STRATEGY_VERSION = "v0.2.0-daily"
SPEC_DIR = PROJECT_ROOT / "docs" / "strategy_specs" / STRATEGY_CODE
REPORTS_DIR = PROJECT_ROOT / "backtests" / "reports"

TRADE_REVIEW_CSV = REPORTS_DIR / "report_10_su_bing_daily_trade_review.csv"
TRADE_REVIEW_MD = REPORTS_DIR / "report_10_su_bing_daily_trade_review.md"
BAR_CONTEXT_CSV = REPORTS_DIR / "report_10_trade_bar_context.csv"
SIGNAL_CANDIDATES_CSV = REPORTS_DIR / "report_10_signal_candidates.csv"
REJECTED_SIGNALS_CSV = REPORTS_DIR / "report_10_rejected_signals.csv"
SIGNAL_FUNNEL_MD = REPORTS_DIR / "report_10_signal_funnel.md"
CURRENT_CODE_RULES_MD = SPEC_DIR / "CURRENT_CODE_RULES_v0.2.0.md"
SKILL_ALIGNMENT_TEMPLATE_MD = SPEC_DIR / "SKILL_ALIGNMENT_TEMPLATE.md"
TRUST_AUDIT_MD = SPEC_DIR / "REPORT_10_TRUST_AUDIT.md"

OUTPUT_FILES = [
    CURRENT_CODE_RULES_MD,
    TRADE_REVIEW_CSV,
    TRADE_REVIEW_MD,
    BAR_CONTEXT_CSV,
    SIGNAL_CANDIDATES_CSV,
    REJECTED_SIGNALS_CSV,
    SIGNAL_FUNNEL_MD,
    SKILL_ALIGNMENT_TEMPLATE_MD,
    TRUST_AUDIT_MD,
]

TRADE_REVIEW_FIELDS = [
    "trade_no",
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
    "gross_pnl",
    "net_pnl",
    "commission",
    "slippage",
    "margin_required",
    "holding_calendar_days",
    "holding_trading_days",
    "holding_bars_persisted_value",
    "holding_bars_current_value",
    "holding_bars_expected_value",
    "entry_reason",
    "exit_reason",
    "entry_ema21",
    "exit_ema21",
    "entry_close_vs_ema21",
    "exit_close_vs_ema21",
    "entry_macd_dif",
    "entry_macd_dea",
    "entry_macd_hist",
    "entry_macd_near_zero",
    "entry_macd_cross_type",
    "entry_volume",
    "entry_prev_volume",
    "entry_volume_expanded",
    "entry_atr",
    "max_favorable_excursion",
    "max_adverse_excursion",
    "mfe_r",
    "mae_r",
    "pnl_trust_status",
    "issue_reason",
]

BAR_CONTEXT_FIELDS = [
    "trade_id",
    "relation_to_trade",
    "datetime",
    "trading_day",
    "contract",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "open_interest",
    "ema21",
    "ema21_slope",
    "macd_dif",
    "macd_dea",
    "macd_hist",
    "macd_cross_type",
    "macd_near_zero_25",
    "macd_near_zero_50",
    "macd_near_zero_100",
    "volume_gt_prev",
    "volume_ma5",
    "volume_ma20",
    "atr14",
    "close_vs_ema21",
    "signal_generated",
    "signal_direction",
    "reject_reason",
    "position_state",
]

SIGNAL_FIELDS = [
    "datetime",
    "trading_day",
    "contract",
    "direction_candidate",
    "close",
    "ema21",
    "close_vs_ema21",
    "ema21_slope",
    "macd_dif",
    "macd_dea",
    "macd_hist",
    "macd_cross_type",
    "macd_near_zero_25",
    "macd_near_zero_50",
    "macd_near_zero_100",
    "volume",
    "prev_volume",
    "volume_expanded",
    "final_signal",
    "reject_reason",
    "all_failed_conditions",
    "position_state",
    "pending_order_state",
]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    with SessionLocal() as session:
        package = load_report_package(session, args.report_id)
    export_package(package)
    print(json.dumps({"report_id": args.report_id, "outputs": [str(path) for path in OUTPUT_FILES]}, ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Su Bing report 10 review package.")
    parser.add_argument("--report-id", type=int, default=10)
    return parser.parse_args(argv)


def load_report_package(session: Session, report_id: int) -> dict[str, Any]:
    report = session.get(BacktestReportModel, report_id)
    if report is None:
        raise SystemExit(f"report_id={report_id} does not exist")
    if report.strategy_code != STRATEGY_CODE or report.strategy_version != STRATEGY_VERSION:
        raise SystemExit(f"report_id={report_id} is not {STRATEGY_CODE}/{STRATEGY_VERSION}")
    task = session.get(BacktestTask, report.task_id)
    if task is None:
        raise SystemExit(f"task_id={report.task_id} does not exist")

    trades = [
        trade_to_dict(row)
        for row in session.scalars(
            select(BacktestTradeModel).where(BacktestTradeModel.report_id == report_id).order_by(BacktestTradeModel.sequence)
        )
    ]
    orders = [
        order_to_dict(row)
        for row in session.scalars(select(BacktestOrderModel).where(BacktestOrderModel.report_id == report_id).order_by(BacktestOrderModel.id))
    ]
    normalized = (task.result_payload or {}).get("normalized_result") or {}
    events = [dict(item) for item in normalized.get("strategy_execution_events") or []]
    rejected = [dict(item) for item in normalized.get("rejected_signals") or []]
    market_file = resolve_market_data_file(session, report)
    bar_frame = read_report_bars(market_file, report)
    return {
        "report": report_to_dict(report),
        "task": task_to_dict(task),
        "trades": trades,
        "orders": orders,
        "events": events,
        "rejected": rejected,
        "market_file": market_file_payload(market_file),
        "bar_frame": bar_frame,
    }


def resolve_market_data_file(session: Session, report: BacktestReportModel) -> MarketDataFile:
    row = session.scalar(
        select(MarketDataFile)
        .where(
            MarketDataFile.provider == "rqdata",
            MarketDataFile.instrument_symbol == "jm",
            MarketDataFile.contract_code == "jm.MAIN",
            MarketDataFile.period == "1d",
            MarketDataFile.data_role == "primary",
            MarketDataFile.quality_status == "passed",
            MarketDataFile.data_version == report.data_version,
        )
        .order_by(MarketDataFile.id.desc())
        .limit(1)
    )
    if row is None:
        raise SystemExit(f"cannot resolve primary passed JM 1d MarketDataFile for data_version={report.data_version}")
    path = Path(row.file_path)
    if not path.exists():
        raise SystemExit(f"MarketDataFile path does not exist: {path}")
    return row


def read_report_bars(market_file: MarketDataFile, report: BacktestReportModel) -> pd.DataFrame:
    frame = pd.read_parquet(market_file.file_path)
    frame = frame.copy()
    frame["datetime"] = pd.to_datetime(frame["datetime"]).dt.tz_localize(None)
    start = parse_dt((report.summary or {}).get("start") or (report.summary or {}).get("report_metadata", {}).get("start"))
    end = parse_dt((report.summary or {}).get("end") or (report.summary or {}).get("report_metadata", {}).get("end"))
    if start is not None:
        frame = frame[frame["datetime"] >= start]
    if end is not None:
        frame = frame[frame["datetime"] <= end]
    return frame.sort_values("datetime").reset_index(drop=True)


def export_package(package: dict[str, Any]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    SPEC_DIR.mkdir(parents=True, exist_ok=True)

    indicator_frame = compute_indicator_frame(package["bar_frame"])
    entry_signal_times = {
        parse_dt(trade["entry_signal_time"]): trade["direction"]
        for trade in package["trades"]
        if parse_dt(trade.get("entry_signal_time")) is not None
    }
    exit_signal_times = {
        parse_dt(trade["exit_signal_time"]): f"exit_{trade['direction']}"
        for trade in package["trades"]
        if parse_dt(trade.get("exit_signal_time")) is not None
    }
    runtime_reject_reasons = {
        parse_dt(item.get("bar_datetime")): str(item.get("rejected_reason") or "")
        for item in package["rejected"]
        if parse_dt(item.get("bar_datetime")) is not None
    }
    position_states, pending_states = build_runtime_state_maps(package["trades"], indicator_frame)
    candidates = build_signal_candidate_rows(
        indicator_frame,
        entry_signal_times=entry_signal_times,
        runtime_reject_reasons=runtime_reject_reasons,
        position_states=position_states,
        pending_states=pending_states,
    )
    rejected_rows = build_rejected_signal_rows(package["rejected"], candidates)
    trade_rows = build_trade_review_rows(package["trades"], indicator_frame)
    context_rows = build_trade_bar_context_rows(
        package["trades"],
        indicator_frame,
        candidates,
        entry_signal_times=entry_signal_times,
        exit_signal_times=exit_signal_times,
    )

    write_csv(TRADE_REVIEW_CSV, trade_rows, TRADE_REVIEW_FIELDS)
    write_csv(BAR_CONTEXT_CSV, context_rows, BAR_CONTEXT_FIELDS)
    write_csv(SIGNAL_CANDIDATES_CSV, candidates, SIGNAL_FIELDS)
    write_csv(REJECTED_SIGNALS_CSV, rejected_rows, SIGNAL_FIELDS + ["runtime_reject_reason", "runtime_decision_status"])
    TRADE_REVIEW_MD.write_text(build_trade_review_markdown(package, trade_rows), encoding="utf-8")
    SIGNAL_FUNNEL_MD.write_text(build_signal_funnel_markdown(indicator_frame, candidates, rejected_rows), encoding="utf-8")
    CURRENT_CODE_RULES_MD.write_text(build_current_code_rules(package), encoding="utf-8")
    SKILL_ALIGNMENT_TEMPLATE_MD.write_text(build_skill_alignment_template(), encoding="utf-8")
    TRUST_AUDIT_MD.write_text(build_trust_audit(package, trade_rows, rejected_rows), encoding="utf-8")


def compute_indicator_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy().sort_values("datetime").reset_index(drop=True)
    out["datetime"] = pd.to_datetime(out["datetime"]).dt.tz_localize(None)
    out["ema21"] = out["close"].ewm(span=21, adjust=False).mean()
    fast = out["close"].ewm(span=12, adjust=False).mean()
    slow = out["close"].ewm(span=26, adjust=False).mean()
    out["macd_dif"] = fast - slow
    out["macd_dea"] = out["macd_dif"].ewm(span=9, adjust=False).mean()
    out["macd_hist"] = out["macd_dif"] - out["macd_dea"]
    out["previous_dif"] = out["macd_dif"].shift(1)
    out["previous_dea"] = out["macd_dea"].shift(1)
    out["prev_volume"] = out["volume"].shift(1)
    out["volume_gt_prev"] = out["volume"] > out["prev_volume"]
    out["volume_ma5"] = out["volume"].rolling(5, min_periods=1).mean()
    out["volume_ma20"] = out["volume"].rolling(20, min_periods=1).mean()
    out["ema21_slope"] = out["ema21"] - out["ema21"].shift(1)
    out["close_vs_ema21"] = out.apply(close_vs_ema21, axis=1)
    out["macd_cross_type"] = out.apply(macd_cross_type, axis=1)
    for band in (25, 50, 100):
        out[f"macd_near_zero_{band}"] = (out["macd_dif"].abs() <= band) & (out["macd_dea"].abs() <= band)
    prev_close = out["close"].shift(1)
    true_range = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr14"] = true_range.rolling(14, min_periods=1).mean()
    out["bar_index"] = out.index
    return out


def build_signal_candidate_rows(
    indicator_frame: pd.DataFrame,
    *,
    entry_signal_times: dict[datetime | None, str] | None = None,
    runtime_reject_reasons: dict[datetime | None, str] | None = None,
    position_states: dict[datetime | None, str] | None = None,
    pending_states: dict[datetime | None, str] | None = None,
) -> list[dict[str, Any]]:
    entry_signal_times = entry_signal_times or {}
    runtime_reject_reasons = runtime_reject_reasons or {}
    position_states = position_states or {}
    pending_states = pending_states or {}
    rows: list[dict[str, Any]] = []
    for _, bar in indicator_frame.iterrows():
        if int(bar["bar_index"]) < 27:
            continue
        signal_time = normalize_dt(bar["datetime"])
        direction_candidate = direction_candidate_from_bar(bar)
        runtime_direction = entry_signal_times.get(signal_time)
        if entry_signal_times or runtime_reject_reasons:
            final_signal = runtime_direction if runtime_direction in {"long", "short"} else ""
            reject_reason = runtime_reject_reasons.get(signal_time, "")
        else:
            final_signal = final_signal_from_bar(bar, direction_candidate)
            reject_reason = "" if final_signal in {"long", "short"} else reject_reason_from_bar(bar, direction_candidate)
        row = signal_row_from_bar(bar, direction_candidate, final_signal, reject_reason)
        row["position_state"] = position_states.get(signal_time, "")
        row["pending_order_state"] = pending_states.get(signal_time, "")
        rows.append(row)
    return rows


def build_rejected_signal_rows(rejected: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_time = {parse_dt(row["datetime"]): row for row in candidates}
    rows: list[dict[str, Any]] = []
    for item in rejected:
        bar_time = parse_dt(item.get("bar_datetime"))
        base = dict(by_time.get(bar_time) or empty_signal_row(bar_time))
        reason = str(item.get("rejected_reason") or base.get("reject_reason") or "")
        base["reject_reason"] = reason
        base["final_signal"] = ""
        base["runtime_reject_reason"] = reason
        base["runtime_decision_status"] = str(item.get("decision_status") or "")
        rows.append(base)
    return rows


def build_trade_review_rows(trades: list[dict[str, Any]], indicator_frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_time = {normalize_dt(row["datetime"]): row for _, row in indicator_frame.iterrows()}
    for trade in trades:
        entry_signal_time = parse_dt(trade.get("entry_signal_time"))
        exit_signal_time = parse_dt(trade.get("exit_signal_time"))
        open_time = parse_dt(trade.get("open_time"))
        close_time = parse_dt(trade.get("close_time"))
        entry_bar = by_time.get(entry_signal_time)
        exit_bar = by_time.get(exit_signal_time)
        holding = holding_frame(indicator_frame, open_time, close_time)
        mfe, mae = compute_mfe_mae(trade, holding)
        persisted_holding_bars = int(float(trade.get("holding_bars") or 0))
        expected_holding_bars = expected_bar_distance(indicator_frame, open_time, close_time)
        holding_trading_days = trade_holding_trading_days(trade, expected_holding_bars)
        current_holding_bars = resolved_holding_bars(persisted_holding_bars, expected_holding_bars)
        cross_contract = bool(trade.get("entry_contract") and trade.get("exit_contract") and trade["entry_contract"] != trade["exit_contract"])
        issues = []
        if cross_contract:
            issues.append("entry_contract_differs_from_exit_contract")
        if persisted_holding_bars == 0 and expected_holding_bars not in ("", 0):
            issues.append("persisted_holding_bars_zero")
        rows.append(
            {
                "trade_no": trade.get("trade_no") or trade.get("trade_id"),
                "trade_id": trade.get("trade_no") or trade.get("trade_id"),
                "direction": trade.get("direction"),
                "entry_signal_time": iso_or_blank(entry_signal_time),
                "open_time": iso_or_blank(open_time),
                "open_price": trade.get("open_price"),
                "exit_signal_time": iso_or_blank(exit_signal_time),
                "close_time": iso_or_blank(close_time),
                "close_price": trade.get("close_price"),
                "entry_contract": trade.get("entry_contract"),
                "exit_contract": trade.get("exit_contract"),
                "is_cross_contract": cross_contract,
                "gross_pnl": trade.get("gross_pnl"),
                "net_pnl": trade.get("net_pnl"),
                "commission": trade.get("commission"),
                "slippage": trade.get("slippage"),
                "margin_required": trade.get("margin_required"),
                "holding_calendar_days": calendar_days(open_time, close_time),
                "holding_trading_days": holding_trading_days,
                "holding_bars_persisted_value": persisted_holding_bars,
                "holding_bars_current_value": current_holding_bars,
                "holding_bars_expected_value": expected_holding_bars,
                "entry_reason": trade.get("entry_reason"),
                "exit_reason": trade.get("exit_reason"),
                "entry_ema21": value_from_bar_or_raw(entry_bar, trade, "ema21"),
                "exit_ema21": value_from_bar(exit_bar, "ema21"),
                "entry_close_vs_ema21": value_from_bar(entry_bar, "close_vs_ema21"),
                "exit_close_vs_ema21": value_from_bar(exit_bar, "close_vs_ema21"),
                "entry_macd_dif": value_from_bar_or_raw(entry_bar, trade, "macd_dif", "current_dif"),
                "entry_macd_dea": value_from_bar_or_raw(entry_bar, trade, "macd_dea", "current_dea"),
                "entry_macd_hist": value_from_bar(entry_bar, "macd_hist"),
                "entry_macd_near_zero": value_from_bar(entry_bar, "macd_near_zero_25"),
                "entry_macd_cross_type": value_from_bar(entry_bar, "macd_cross_type"),
                "entry_volume": value_from_bar_or_raw(entry_bar, trade, "volume", "current_volume"),
                "entry_prev_volume": value_from_bar_or_raw(entry_bar, trade, "prev_volume", "previous_volume"),
                "entry_volume_expanded": value_from_bar(entry_bar, "volume_gt_prev"),
                "entry_atr": value_from_bar(entry_bar, "atr14"),
                "max_favorable_excursion": mfe,
                "max_adverse_excursion": mae,
                "mfe_r": "",
                "mae_r": "",
                "pnl_trust_status": "cross_contract_needs_review" if cross_contract else "traceable_same_contract",
                "issue_reason": ";".join(issues),
            }
        )
    return rows


def build_trade_bar_context_rows(
    trades: list[dict[str, Any]],
    indicator_frame: pd.DataFrame,
    candidates: list[dict[str, Any]],
    *,
    entry_signal_times: dict[datetime | None, str],
    exit_signal_times: dict[datetime | None, str],
) -> list[dict[str, Any]]:
    candidate_by_time = {parse_dt(row["datetime"]): row for row in candidates}
    rows: list[dict[str, Any]] = []
    for trade in trades:
        trade_id = str(trade.get("trade_no") or trade.get("trade_id"))
        entry_signal_time = parse_dt(trade.get("entry_signal_time"))
        open_time = parse_dt(trade.get("open_time"))
        close_time = parse_dt(trade.get("close_time"))
        entry_index = index_for_time(indicator_frame, entry_signal_time)
        open_index = index_for_time(indicator_frame, open_time)
        close_index = index_for_time(indicator_frame, close_time)
        if entry_index is None or open_index is None or close_index is None:
            continue
        slices = [
            ("pre_entry", range(max(0, entry_index - 30), entry_index)),
            ("holding", range(open_index, close_index + 1)),
            ("post_exit", range(close_index + 1, min(len(indicator_frame), close_index + 11))),
        ]
        for relation, indexes in slices:
            for row_index in indexes:
                bar = indicator_frame.iloc[row_index]
                bar_time = normalize_dt(bar["datetime"])
                candidate = candidate_by_time.get(bar_time, {})
                signal_direction = entry_signal_times.get(bar_time) or exit_signal_times.get(bar_time) or ""
                rows.append(context_row(trade_id, relation, bar, candidate, signal_direction))
    return rows


def build_runtime_state_maps(
    trades: list[dict[str, Any]],
    indicator_frame: pd.DataFrame,
) -> tuple[dict[datetime | None, str], dict[datetime | None, str]]:
    position_states: dict[datetime | None, str] = {}
    pending_states: dict[datetime | None, str] = {}
    for _, bar in indicator_frame.iterrows():
        bar_time = normalize_dt(bar["datetime"])
        for trade in trades:
            entry_signal_time = parse_dt(trade.get("entry_signal_time"))
            open_time = parse_dt(trade.get("open_time"))
            exit_signal_time = parse_dt(trade.get("exit_signal_time"))
            close_time = parse_dt(trade.get("close_time"))
            if entry_signal_time is not None and open_time is not None and entry_signal_time <= bar_time < open_time:
                pending_states[bar_time] = "pending_entry"
            if exit_signal_time is not None and close_time is not None and exit_signal_time <= bar_time < close_time:
                pending_states[bar_time] = "pending_exit"
            if open_time is not None and close_time is not None and open_time <= bar_time < close_time:
                position_states[bar_time] = f"holding_{trade.get('direction')}"
    return position_states, pending_states


def build_signal_funnel_markdown(indicator_frame: pd.DataFrame, candidates: list[dict[str, Any]], rejected_rows: list[dict[str, Any]]) -> str:
    candidate_frame = pd.DataFrame(candidates)
    rejected_counts = Counter(row.get("runtime_reject_reason") for row in rejected_rows)
    lines = [
        "# Report 10 Signal Funnel",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| 总 K 线数量 | {len(indicator_frame)} |",
        f"| warmup 后数量 | {len(candidates)} |",
        f"| close > EMA21 数量 | {count_condition(candidate_frame, 'close_vs_ema21', 'above')} |",
        f"| close < EMA21 数量 | {count_condition(candidate_frame, 'close_vs_ema21', 'below')} |",
        f"| EMA21 斜率向上数量 | {int((candidate_frame.get('ema21_slope', pd.Series(dtype=float)) > 0).sum()) if not candidate_frame.empty else 0} |",
        f"| EMA21 斜率向下数量 | {int((candidate_frame.get('ema21_slope', pd.Series(dtype=float)) < 0).sum()) if not candidate_frame.empty else 0} |",
        f"| MACD 金叉数量 | {count_condition(candidate_frame, 'macd_cross_type', 'golden_cross')} |",
        f"| MACD 死叉数量 | {count_condition(candidate_frame, 'macd_cross_type', 'dead_cross')} |",
        f"| MACD +-25 数量 | {count_true(candidate_frame, 'macd_near_zero_25')} |",
        f"| MACD +-50 数量 | {count_true(candidate_frame, 'macd_near_zero_50')} |",
        f"| MACD +-100 数量 | {count_true(candidate_frame, 'macd_near_zero_100')} |",
        f"| MACD +-25 内金叉数量 | {count_cross_inside_band(candidate_frame, 'golden_cross', 'macd_near_zero_25')} |",
        f"| MACD +-25 内死叉数量 | {count_cross_inside_band(candidate_frame, 'dead_cross', 'macd_near_zero_25')} |",
        f"| volume > prev_volume 数量 | {count_true(candidate_frame, 'volume_expanded')} |",
        f"| 多头候选数量 | {count_condition(candidate_frame, 'direction_candidate', 'long')} |",
        f"| 空头候选数量 | {count_condition(candidate_frame, 'direction_candidate', 'short')} |",
        f"| 最终入场数量 | {sum(1 for row in candidates if row.get('final_signal') in {'long', 'short'})} |",
    ]
    for reason in ("daily_entry_conditions_not_met", "macd_not_near_zero", "volume_not_expanded"):
        lines.append(f"| rejected reason: {reason} | {rejected_counts.get(reason, 0)} |")
    lines.extend(["", "本文件只统计当前代码规则命中情况，不做参数优化结论。", ""])
    return "\n".join(lines)


def build_trade_review_markdown(package: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    report = package["report"]
    total_net = sum(float(row.get("net_pnl") or 0) for row in rows)
    cross_count = sum(1 for row in rows if row.get("is_cross_contract"))
    lines = [
        "# Report 10 Su Bing Daily Trade Review",
        "",
        f"- report_id: `{report['id']}`",
        f"- task_id: `{report['task_id']}`",
        f"- strategy: `{report['strategy_code']} / {report['strategy_version']}`",
        f"- trade_count: `{len(rows)}`",
        f"- net_pnl_sum: `{total_net:.3f}`",
        f"- cross_contract_trades: `{cross_count}`",
        "",
        "| trade_id | direction | open_time | close_time | entry_contract | exit_contract | net_pnl | status | issue_reason |",
        "|---|---|---|---|---|---|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {trade_id} | {direction} | {open_time} | {close_time} | {entry_contract} | {exit_contract} | {net_pnl} | {status} | {issue} |".format(
                trade_id=row["trade_id"],
                direction=row["direction"],
                open_time=row["open_time"],
                close_time=row["close_time"],
                entry_contract=row["entry_contract"],
                exit_contract=row["exit_contract"],
                net_pnl=row["net_pnl"],
                status=row["pnl_trust_status"],
                issue=row["issue_reason"],
            )
        )
    lines.extend(["", "MFE/MAE 按持仓窗口日线 high/low、方向、合约乘数和手数估算；R 倍数因 v0.2.0 未启用止损而留空。", ""])
    return "\n".join(lines)


def build_current_code_rules(package: dict[str, Any]) -> str:
    report = package["report"]
    rejected_counts = Counter(item.get("rejected_reason") for item in package["rejected"])
    return f"""# CURRENT_CODE_RULES_v0.2.0

## Scope

- strategy_code: `{STRATEGY_CODE}`
- strategy_version: `{STRATEGY_VERSION}`
- report_id: `{report["id"]}`
- task_id: `{report["task_id"]}`
- data_source: `{report["data_source"]}`
- data_role: `{report["data_role"]}`
- data_version: `{report["data_version"]}`

## Current Entry Logic

The actual code in `packages/quant-core/guiyi_quant/strategies/{STRATEGY_CODE}/vnpy_strategy.py` only accepts daily bars.

- Warm-up requires `max(21, 12, 26, 9) + 2` completed daily bars.
- Indicators use completed daily close/volume only: EMA21, MACD DIF/DEA/histogram with `12/26/9`.
- MACD near-zero is `abs(DIF) <= 25 and abs(DEA) <= 25`.
- Volume confirmation is `current_volume > previous_volume`.
- Long signal: `close > EMA21`, MACD near zero, golden cross, volume expansion.
- Short signal: `close < EMA21`, MACD near zero, dead cross, volume expansion.
- Signal is produced on completed daily close and filled on the next daily open with one adverse tick.

## Current Exit Logic

- Long exit: completed daily close below EMA21, filled on next daily open.
- Short exit: completed daily close above EMA21, filled on next daily open.
- Fixed stop loss, take profit, time exit, pyramiding, same-day reverse, live trading, and auto ordering are disabled.

## Current Parameters

See `packages/quant-core/guiyi_quant/strategies/{STRATEGY_CODE}/config_schema.py` and `default_params.json`.

- `ema_period=21`
- `macd_fast=12`
- `macd_slow=26`
- `macd_signal=9`
- `jm_macd_zero_band=25`
- `volume_confirm_enabled=True`
- `volume_rule=current_volume_gt_previous_volume`
- `maximum_position=1`
- `allow_long=True`
- `allow_short=True`
- `slippage_ticks=1`
- `submit_vnpy_orders=False`
- `live_trading_enabled=False`
- `auto_order_enabled=False`

## submit_vnpy_orders=False

`submit_vnpy_orders=False` means this strategy records internal research trades in `strategy_trades` and runtime events in `execution_events`.
It does not submit vn.py order objects for the engine order ledger.

Therefore `orders_count=0` and `strategy_execution_events_count=14` can coexist with 7 completed research trades.
The 14 execution events map to 7 opens and 7 closes.

## Rejected Reason Generation

The code evaluates rejected reasons in this order:

1. `macd_not_near_zero`
2. `volume_not_expanded`
3. `daily_entry_conditions_not_met`

Report 10 runtime rejected reasons:

- `macd_not_near_zero`: {rejected_counts.get("macd_not_near_zero", 0)}
- `volume_not_expanded`: {rejected_counts.get("volume_not_expanded", 0)}
- `daily_entry_conditions_not_met`: {rejected_counts.get("daily_entry_conditions_not_met", 0)}

## Possible Code vs Su Bing Thought Gaps

These are疑点 only, not conclusions:

- EMA21 is used as a strict close-position filter, but no trend-strength or structure context is encoded.
- MACD near-zero threshold `25` is a current spec decision, not proven here as a course rule.
- Volume confirmation is reduced to `current_volume > previous_volume`.
- No explicit anti-chase, range filter, fixed stop loss, floating profit protection, or review-tag feedback is used in signal generation.
- Holding can last many daily bars because time exit is disabled.
- Cross-contract PnL needs extra review when entry and exit mapped contracts differ.
"""


def build_skill_alignment_template() -> str:
    rows = [
        ("趋势方向", "close > EMA21 偏多，close < EMA21 偏空；未使用更高周期趋势。"),
        ("EMA21 位置", "多头要求 daily close > EMA21；空头要求 daily close < EMA21。"),
        ("EMA21 斜率", "当前入场不要求 EMA21 斜率；只在导出中记录 `ema21_slope`。"),
        ("突破 / 回踩 / 收回 EMA21", "当前代码不识别突破、回踩或收回形态，只检查收盘价与 EMA21 位置。"),
        ("MACD 零轴附近", "要求 `abs(DIF) <= 25 and abs(DEA) <= 25`。"),
        ("MACD 金叉 / 死叉", "多头要求金叉；空头要求死叉。"),
        ("成交量确认", "要求 `current_volume > previous_volume`。"),
        ("禁止追高 / 杀跌", "当前代码没有独立追高/杀跌过滤。"),
        ("震荡区过滤", "当前代码没有独立震荡区过滤。"),
        ("入场触发", "日线收盘确认信号，下一根日线 open 成交，1 tick 不利滑点。"),
        ("持仓逻辑", "最多 1 手；无 pyramiding；无同日反手；持仓直到 EMA21 失效。"),
        ("离场逻辑", "多单 close < EMA21 后下一日 open 平；空单 close > EMA21 后下一日 open 平。"),
        ("止损逻辑", "v0.2.0-daily 禁用固定止损。"),
        ("浮盈保护", "当前代码没有浮盈保护。"),
        ("多空对称性", "多空在 EMA21 位置、MACD 交叉、成交量确认上基本对称。"),
        ("换月 / 主连处理", "回测研究符号为 `jm.MAIN`，成交合约由主力映射补充；未做强制换月平仓。"),
        ("信号强弱评分", "当前代码没有信号强弱评分。"),
    ]
    lines = [
        "# SKILL_ALIGNMENT_TEMPLATE",
        "",
        "本模板只填当前代码规则，不编造苏冰 Skill 规则。`su_bing_skill_rule` 留给后续人工或 ChatGPT 对齐。",
        "",
        "| rule_category | current_code_rule | su_bing_skill_rule | match_status | impact_on_report_10 | suggested_action | priority |",
        "|---|---|---|---|---|---|---|",
    ]
    for category, current_rule in rows:
        lines.append(f"| {category} | {current_rule} | 待填写 | unclear | 待对齐后评估 | 待填写 | P1 |")
    lines.append("")
    return "\n".join(lines)


def build_trust_audit(package: dict[str, Any], trade_rows: list[dict[str, Any]], rejected_rows: list[dict[str, Any]]) -> str:
    report = package["report"]
    cross = [row for row in trade_rows if row["is_cross_contract"]]
    return f"""# REPORT_10_TRUST_AUDIT

## Summary

- report_id: `{report["id"]}`
- task_id: `{report["task_id"]}`
- strategy: `{report["strategy_code"]} / {report["strategy_version"]}`
- trades: `{len(trade_rows)}`
- orders: `{len(package["orders"])}`
- strategy_execution_events: `{len(package["events"])}`
- rejected_signals: `{len(package["rejected"])}`

## Required Checks

| Check | Result |
|---|---|
| 7 笔交易中是否存在 entry_contract != exit_contract | {'Yes: ' + ', '.join(row['trade_id'] for row in cross) if cross else 'No'} |
| 跨合约 PnL 是否可信 | 需要复核；跨合约交易标记为 `cross_contract_needs_review`。 |
| 主连换月是否有真实 rollover 处理 | 当前 summary 显示 `forced_rollover_exit_policy=not_applied_for_daily_v0_2_0`。 |
| holding_bars 当前导出口径 | 旧持久化字段仍为 0；本导出保留 `holding_bars_persisted_value`，并用 K 线窗口生成 `holding_bars_current_value` 和 `holding_trading_days`。 |
| orders_count=0 是否只是 submit_vnpy_orders=False 的设计结果 | 是；研究交易来自 `strategy_trades`，不是 vn.py order ledger。 |
| strategy_execution_events_count=14 是否能完整对应 7 笔开平 | 是；7 open + 7 close。 |
| 每笔 PnL 是否可追溯到 K 线 | 同合约交易可追溯；跨合约交易需额外复核主力映射和价格连续性。 |
| 手续费、滑点、合约乘数是否正确 | 已导出字段；需外部审查交易所参数和主力映射。 |
| report_id=10 是否可以用于策略优化 | 不建议直接优化；应先做规则对齐和可信度复核。 |
| 如果不能，阻塞项 | 跨合约 PnL、旧报告持久化 holding_bars 为 0、无止损 R 单位、样本交易数仅 7。 |

## Conclusion

Report 10 可以作为规则对齐和逐笔复盘输入包，但不应直接作为参数优化依据。
"""


def trade_to_dict(row: BacktestTradeModel) -> dict[str, Any]:
    return {
        "trade_no": row.trade_no,
        "sequence": row.sequence,
        "symbol": row.symbol,
        "research_contract": row.research_contract,
        "contract": row.contract,
        "entry_contract": row.entry_contract,
        "exit_contract": row.exit_contract,
        "timeframe": row.timeframe,
        "direction": row.direction,
        "entry_signal_time": iso_or_blank(row.entry_signal_time),
        "open_time": iso_or_blank(row.open_time),
        "open_price": row.open_price,
        "exit_signal_time": iso_or_blank(row.exit_signal_time),
        "close_time": iso_or_blank(row.close_time),
        "close_price": row.close_price,
        "volume": row.volume,
        "turnover": row.turnover,
        "contract_multiplier": row.contract_multiplier,
        "price_tick": row.price_tick,
        "commission": row.commission,
        "slippage": row.slippage,
        "margin_ratio": row.margin_ratio,
        "margin_required": row.margin_required,
        "gross_pnl": row.gross_pnl,
        "net_pnl": row.net_pnl,
        "return_pct": row.return_pct,
        "holding_bars": row.holding_bars,
        "entry_reason": row.entry_reason,
        "exit_reason": row.exit_reason,
        "parameter_source": row.parameter_source,
        "raw_payload": row.raw_payload or {},
    }


def order_to_dict(row: BacktestOrderModel) -> dict[str, Any]:
    return {"order_no": row.order_no, "status": row.status, "raw_payload": row.raw_payload or {}}


def report_to_dict(row: BacktestReportModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "task_no": row.task_no,
        "report_no": row.report_no,
        "strategy_code": row.strategy_code,
        "strategy_version": row.strategy_version,
        "status": row.status,
        "symbol": row.symbol,
        "contract": row.contract,
        "period": row.period,
        "data_source": row.data_source,
        "data_role": row.data_role,
        "data_version": row.data_version,
        "summary": row.summary or {},
    }


def task_to_dict(row: BacktestTask) -> dict[str, Any]:
    return {"id": row.id, "task_no": row.task_no, "status": row.status, "task_type": row.task_type}


def market_file_payload(row: MarketDataFile) -> dict[str, Any]:
    return {"id": row.id, "file_path": row.file_path, "data_version": row.data_version}


def signal_row_from_bar(bar: pd.Series, direction_candidate: str, final_signal: str, reject_reason: str) -> dict[str, Any]:
    return {
        "datetime": iso_or_blank(normalize_dt(bar["datetime"])),
        "trading_day": str(bar.get("trading_day") or ""),
        "contract": contract_from_bar(bar),
        "direction_candidate": direction_candidate,
        "close": round_float(bar["close"]),
        "ema21": round_float(bar["ema21"]),
        "close_vs_ema21": bar["close_vs_ema21"],
        "ema21_slope": round_float(bar["ema21_slope"]),
        "macd_dif": round_float(bar["macd_dif"]),
        "macd_dea": round_float(bar["macd_dea"]),
        "macd_hist": round_float(bar["macd_hist"]),
        "macd_cross_type": bar["macd_cross_type"],
        "macd_near_zero_25": bool(bar["macd_near_zero_25"]),
        "macd_near_zero_50": bool(bar["macd_near_zero_50"]),
        "macd_near_zero_100": bool(bar["macd_near_zero_100"]),
        "volume": round_float(bar["volume"]),
        "prev_volume": round_float(bar["prev_volume"]),
        "volume_expanded": bool(bar["volume_gt_prev"]),
        "final_signal": final_signal,
        "reject_reason": reject_reason,
        "all_failed_conditions": ";".join(failed_conditions(bar, direction_candidate)),
        "position_state": "",
        "pending_order_state": "",
    }


def context_row(trade_id: str, relation: str, bar: pd.Series, candidate: dict[str, Any], signal_direction: str) -> dict[str, Any]:
    return {
        "trade_id": trade_id,
        "relation_to_trade": relation,
        "datetime": iso_or_blank(normalize_dt(bar["datetime"])),
        "trading_day": str(bar.get("trading_day") or ""),
        "contract": contract_from_bar(bar),
        "open": round_float(bar["open"]),
        "high": round_float(bar["high"]),
        "low": round_float(bar["low"]),
        "close": round_float(bar["close"]),
        "volume": round_float(bar["volume"]),
        "open_interest": round_float(bar.get("open_interest")),
        "ema21": round_float(bar["ema21"]),
        "ema21_slope": round_float(bar["ema21_slope"]),
        "macd_dif": round_float(bar["macd_dif"]),
        "macd_dea": round_float(bar["macd_dea"]),
        "macd_hist": round_float(bar["macd_hist"]),
        "macd_cross_type": bar["macd_cross_type"],
        "macd_near_zero_25": bool(bar["macd_near_zero_25"]),
        "macd_near_zero_50": bool(bar["macd_near_zero_50"]),
        "macd_near_zero_100": bool(bar["macd_near_zero_100"]),
        "volume_gt_prev": bool(bar["volume_gt_prev"]),
        "volume_ma5": round_float(bar["volume_ma5"]),
        "volume_ma20": round_float(bar["volume_ma20"]),
        "atr14": round_float(bar["atr14"]),
        "close_vs_ema21": bar["close_vs_ema21"],
        "signal_generated": bool(signal_direction),
        "signal_direction": signal_direction,
        "reject_reason": candidate.get("reject_reason", ""),
        "position_state": "holding" if relation == "holding" else "flat",
    }


def empty_signal_row(bar_time: datetime | None) -> dict[str, Any]:
    return {field: "" for field in SIGNAL_FIELDS} | {"datetime": iso_or_blank(bar_time)}


def direction_candidate_from_bar(bar: pd.Series) -> str:
    if bar["close"] > bar["ema21"] and bar["macd_cross_type"] == "golden_cross":
        return "long"
    if bar["close"] < bar["ema21"] and bar["macd_cross_type"] == "dead_cross":
        return "short"
    return ""


def final_signal_from_bar(bar: pd.Series, direction_candidate: str) -> str:
    if bool(bar["macd_near_zero_25"]) and bool(bar["volume_gt_prev"]) and direction_candidate in {"long", "short"}:
        return direction_candidate
    return ""


def reject_reason_from_bar(bar: pd.Series, direction_candidate: str) -> str:
    if not bool(bar["macd_near_zero_25"]):
        return "macd_not_near_zero"
    if not bool(bar["volume_gt_prev"]):
        return "volume_not_expanded"
    if direction_candidate not in {"long", "short"}:
        return "daily_entry_conditions_not_met"
    return ""


def failed_conditions(bar: pd.Series, direction_candidate: str) -> list[str]:
    failed = []
    if not bool(bar["macd_near_zero_25"]):
        failed.append("macd_not_near_zero")
    if not bool(bar["volume_gt_prev"]):
        failed.append("volume_not_expanded")
    if direction_candidate not in {"long", "short"}:
        failed.append("daily_entry_conditions_not_met")
    return failed


def close_vs_ema21(row: pd.Series) -> str:
    if row["close"] > row["ema21"]:
        return "above"
    if row["close"] < row["ema21"]:
        return "below"
    return "equal"


def macd_cross_type(row: pd.Series) -> str:
    if pd.isna(row["previous_dif"]) or pd.isna(row["previous_dea"]):
        return ""
    if row["previous_dif"] <= row["previous_dea"] and row["macd_dif"] > row["macd_dea"]:
        return "golden_cross"
    if row["previous_dif"] >= row["previous_dea"] and row["macd_dif"] < row["macd_dea"]:
        return "dead_cross"
    return ""


def holding_frame(indicator_frame: pd.DataFrame, open_time: datetime | None, close_time: datetime | None) -> pd.DataFrame:
    if open_time is None or close_time is None:
        return indicator_frame.iloc[0:0]
    return indicator_frame[(indicator_frame["datetime"] >= open_time) & (indicator_frame["datetime"] <= close_time)]


def compute_mfe_mae(trade: dict[str, Any], holding: pd.DataFrame) -> tuple[float | str, float | str]:
    if holding.empty:
        return "", ""
    entry_price = float(trade.get("open_price") or 0)
    multiplier = float(trade.get("contract_multiplier") or 1)
    volume = float(trade.get("volume") or 1)
    if trade.get("direction") == "short":
        mfe = (entry_price - float(holding["low"].min())) * multiplier * volume
        mae = (entry_price - float(holding["high"].max())) * multiplier * volume
    else:
        mfe = (float(holding["high"].max()) - entry_price) * multiplier * volume
        mae = (float(holding["low"].min()) - entry_price) * multiplier * volume
    return round_float(mfe), round_float(mae)


def expected_bar_distance(indicator_frame: pd.DataFrame, open_time: datetime | None, close_time: datetime | None) -> int | str:
    open_index = index_for_time(indicator_frame, open_time)
    close_index = index_for_time(indicator_frame, close_time)
    if open_index is None or close_index is None:
        return ""
    return close_index - open_index


def trade_holding_trading_days(trade: dict[str, Any], expected_holding_bars: int | str) -> int | str:
    for key in ("holding_trading_days", "holding_bars", "hold_bars"):
        value = trade.get(key)
        if value not in (None, ""):
            parsed = int(float(value))
            if parsed > 0:
                return parsed
    return expected_holding_bars


def resolved_holding_bars(persisted_holding_bars: int, expected_holding_bars: int | str) -> int | str:
    if persisted_holding_bars > 0:
        return persisted_holding_bars
    return expected_holding_bars


def index_for_time(indicator_frame: pd.DataFrame, value: datetime | None) -> int | None:
    if value is None:
        return None
    matches = indicator_frame.index[indicator_frame["datetime"] == value].tolist()
    return int(matches[0]) if matches else None


def value_from_bar(bar: pd.Series | None, key: str) -> Any:
    if bar is None:
        return ""
    value = bar.get(key)
    return round_float(value) if isinstance(value, float) else value


def value_from_bar_or_raw(bar: pd.Series | None, trade: dict[str, Any], key: str, raw_key: str | None = None) -> Any:
    value = value_from_bar(bar, key)
    if value != "":
        return value
    raw = trade.get("raw_payload") or {}
    return raw.get(raw_key or key, "")


def calendar_days(open_time: datetime | None, close_time: datetime | None) -> int | str:
    if open_time is None or close_time is None:
        return ""
    return (close_time.date() - open_time.date()).days


def parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, pd.Timestamp):
        parsed = value.to_pydatetime()
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def normalize_dt(value: Any) -> datetime | None:
    return parse_dt(value)


def iso_or_blank(value: Any) -> str:
    parsed = parse_dt(value)
    return "" if parsed is None else parsed.isoformat()


def contract_from_bar(bar: pd.Series) -> str:
    value = bar.get("source_symbol") or bar.get("contract") or ""
    return str(value).upper()


def round_float(value: Any) -> Any:
    if value is None or value == "" or pd.isna(value):
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, 10)
    try:
        return round(float(value), 10)
    except (TypeError, ValueError):
        return value


def count_condition(frame: pd.DataFrame, column: str, value: str) -> int:
    if frame.empty or column not in frame:
        return 0
    return int((frame[column] == value).sum())


def count_true(frame: pd.DataFrame, column: str) -> int:
    if frame.empty or column not in frame:
        return 0
    return int(frame[column].fillna(False).astype(bool).sum())


def count_cross_inside_band(frame: pd.DataFrame, cross: str, band: str) -> int:
    if frame.empty:
        return 0
    return int(((frame["macd_cross_type"] == cross) & frame[band].fillna(False).astype(bool)).sum())


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    frame = pd.DataFrame(rows, columns=fields)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    raise SystemExit(main())
