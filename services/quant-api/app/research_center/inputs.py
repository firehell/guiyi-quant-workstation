"""Qualify evidence from the owning domains before dispatching research."""

from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.backtest_center.codec import digest
from app.backtest_center.experiments import ENVIRONMENT_FIELDS, evaluation_settlements
from app.backtest_center.store import RunStore
from app.backtest_center.worker import Settings


class ResearchError(ValueError):
    pass


def publication_identity(native):
    return digest({key: native[key] for key in ("run_id", "result_digest", "config", "snapshot")})


def published_runs(offset, limit, **filters):
    reader = RunStore.open_reader(Settings.local().path)
    page = reader.list(offset=offset, limit=limit, status="SUCCEEDED", **filters)
    items = []
    for run in page["items"]:
        config = run["config"]
        items.append({
            "run_id": run["run_id"], "product": config["product"], "contract": config["contract"],
            "strategy_id": config["strategy_id"], "formula_version": config["formula_version"],
            "frequency": config["signal_frequency"],
            "start": config["start"], "end": config["end"], "qualification": run["qualification"],
        })
    return {"items": items, "total": page["total"]}


def trade_summary(trades):
    counts = Counter(row["status"] for row in trades)
    closed = [Decimal(row["net_pnl"]) for row in trades if row["status"] == "CLOSED"]
    if any(not pnl.is_finite() for pnl in closed):
        raise ResearchError("TRADE_PNL_INVALID")
    wins = [pnl for pnl in closed if pnl > 0]
    losses = [-pnl for pnl in closed if pnl < 0]
    return {
        "closed": len(closed), "wins": len(wins), "losses": len(losses),
        "breakeven": len(closed) - len(wins) - len(losses),
        "other_statuses": {status: count for status, count in counts.items() if status != "CLOSED"},
        "win_rate": str(Decimal(len(wins)) / len(closed)) if closed else None,
        "profit_factor": str(sum(wins) / sum(losses)) if losses else None,
        "net_closed_pnl": str(sum(closed)),
    }


def group_closed_trades(trades, fills):
    opens = {str(fill["native_trade_id"]): fill for fill in fills if fill.get("position_effect") == "OPEN"}
    buckets = defaultdict(list)
    for trade in trades:
        if trade["status"] != "CLOSED":
            continue
        fill = opens.get(str(trade.get("native_entry_id")))
        local_hour = None
        if fill and fill.get("contract") == trade.get("contract"):
            at = datetime.fromisoformat(fill["modeled_fill_at"])
            if at.utcoffset() is not None:
                local_hour = at.astimezone(ZoneInfo("Asia/Shanghai")).hour
        # Keep time-of-day buckets explicit. The archive lacks a frozen exchange session id.
        time_band = "UNKNOWN" if local_hour is None else "18–06" if local_hour >= 18 or local_hour < 6 else "06–18"
        direction = trade["direction"]
        group = f"{direction}:{time_band}"
        buckets[group].append({
            **{name: trade.get(name) for name in ("trade_id", "entry_at", "exit_at", "direction", "quantity",
                                                  "entry_price", "exit_price", "net_pnl", "fees")},
            "record_type": "trade", "group": group,
        })
    groups = [
        {"group": group, **trade_summary([{**row, "status": "CLOSED"} for row in rows])}
        for group, rows in sorted(buckets.items())
    ]
    return groups, [row for rows in buckets.values() for row in rows]


def backtest_input(publication):
    c, s, report, summary = (publication[key] for key in ("config", "snapshot", "report", "summary"))
    if (
        s.get("engine", {}).get("name") != "rqalpha-plus"
        or report.get("native_analysis_source") != "rqalpha-plus/sys_analyser"
        or c.get("contract_selection") != "physical"
        or not c.get("contract") or c["contract"] != s.get("physical_contract")
        or c["contract"] != summary.get("contract") or s.get("qualification") != summary.get("qualification")
        or summary.get("currency") != "CNY"
    ):
        raise ResearchError("VERIFIED_PHYSICAL_RUN_REQUIRED")

    trade_stats = trade_summary(publication["trades"])
    groups, trade_rows = group_closed_trades(publication["trades"], report.get("native_fills", []))
    days = report.get("evaluation_trading_days", [])
    try:
        if report["benchmark"] != "cash":
            raise ResearchError("CASH_FLOW_OR_INITIAL_EQUITY_UNPROVEN")
        rows = evaluation_settlements(publication, publication)
        if any(Decimal(row["equity"]) <= 0 for row in rows):
            raise ResearchError("SETTLEMENT_EQUITY_INVALID")
        reason = None
    except ValueError as exc:
        rows, reason = [], str(exc) if str(exc).isidentifier() else "SETTLEMENT_EVIDENCE_UNAVAILABLE"
    except (KeyError, TypeError, ArithmeticError):
        rows, reason = [], "SETTLEMENT_EVIDENCE_UNAVAILABLE"
    return {
        "source": {"kind": "backtest", "run_id": publication["run_id"], "digest": publication["result_digest"],
                   "publication_identity": publication_identity(publication),
                   "code_revision": s.get("code_revision"), "data_revision": s.get("data_revision"),
                   "qualification": s["qualification"], "contract": c["contract"],
                   "product": c["product"], "strategy_id": c["strategy_id"], "formula_version": c["formula_version"],
                   "profile_id": c["profile_id"], "frequency": c["signal_frequency"], "cost_basis": summary["cost_basis"],
                   "cost_revision": s.get("cost_rows_sha256"), "currency": summary["currency"],
                   "start": c["start"], "end": c["end"]},
        "policy": {"version": "plus_cash_evaluation_v1", "initial_equity": c["initial_capital"],
                   "benchmark": "cash", "annual_periods": 252, "annual_risk_free_rate": 0,
                   "external_cash_flow": 0, "scope": "evaluation_trading_days"},
        "coverage": {"expected_days": len(days), "settlement_days": len(rows), "reason": reason},
        "comparison_identity": {
            **{field: s.get(field) for field in ENVIRONMENT_FIELDS},
            **{field: c.get(field) for field in ("commission_multiplier", "slippage_ticks", "execution_frequency",
                                                "warmup_start", "rollover_policy")},
            **{field: s.get(field) for field in ("contract_multiplier", "tick_size", "execution_delay_minutes")},
        },
        "native": report.get("native_analysis", {}),
        "native_scope": report.get("native_analysis_scope"),
        "trades": trade_stats,
        "groups": groups,
        "group_policy": {"admission": "closed_trades_by_direction_and_china_time_band",
                         "market_state": "FROZEN_REGIME_EVIDENCE_UNAVAILABLE",
                         "confidence_interval": "DESCRIPTIVE_ONLY"},
        "samples": [{**row, "record_type": "settlement"} for row in rows] + trade_rows,
    }


def comparison_differences(left, right):
    differences = []
    for section, keys in (
        ("source", ("currency", "cost_basis", "cost_revision", "start", "end", "product", "contract",
                    "frequency", "qualification", "data_revision")),
        ("policy", ("version", "scope", "benchmark", "annual_periods", "annual_risk_free_rate",
                    "external_cash_flow", "initial_equity")),
        ("comparison_identity", set(left["comparison_identity"]) | set(right["comparison_identity"])),
    ):
        differences.extend(key for key in keys if left[section].get(key) is None
                           or left[section].get(key) != right[section].get(key))
    if not left.get("performance") or not right.get("performance"):
        differences.append("settlement_coverage")
    return sorted(set(differences))
