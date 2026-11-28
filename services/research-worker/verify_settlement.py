"""Compare an exported RQAlpha Plus Run with independent arithmetic and QuantStats."""

import argparse
from decimal import Decimal, localcontext
from hashlib import sha256
import json
from math import isclose, sqrt
from pathlib import Path
from statistics import mean, stdev

from performance import calculate, daily_returns


def require(condition, message):
    if not condition:
        raise ValueError(message)


def manual_statistics(initial, settlements, *, periods):
    with localcontext() as context:
        context.prec = 40
        balances = [initial, *settlements.values()]
        returns = [after / before - 1 for before, after in zip(balances, balances[1:])]
        peak, peak_index = initial, 0
        dd, valley_index, valley_peak = Decimal(0), 0, 0
        monthly = {}
        for i, (day, balance, change) in enumerate(zip(settlements, balances[1:], returns), start=1):
            monthly[day[:7]] = monthly.get(day[:7], Decimal(1)) * (1 + change)
            if balance >= peak:
                peak, peak_index = balance, i
            depth = 1 - balance / peak
            if depth > dd:
                dd, valley_index, valley_peak = depth, i, peak_index
        recovery = next((i for i in range(valley_index + 1, len(balances))
                         if balances[i] >= balances[valley_peak]), None)
        samples = [float(value) for value in returns]
        dispersion = stdev(samples)
        downside = sqrt(sum(min(0, value) ** 2 for value in samples) / len(samples))
        annual = (balances[-1] / initial) ** (Decimal(periods) / len(samples)) - 1
        return {
            "cumulative": float(balances[-1] / initial - 1),
            "annualized": float(annual),
            "max_drawdown": float(dd),
            "drawdown_span": {"trading_days": (recovery or len(samples)) - valley_peak if dd else 0,
                              "ongoing": bool(dd) and recovery is None},
            "daily_win_rate": sum(value > 0 for value in returns) / len(returns),
            "monthly": {month: float(growth - 1) for month, growth in monthly.items()},
            "sharpe": mean(samples) / dispersion * sqrt(periods) if dispersion else None,
            "sortino": mean(samples) / downside * sqrt(periods) if downside else None,
            "calmar": float(annual / dd) if dd else None,
        }


