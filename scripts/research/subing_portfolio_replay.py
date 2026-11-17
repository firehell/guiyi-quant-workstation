"""Replay one shared SuBing account from authority-bound historical inputs."""

import argparse
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.readonly import readonly_transaction
from app.db.url import normalize_database_url
from app.market_data.actual_dominant_research import ActualDominantResearchSegmentLoader
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import BarFrequency, ContractTradingDayQuery
from app.market_data.market_data_service import MarketDataService
from app.market_data.new_subing_research import (
    NewSubingInputError,
    payload_hash,
    validate_series,
)
from app.market_data.storage import CanonicalMonthlyStore
from app.private_settings import load_private_readonly_settings
from guiyi_quant.indicators.subing_trend import initial_state, step
from guiyi_quant.subing_decision import _wire
from guiyi_quant.subing_one_lot import EXPANDED_PORTFOLIO_PRODUCTS, PORTFOLIO_PRODUCTS
from guiyi_quant.subing_one_lot.portfolio import Segment, replay
from scripts.research.subing_account import load
from scripts.research.subing_one_lot_stress import build_context, dump, hashes
from scripts.research.subing_trend import load as load_factors


def prepare_segment(market, product, contract, days, schedule, facts):
    since, through = map(date.fromisoformat, (days[0], days[-1]))
    segments, evidence = load(
        market,
        facts,
        since,
        through,
        product=product,
        include_range=True,
        portfolio=True,
    )
    (segment,) = segments
    if segment["contract"] != contract:
        raise ValueError("PORTFOLIO_RANK1_MISMATCH")
    xs = segment["executions"]
    factors = load_factors(
        market,
        since,
        through,
        product=product,
        include_joint=True,
        include_range=True,
        portfolio=True,
    )
    if factors["input_hash"] != evidence["factors_input_hash"]:
        raise ValueError("PORTFOLIO_FACTOR_SOURCE_CHANGED")
    cutoff = xs[-1].bar.bar_end
    expected = market.expected_contract_replay_endpoints(
        symbol=product,
        contract=contract,
        frequency=BarFrequency.H1,
        trading_day=through,
        cutoff=cutoff,
    )
    if not expected:
        raise NewSubingInputError("HOURLY_INPUT_EMPTY")
    series = market.query_contract_trading_days(
        ContractTradingDayQuery(
            product, contract, BarFrequency.H1, expected[0][1], through
        )
    )
    validate_series(
        series,
        product=product,
        contract=contract,
        frequency=BarFrequency.H1,
        expected=expected,
    )
    hourly = {}
    state = initial_state(contract, "60m")
    for bar in series.bars:
        state, point = step(
            state,
            contract=contract,
            frequency="60m",
            bar_end=bar.bar_end,
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
        )
        hourly[bar.bar_end] = dict(
            at=bar.bar_end.isoformat(), direction=point.direction
        )
    structures = build_context(factors["rows"], xs, contract, hourly)
    return Segment(
        product, tuple(xs), segment["observations"], structures, schedule
    ), evidence, [
        {**{key: row[key] for key in ("open", "high", "low", "close", "ema21")},
         "at": row["time"], "contract": contract, **{
             key: structures.get(row["time"], {}).get(key) for key in ("lower", "upper")
         }}
        for row in factors["rows"]
        if row["contract"] == contract and row["frequency"] == "30m" and
        xs[0].bar.bar_end <= datetime.fromisoformat(row["time"]) <= cutoff
    ]


