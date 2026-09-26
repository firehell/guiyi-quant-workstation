#!/usr/bin/env python3
"""Bounded, read-only four-period MDS probe; never treats one day as history readiness."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from time import monotonic

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.readonly import readonly_transaction
from app.db.session import SessionLocal
from app.market_data.composition import build_market_data_service, canonical_root
from app.market_data.domain import ActualDominantTradingDayQuery, BarFrequency
from app.market_data.market_data_service import MarketDataError
from app.market_data.operational_universe import load_operational_products
from app.core.env import PROJECT_ROOT


PERIODS = (BarFrequency.M1, BarFrequency.M15, BarFrequency.M30, BarFrequency.H1)
STRATEGIES = ("trend", "oscillation", "main_rise")


def audit(*, since: date, day: date, timeout_seconds: int) -> dict:
    audit_started_at = datetime.now(UTC).isoformat()
    deadline = monotonic() + timeout_seconds
    products = load_operational_products()
    if len(products) != 60:
        raise ValueError("OPERATIONAL_60_REQUIRED")
    rows: list[dict] = []
    with SessionLocal() as session, readonly_transaction(
        session, timeout_seconds=timeout_seconds,
    ):
        database = session.execute(text("SELECT current_database()")).scalar_one()
        schema = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        snapshot_at = session.execute(text("SELECT transaction_timestamp()")).scalar_one().isoformat()
        market = build_market_data_service(session)
        for product in products:
            for period in PERIODS:
                row = {"product": product, "frequency": period.value,
                       "probe_window": [since.isoformat(), day.isoformat()], "status": "NOT_EVALUATED",
                       "bar_count": None, "first_bar_end": None, "last_bar_end": None,
                       "reason": None}
                if monotonic() >= deadline:
                    row.update(reason="AUDIT_BUDGET_EXHAUSTED")
                    rows.append(row)
                    continue
                try:
                    result = market.query_actual_dominant_trading_days(
                        ActualDominantTradingDayQuery(product, period, since, day)
                    )
                    bars = result.bars
                    row.update(status="WINDOW_READABLE", bar_count=len(bars),
                               first_bar_end=bars[0].bar_end.isoformat() if bars else None,
                               last_bar_end=bars[-1].bar_end.isoformat() if bars else None)
                except MarketDataError as exc:
                    row.update(status="BLOCKED", reason=exc.code)
                except SQLAlchemyError:
                    raise
                except Exception:
                    row.update(status="UNVERIFIED", reason="READ_FAILED")
                rows.append(row)
    by_key = {(row["product"], row["frequency"]): row for row in rows}
    for row in rows:
        source = by_key[row["product"], "1m"]
        row["source_1m_window_status"] = source["status"]
        row["source_1m_window_reason"] = source["reason"]
        row["physical_contract_full_prefix_status"] = "NOT_EVALUATED"
        row["warmup_status"] = "NOT_EVALUATED"
        row["product_capability"] = "UNSUPPORTED_OR_CLOSED"
        row["formal_open"] = False
        row["runtime_status"] = "NOT_EVALUATED"
    strategy_rows = [
        {"product": row["product"], "frequency": row["frequency"],
         "strategy": strategy, "calculation": "NOT_EVALUATED",
         "page": "UNSUPPORTED_OR_CLOSED", "formal_open": False}
        for row in rows for strategy in STRATEGIES
    ]
    return {"schema_version": 1, "readonly": True, "probe_scope": "bounded_trading_day_window",
            "full_history_proven": False, "database": database, "alembic": schema,
            "code_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "audit_script_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "operational_universe_sha256": sha256(
                (PROJECT_ROOT / "data/universe/operational_products.txt").read_bytes()
            ).hexdigest(),
            "audit_started_at_utc": audit_started_at, "database_snapshot_at": snapshot_at,
            "canonical_root": str(canonical_root()), "window": {"since": since.isoformat(), "through": day.isoformat()},
            "denominator": {"product_period": 240, "product_period_strategy": 720},
            "rows": rows, "strategy_rows": strategy_rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", type=date.fromisoformat, required=True)
    parser.add_argument("--trading-day", type=date.fromisoformat, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.timeout_seconds <= 300 or args.since > args.trading_day:
        parser.error("timeout out of range")
    body = audit(since=args.since, day=args.trading_day, timeout_seconds=args.timeout_seconds)
    if args.output.exists() or not args.output.parent.is_dir():
        parser.error("output must be new and parent must exist")
    args.output.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n")
    counts: dict[str, int] = {}
    for row in body["rows"]:
        key = f'{row["status"]}:{row["reason"] or "none"}'
        counts[key] = counts.get(key, 0) + 1
    print(json.dumps({"output": str(args.output), "counts": counts}, sort_keys=True))


if __name__ == "__main__":
    main()