def verify(publication, *, expected_result_digest):
    config, snapshot, report = (publication[key] for key in ("config", "snapshot", "report"))
    result = {key: publication[key] for key in ("summary", "report", "trades", "equity", "bars", "markers")}
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    require(sha256(encoded.encode()).hexdigest() == publication["result_digest"] == expected_result_digest,
            "PUBLICATION_DIGEST_MISMATCH")
    summary = publication["summary"]
    require(config["contract_selection"] == "physical" and config["sample_type"] == "historical"
            and snapshot["engine"]["name"] == "rqalpha-plus"
            and config["contract"] == snapshot["physical_contract"] == summary["contract"]
            and snapshot["qualification"] == summary["qualification"]
            and report["native_analysis_source"] == "rqalpha-plus/sys_analyser"
            and report["native_analysis_scope"] == "configured_warmup_and_evaluation"
            and report["benchmark"] == "cash"
            and report["evaluation_initial_position"] == "FLAT", "NATIVE_RUN_REQUIRED")
    initial = Decimal(report["evaluation_initial_equity"])
    require(initial == Decimal(config["initial_capital"]), "INITIAL_CAPITAL_MISMATCH")
    raw = report["native_settlements"]
    full_days = [row["trading_day"] for row in raw]
    official = {row["trading_day"]: Decimal(row["after"]["native_equity"]["repr"]) for row in raw}
    days = report["evaluation_trading_days"]
    warm_days = full_days[:-len(days)]
    require(len(days) >= 2 and days == snapshot["evaluation_trading_days"]
            and days[0] == config["start"] and days[-1] == config["end"]
            and full_days[0] == config["warmup_start"]
            and full_days == sorted(set(full_days)) and full_days[-len(days):] == days
            and all(official[day] == initial for day in warm_days), "NATIVE_WINDOW_MISMATCH")
    projected_rows = publication["equity"]
    require([row["trading_day"] for row in projected_rows] == days, "EQUITY_COVERAGE_MISMATCH")
    projected = {row["trading_day"]: Decimal(row["equity"]) for row in projected_rows}
    binary_tolerance = Decimal(report["account_binary_tolerance_cny"])
    error = max(abs(official[day] - projected[day]) for day in days)
    require(error <= binary_tolerance, "NATIVE_SETTLEMENT_EQUITY_MISMATCH")

    # The frozen Plus historical Run has fixed capital and no external transfers.
    period_count = 252
    comparison = {}
    for scope, source in (("evaluation", projected), ("native_with_warmup", official)):
        hand = manual_statistics(initial, source, periods=period_count)
        qs = calculate(daily_returns(list(source), source, initial, external_cash_flow=0), periods=period_count)
        for key, expected in hand.items():
            actual = qs[key]
            if isinstance(expected, float):
                require(isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-10), f"PARITY_MISMATCH:{scope}:{key}")
            elif key == "monthly":
                require(actual.keys() == expected.keys() and all(
                    isclose(actual[month], value, rel_tol=1e-9, abs_tol=1e-10)
                    for month, value in expected.items()), f"PARITY_MISMATCH:{scope}:{key}")
            else:
                require(actual == expected, f"PARITY_MISMATCH:{scope}:{key}")
        comparison[scope] = {"manual": hand, "quantstats": qs}
    native = report["native_analysis"]
    full = comparison["native_with_warmup"]["quantstats"]
    for original, derived in (("total_returns", "cumulative"), ("annualized_returns", "annualized"),
                              ("max_drawdown", "max_drawdown")):
        require(isclose(float(native[original]), full[derived], rel_tol=1e-9, abs_tol=1e-10),
                f"PLUS_METRIC_MISMATCH:{original}")
    require(abs(Decimal(native["total_value"]) - official[days[-1]]) <= binary_tolerance,
            "PLUS_FINAL_VALUE_MISMATCH")

    trades = publication["trades"]
    closed = [Decimal(row["net_pnl"]) for row in trades if row["status"] == "CLOSED"]
    opened = [row for row in trades if row["status"] == "OPEN"]
    require(len(opened) == 1 and opened[0] == report["terminal_position"], "TERMINAL_POSITION_MISMATCH")
    terminal = opened[0]
    require(initial + sum(closed) + Decimal(terminal["unrealized_pnl"]) - Decimal(terminal["fees"])
            == projected[days[-1]], "TRADE_SETTLEMENT_RECONCILIATION_MISMATCH")
    metrics = publication["summary"]["metrics"]
    require(len(closed) == metrics["trade_count"]["value"]
            and isclose(sum(value > 0 for value in closed) / len(closed), float(metrics["win_rate"]["value"])),
            "CLOSED_TRADE_METRIC_MISMATCH")
    return {
        "run_id": publication["run_id"], "result_digest": publication["result_digest"],
        "data_revision": snapshot["data_revision"], "code_revision": snapshot["code_revision"],
        "contract": config["contract"], "qualification": snapshot["qualification"],
        "dates": [days[0], days[-1]], "warmup_sessions": len(warm_days),
        "native": native, "max_native_settlement_difference_cny": str(error), "comparison": comparison,
        "closed_trade_count": len(closed), "closed_trade_win_rate": sum(value > 0 for value in closed) / len(closed),
        "open_unrealized_cny": terminal["unrealized_pnl"], "open_fee_cny": terminal["fees"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("publication", type=Path)
    parser.add_argument("--expected-publication-sha256", required=True)
    args = parser.parse_args()
    payload = args.publication.read_bytes()
    require(sha256(payload).hexdigest() == args.expected_publication_sha256, "PUBLICATION_FILE_DIGEST_MISMATCH")
    publication = json.loads(payload)
    print(json.dumps(verify(publication, expected_result_digest=publication["result_digest"]),
                     indent=2, allow_nan=False))