def verify_schedule(market, product, item, since, through):
    calendar = market.catalog.calendar_days(product, since, through)
    if len(calendar) != (through - since).days + 1 or sorted(item["schedule"]) != [
        str(d) for d, is_open in calendar if is_open
    ]:
        raise ValueError("PORTFOLIO_CALENDAR_INCOMPLETE")
    for day, row in item["schedule"].items():
        trading_day = date.fromisoformat(day)
        windows = market.session_windows(symbol=product, trading_day=trading_day)
        previous = date.fromisoformat(row["previous"])
        opening = datetime.fromisoformat(row["next_open"])
        candidates = market.catalog.calendar_days(product, previous, opening.date())
        earlier = [d for d, is_open in candidates if is_open and d < trading_day]
        # Night trading can open on the preceding civil date.
        candidates = market.catalog.calendar_days(
            product, trading_day, max(trading_day, opening.date()) + timedelta(days=7)
        )
        later = [d for d, is_open in candidates if is_open and d > trading_day]
        future = (
            market.session_windows(symbol=product, trading_day=later[0])
            if later
            else ()
        )
        if (
            not earlier
            or earlier[-1] != previous
            or not future
            or opening != min(w.start for w in future)
            or datetime.fromisoformat(row["first_open"])
            != min(w.start for w in windows)
            or datetime.fromisoformat(row["day_end"]) != max(w.end for w in windows)
            or datetime.fromisoformat(row["day_end"]) > datetime.now(UTC)
        ):
            raise ValueError("PORTFOLIO_SESSION_PLAN_CHANGED")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("PORTFOLIO_OUTPUT_EXISTS")
    plan = json.loads((args.facts_dir / "plan.json").read_text())
    since, through = map(date.fromisoformat, plan["dates"])
    products = next((scope for scope in (PORTFOLIO_PRODUCTS, EXPANDED_PORTFOLIO_PRODUCTS)
                     if set(plan["products"]) == set(scope)), None)
    if products is None:
        raise ValueError("PORTFOLIO_PLAN_SCOPE_INVALID")
    settings, _ = load_private_readonly_settings(
        Path.home() / "Library/Application Support/GuiyiQuant/project.env"
    )
    root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
    engine = create_engine(
        normalize_database_url(settings["DATABASE_URL"]),
        connect_args={"connect_timeout": 5},
    )
    segments, coverage, charts, timeline = [], [], {}, []
    runner_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    source_hashes = hashes()
    fact_hashes = {}
    try:
        for product in products:
            item = plan["products"][product]
            path = args.facts_dir / f"{product}-facts.json"
            raw = path.read_bytes() if path.is_file() else b""
            facts = json.loads(raw) if raw else {}
            fact_hashes[product] = hashlib.sha256(raw).hexdigest() if raw else None
            if facts and (
                facts.get("plan_hash") != payload_hash(plan)
                or facts.get("time_semantics") != "retrospective_execution_facts"
            ):
                raise ValueError("PORTFOLIO_DATED_FACTS_REQUIRED")
            with (
                Session(engine, autoflush=False) as db,
                readonly_transaction(db, timeout_seconds=90),
            ):
                market = MarketDataService(
                    MarketCatalog(db, root), CanonicalMonthlyStore(root)
                )
                verify_schedule(market, product, item, since, through)
                owners = ActualDominantResearchSegmentLoader(market).owner_segments(
                    symbol=product, since=since, through=through
                )
                expected = {
                    owner.contract: [
                        d
                        for d in item["schedule"]
                        if owner.start_trading_day
                        <= date.fromisoformat(d)
                        <= owner.end_trading_day
                    ]
                    for owner in owners
                }
                if expected != item["blocks"] or sorted(
                    d for days in expected.values() for d in days
                ) != sorted(item["schedule"]):
                    raise ValueError("PORTFOLIO_OWNER_PLAN_CHANGED")
                for contract, days in expected.items():
                    row = dict(product=product, contract=contract, days=days)
                    schedule = {d: item["schedule"][d] for d in days}
                    try:
                        segment, evidence, chart = prepare_segment(
                            market, product, contract, days, schedule, facts
                        )
                    except NewSubingInputError as exc:
                        row.update(status=exc.code, diagnostic=exc.diagnostic)
                    else:
                        segments.append(segment)
                        charts.setdefault(product, []).extend(chart)
                        row.update(
                            status="VERIFIED",
                            minutes=len(segment.executions),
                            evidence=evidence,
                        )
                    coverage.append(row)
                    print(
                        product,
                        contract,
                        row["status"],
                        row.get("minutes", ""),
                        flush=True,
                    )
    finally:
        engine.dispose()
    if not segments:
        raise ValueError("PORTFOLIO_NO_VERIFIED_SEGMENTS")
    if products == EXPANDED_PORTFOLIO_PRODUCTS and any(row["status"] != "VERIFIED" for row in coverage):
        raise ValueError("PORTFOLIO_EXPANDED_FACTS_INCOMPLETE")
    def record(portfolio):
        marks = {}
        relevant = set(portfolio.active_contracts.values()) | portfolio.exit_owed | portfolio.unproven_marks
        for contract in sorted(relevant):
            account = portfolio.accounts[contract]
            latest = account.model.chain[-1]
            marks[contract] = {
                "contract": contract, "quantity": len(account.layers),
                "layers": list(account.layers.values()), "pending": account.model.pending,
                "decision": {key: latest.get(key) for key in ("at", "demand", "reason", "next_wait")},
                "stop": account.model.state().get("initial_stop"),
                "target": account.model.state().get("profit_target"),
            }
        timeline.append(_wire(dict(
            at=portfolio.last_at, day=str(portfolio.day), accounts=marks,
            daily=portfolio.daily[str(portfolio.day)],
            pending_exit_contracts=sorted(portfolio.exit_owed),
            valuation_unproven=sorted(portfolio.unproven_marks),
        )))

    result = replay(segments, f"subing-portfolio-replay:{since}:{through}",
                    products=products, on_batch=record)
    if (
        source_hashes != hashes()
        or runner_hash != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    ):
        raise ValueError("PORTFOLIO_CODE_CHANGED")
    dump(
        args.output,
        dict(
            requested=plan["dates"],
            code_hashes=source_hashes,
            runner_sha256=runner_hash,
            plan_hash=payload_hash(plan),
            execution_facts_sha256=fact_hashes,
            coverage=coverage,
            result=result,
            timeline=timeline,
            charts=charts,
        ),
    )


if __name__ == "__main__":
    main()
