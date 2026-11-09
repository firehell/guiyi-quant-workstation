"""Fixed-input JM development stress; no provider, Runtime or account writes.

prepare reads MDS once and saves hash-bound inputs; run consumes one immutable
physical segment/scenario. All nine fee/slippage combinations are predefined.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
import gzip
import hashlib
import json
import os
from pathlib import Path
import re

from guiyi_quant.subing_decision import REGIME_PROFILE, _digest, _wire
from guiyi_quant.subing_demand_account_candidate import build_engine as build_control
from guiyi_quant.subing_one_lot import POLICY, build_engine as build_one_lot

ROOT = Path(__file__).resolve().parents[2]
SINCE = date(2024, 10, 14)
THROUGH = date(2026, 10, 19)
FEES = (
    "open_rate",
    "open_per_contract",
    "close_rate",
    "close_per_contract",
    "close_today_rate",
    "close_today_per_contract",
)
SCENARIOS = [(fee, slip) for fee in (1, 2, 3) for slip in (1, 2, 3)]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value, *, compressed=False):
    if path.exists():
        raise ValueError("OUTPUT_ALREADY_EXISTS")
    raw = json.dumps(
        _wire(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("xb") as stream:
        stream.write(
            gzip.compress(raw, compresslevel=3, mtime=0) if compressed else raw
        )
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def hashes():
    core = ROOT / "packages/quant-core/guiyi_quant"
    paths = [
        *core.glob("subing*.py"),
        *core.glob("subing_one_lot/*.py"),
        *core.glob("indicators/*.py"),
        *core.glob("paper/*.py"),
        *core.glob("new_subing/*.py"),
        ROOT / "scripts/research/subing_account.py",
        ROOT / "scripts/research/subing_trend.py",
        ROOT / "services/quant-api/app/subing_model/account.py",
        Path(__file__),
    ]
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}


def session_eligibility(locked_at, now, windows):
    if locked_at.utcoffset() is None or now.utcoffset() is None:
        raise ValueError("NAIVE_TIME")
    rows = []
    for day, periods in sorted(windows.items()):
        if not periods:
            raise ValueError("SESSION_MISSING")
        first, last = min(w[0] for w in periods), max(w[1] for w in periods)
        rows.append(
            dict(
                trading_day=str(day),
                first_session=first.isoformat(),
                last_session=last.isoformat(),
                entire_day_after_lock=first > locked_at,
                completed=last <= now,
                temporally_eligible=first > locked_at and last <= now,
            )
        )
    return rows


def open_calendar_days(metadata):
    # MDS rows also contain has_night_session/provider/remark. Consume the
    # documented date and trading-day fields without assuming two columns.
    return [date.fromisoformat(row[0]) for row in metadata["calendar"] if row[1]]


def oos_preflight(market, locked_at, now):
    """Report missing lookahead days; only prove individually registered days.

    This is not a shortened successful backtest. Missing dates stay UNKNOWN;
    no market replay is run even when a day has temporal eligibility.
    """
    from app.market_data.market_data_service import MarketDataError
    from zoneinfo import ZoneInfo

    start = locked_at.astimezone(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=3)
    end = start + timedelta(days=14)
    rows = market.catalog.calendar_days("jm", start, end)
    available = {d for d, _ in rows}
    missing = [
        str(start + timedelta(days=i))
        for i in range((end - start).days + 1)
        if start + timedelta(days=i) not in available
    ]
    full = None
    try:
        full = market.historical_metadata_evidence(
            symbol="jm", since=start, through=end
        )
    except MarketDataError as exc:
        if exc.code != "HISTORICAL_METADATA_EVIDENCE_MISSING":
            raise
        if not missing:
            raise
    windows = {}
    day_hashes = {}
    day_failures = []
    for day, opened in rows:
        if not opened:
            continue
        try:
            meta = market.historical_metadata_evidence(
                symbol="jm", since=day, through=day
            )
            periods = [
                (w.start, w.end)
                for w in market.session_windows(symbol="jm", trading_day=day)
            ]
            if meta != market.historical_metadata_evidence(
                symbol="jm", since=day, through=day
            ):
                raise ValueError("OOS_METADATA_CHANGED")
        except MarketDataError as exc:
            day_failures.append(
                dict(trading_day=str(day), status="UNKNOWN", error_code=exc.code)
            )
            continue
        windows[day] = periods
        day_hashes[str(day)] = _digest(meta)
    if rows != market.catalog.calendar_days("jm", start, end):
        raise ValueError("OOS_CALENDAR_CHANGED")
    return dict(
        status="PREFLIGHT_ONLY_NOT_RUN",
        observed_at=now.isoformat(),
        requested_since=str(start),
        requested_through=str(end),
        requested_window_complete=full is not None,
        missing_calendar_days=missing,
        individual_day_failures=day_failures,
        eligibility=session_eligibility(locked_at, now, windows),
        individual_day_metadata_hashes=day_hashes,
        metadata_hash=_digest(full) if full else None,
        execution_and_market_facts="NOT_VALIDATED_IN_THIS_TEMPORAL_PREFLIGHT",
    )


def build_context(rows, executions, contract, hourly):
    from guiyi_quant.subing_recent_structure import State, Bar, step

    state = State(contract)
    points = {}
    for r in rows:
        if r["contract"] != contract or r["frequency"] != "30m":
            continue
        at = datetime.fromisoformat(r["time"])
        state, point = step(
            state,
            Bar(at, *(D(str(r[k])) for k in ("high", "low", "close"))),
            contract=contract,
        )
        points[at] = dict(_wire(point), base_regime=r["range_factor"]["regime"])
    first = executions[0].bar.bar_end
    previous = [v for k, v in points.items() if k < first]
    hours = [v for k, v in hourly.items() if k < first]
    current = previous[-1] if previous else None
    hour = hours[-1] if hours else None
    contexts = {}
    for x in executions:
        at = x.bar.bar_end
        current = points.get(at, current)
        hour = hourly.get(at, hour)
        contexts[at.isoformat()] = dict(current or {}, hourly=hour)
    return contexts


def prepare(output, locked_at):
    if output.exists():
        raise ValueError("OUTPUT_ALREADY_EXISTS")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.readonly import readonly_transaction
    from app.db.url import normalize_database_url
    from app.private_settings import load_private_readonly_settings
    from app.market_data.catalog import MarketCatalog
    from app.market_data.market_data_service import MarketDataService
    from app.market_data.storage import CanonicalMonthlyStore
    from app.market_data.domain import BarFrequency, ContractTradingDayQuery
    from app.market_data.new_subing_research import validate_series
    from guiyi_quant.indicators.subing_trend import initial_state, step
    from scripts.research.subing_account import load
    from scripts.research.subing_trend import load as load_factors

    code = hashes()
    facts_path = (
        ROOT
        / "output/newow-futures-bidir-v1-20261020-evidence/facts-attempt-001/jm.json"
    )
    raw = facts_path.read_bytes()
    settings, _ = load_private_readonly_settings(
        Path.home() / "Library/Application Support/GuiyiQuant/project.env"
    )
    engine = create_engine(
        normalize_database_url(settings["DATABASE_URL"]),
        connect_args={"connect_timeout": 5},
    )
    bundles = []
    now = datetime.now(timezone.utc)
    try:
        with (
            Session(engine, autoflush=False) as db,
            readonly_transaction(db, timeout_seconds=900),
        ):
            root = Path(settings["GUIYI_CANONICAL_DATA_ROOT"])
            market = MarketDataService(
                MarketCatalog(db, root), CanonicalMonthlyStore(root)
            )
            segments, evidence = load(
                market, json.loads(raw), SINCE, THROUGH, include_range=True
            )
            factors = load_factors(
                market, SINCE, THROUGH, include_joint=True, include_range=True
            )
            if factors["input_hash"] != evidence["factors_input_hash"]:
                raise ValueError("FACTOR_SOURCE_CHANGED")
            meta = market.historical_metadata_evidence(
                symbol="jm",
                since=SINCE - timedelta(days=14),
                through=THROUGH + timedelta(days=14),
            )
            days = open_calendar_days(meta)
            periods = {
                d: market.session_windows(symbol="jm", trading_day=d) for d in days
            }
            schedule = {
                str(d): dict(
                    previous=str(days[i - 1]),
                    first_open=min(w.start for w in periods[d]).isoformat(),
                    day_end=max(w.end for w in periods[d]).isoformat(),
                    next_open=min(w.start for w in periods[days[i + 1]]).isoformat(),
                )
                for i, d in enumerate(days)
                if SINCE <= d <= THROUGH
            }
            for i, s in enumerate(segments):
                xs = s["executions"]
                contract = s["contract"]
                cutoff = xs[-1].bar.bar_end
                before = market.contract_source_evidence(
                    symbol="jm",
                    contract=contract,
                    frequency=BarFrequency.H1,
                    before=cutoff,
                )
                expected = market.expected_contract_replay_endpoints(
                    symbol="jm",
                    contract=contract,
                    frequency=BarFrequency.H1,
                    trading_day=date.fromisoformat(s["through"]),
                    cutoff=cutoff,
                )
                if not expected:
                    raise ValueError("HOURLY_INPUT_EMPTY")
                series = market.query_contract_trading_days(
                    ContractTradingDayQuery(
                        "jm",
                        contract,
                        BarFrequency.H1,
                        expected[0][1],
                        date.fromisoformat(s["through"]),
                    )
                )
                validate_series(
                    series,
                    product="jm",
                    contract=contract,
                    frequency=BarFrequency.H1,
                    expected=expected,
                )
                state = initial_state(contract, "60m")
                hourly = {}
                for b in series.bars:
                    state, point = step(
                        state,
                        contract=contract,
                        frequency="60m",
                        bar_end=b.bar_end,
                        high=float(b.high),
                        low=float(b.low),
                        close=float(b.close),
                    )
                    hourly[b.bar_end] = dict(
                        at=b.bar_end.isoformat(), direction=point.direction
                    )
                if before != market.contract_source_evidence(
                    symbol="jm",
                    contract=contract,
                    frequency=BarFrequency.H1,
                    before=cutoff,
                ):
                    raise ValueError("HOURLY_SOURCE_CHANGED")
                bundles.append(
                    dict(
                        contract=contract,
                        since=s["since"],
                        through=s["through"],
                        boundary="ROLLOVER_INTERRUPTED"
                        if i < len(segments) - 1
                        else "WINDOW_ENDED",
                        executions=[_wire(asdict(x)) for x in xs],
                        observations=[s["observations"][x.bar.bar_end] for x in xs],
                        schedule={
                            str(x.bar.trading_day): schedule[str(x.bar.trading_day)]
                            for x in xs
                        },
                        structures=build_context(factors["rows"], xs, contract, hourly),
                        hourly_source=before,
                        source_evidence=evidence,
                        original_execution_facts_hash=s["facts_hash"],
                    )
                )
            if meta != market.historical_metadata_evidence(
                symbol="jm",
                since=SINCE - timedelta(days=14),
                through=THROUGH + timedelta(days=14),
            ):
                raise ValueError("METADATA_CHANGED")
            oos = oos_preflight(market, locked_at, now)
    finally:
        engine.dispose()
    if facts_path.read_bytes() != raw or hashes() != code:
        raise ValueError("PREPARE_SOURCE_CHANGED")
    output.mkdir(parents=True, exist_ok=False)
    prepared = {}
    for b in bundles:
        path = output / (b["contract"] + ".json.gz")
        dump(path, b, compressed=True)
        prepared[b["contract"]] = dict(
            file=path.name,
            sha256=sha(path),
            minutes=len(b["executions"]),
            since=b["since"],
            through=b["through"],
            boundary=b["boundary"],
        )
    dump(
        output / "index.json",
        dict(
            kind="SEEN_DEVELOPMENT_INPUTS_NOT_OOS",
            since=str(SINCE),
            through=str(THROUGH),
            original_facts_sha256=hashlib.sha256(raw).hexdigest(),
            code_hashes=code,
            policy=dict(POLICY),
            scenarios=SCENARIOS,
            variants=["capital_control", "one_lot"],
            prepared=prepared,
            locked_at=locked_at.isoformat(),
            oos=oos,
        ),
    )
    print(
        json.dumps(
            dict(
                status="PREPARED",
                segments=prepared,
                temporally_eligible_completed_days=sum(
                    r["temporally_eligible"] for r in oos["eligibility"]
                ),
            ),
            ensure_ascii=False,
        ),
        flush=True,
    )


def stressed(executions, fee):
    if type(fee) is not int or fee not in (1, 2, 3):
        raise ValueError("FEE_SCENARIO_INVALID")
    if fee == 1:
        return executions
    return [
        replace(
            x,
            facts=replace(
                x.facts,
                fees=replace(
                    x.facts.fees,
                    **{k: getattr(x.facts.fees, k) * fee for k in FEES},
                    source_id=x.facts.fees.source_id + f":research_fee_x{fee}",
                ),
            ),
        )
        for x in executions
    ]


def metrics(executions, result):
    """Independent per-minute cash/position reconstruction, no terminal close."""
    by_source = {}
    for f in result["fills"]:
        if f["bar_source"] in by_source or f["fill_at"] <= f["decision_at"]:
            raise ValueError("FILL_IDENTITY_OR_TIME_INVALID")
        by_source[f["bar_source"]] = f
    cash = D(result["initial_cash"])
    peak = cash
    last = cash
    day_start = cash
    day = None
    max_dd = D(0)
    dd_cash = D(0)
    dd_at = None
    max_day_loss = D(0)
    max_lots = 0
    layers = {}
    fees = D(0)
    gross = D(0)
    used = set()
    rebuilt_rounds = []
    round_start = None
    round_entry = None
    round_side = None
    round_fills = []
    for x in executions:
        b = x.bar
        if b.trading_day != day:
            day = b.trading_day
            day_start = last
        f = by_source.get(b.source_identity)
        if f:
            if (
                f["contract"] != b.physical_contract
                or f["trading_day"] != b.trading_day.isoformat()
            ):
                raise ValueError("FILL_PHYSICAL_IDENTITY_CONFLICT")
            used.add(f["fill_id"])
            price = D(f["price"])
            fee = D(f["fee"])
            realized = D(0)
            if f["action"] in ("OPEN", "ADD"):
                if f["quantity"] != 1:
                    raise ValueError("FILL_QUANTITY_INVALID")
                if not layers:
                    round_start = cash
                    round_entry = f["fill_at"]
                    round_side = f["side"]
                    round_fills = []
                expected = x.facts.fees.amount("open", price, x.facts.multiplier)
                layers[f["decision_id"]] = dict(
                    price=price, side=f["side"], day=b.trading_day, open_fee=fee
                )
            else:
                if f["action"] != "CLOSE" or f["quantity"] != len(f["layer_ids"]):
                    raise ValueError("FILL_QUANTITY_INVALID")
                expected = D(0)
                for key in f["layer_ids"]:
                    layer = layers.pop(key)
                    sign = 1 if layer["side"] == "LONG" else -1
                    realized += sign * (price - layer["price"]) * x.facts.multiplier
                    expected += x.facts.fees.amount(
                        "close_today" if layer["day"] == b.trading_day else "close",
                        price,
                        x.facts.multiplier,
                    )
            if fee != expected or realized != D(f["gross_realized"]):
                raise ValueError("FILL_ACCOUNTING_CONFLICT")
            cash += realized - fee
            fees += fee
            gross += realized
            round_fills.append(f["fill_id"])
            if not layers:
                if round_start is None:
                    raise ValueError("ROUND_ENTRY_MISSING")
                rebuilt_rounds.append(
                    dict(
                        side=round_side,
                        entry_at=round_entry,
                        exit_at=f["fill_at"],
                        net_pnl=cash - round_start,
                        fills=list(round_fills),
                    )
                )
                round_start = None
        last = cash + sum(
            (
                (1 if layer["side"] == "LONG" else -1)
                * (b.close - layer["price"])
                * x.facts.multiplier
                for layer in layers.values()
            ),
            D(0),
        )
        max_lots = max(max_lots, len(layers))
        peak = max(peak, last)
        dd = (peak - last) / peak
        if dd > max_dd:
            max_dd = dd
            dd_cash = peak - last
            dd_at = b.bar_end.isoformat()
        max_day_loss = max(max_day_loss, day_start - last)
    if (
        cash != D(result["cash"])
        or last != D(result["equity"])
        or fees != D(result["fees"])
        or gross != D(result["gross_realized"])
        or len(used) != len(result["fills"])
    ):
        raise ValueError("ACCOUNT_RECONCILIATION_FAILED")
    if set(layers) != {layer["layer_id"] for layer in result["open_layers"]}:
        raise ValueError("POSITION_RECONCILIATION_FAILED")
    actual_rounds = [
        dict(row, net_pnl=D(row["net_pnl"])) for row in result["closed_rounds"]
    ]
    if rebuilt_rounds != actual_rounds:
        raise ValueError("CLOSED_ROUND_RECONCILIATION_FAILED")
    trace = result["trace"]
    pause = [
        t
        for t in trace
        if t["before"].get("loss_pause_day") is None
        and t["after"].get("loss_pause_day") is not None
    ]
    resume = [
        t
        for t in trace
        if t["before"].get("loss_pause_day") is not None
        and t["after"].get("loss_pause_day") is None
    ]
    return _wire(
        dict(
            net_pnl=result["net_pnl"],
            fees=fees,
            closed_rounds=len(result["closed_rounds"]),
            fills=len(result["fills"]),
            max_lots=max_lots,
            drawdown_pct=max_dd * 100,
            drawdown_cny=dd_cash,
            drawdown_at=dd_at,
            max_daily_net_loss=max_day_loss,
            max_closed_trade_loss=max(
                [max(D(0), -D(r["net_pnl"])) for r in result["closed_rounds"]] + [D(0)]
            ),
            closed_losses_over_2000=sum(
                D(r["net_pnl"]) < -D(2000) for r in result["closed_rounds"]
            ),
            ending_quantity=len(layers),
            pending=result["pending"] is not None,
            pause_events=[
                dict(at=t["facts"]["at"], day=t["after"]["loss_pause_day"])
                for t in pause
            ],
            resume_events=[dict(at=t["facts"]["at"]) for t in resume],
            exit_reasons=dict(
                Counter(
                    reason
                    for f in result["fills"]
                    if f["action"] == "CLOSE"
                    for reason in f["reasons"]
                )
            ),
            rejects=dict(
                Counter(
                    reason
                    for t in trace
                    for a in t["actions"]
                    if a.get("kind") == "REJECT"
                    for reason in a.get("reasons", [])
                )
            ),
            execution_rejections=dict(
                Counter(e["reason"] for e in result["execution_events"])
            ),
            accounting_verified=True,
        )
    )


def run(prepared, output, contract, variant, fee, slip):
    from app.subing_model.account import decode_execution

    index = json.loads((prepared / "index.json").read_text())
    if index["code_hashes"] != hashes():
        raise ValueError("RESEARCH_CODE_CHANGED")
    if (
        (fee, slip) not in SCENARIOS
        or variant not in index["variants"]
        or contract not in index["prepared"]
    ):
        raise ValueError("SCENARIO_INVALID")
    entry = index["prepared"][contract]
    path = prepared / entry["file"]
    if sha(path) != entry["sha256"]:
        raise ValueError("PREPARED_INPUT_CHANGED")
    key = f"{contract}-{variant}-fee{fee}-slip{slip}"
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / (key + ".json.gz")
    summary_path = output / (key + ".summary.json")
    if result_path.exists() or summary_path.exists():
        raise ValueError("OUTPUT_ALREADY_EXISTS")
    bundle = json.loads(gzip.decompress(path.read_bytes()))
    xs = stressed(
        [
            decode_execution({"bar": r["bar"], "facts": r["facts"]})
            for r in bundle["executions"]
        ],
        fee,
    )
    obs = {x.bar.bar_end: r for x, r in zip(xs, bundle["observations"], strict=True)}
    factory = build_one_lot if variant == "one_lot" else build_control
    module, Candidate, context = factory(
        xs, bundle["schedule"], structures=bundle["structures"]
    )
    if variant == "capital_control":
        module.INITIAL_CASH = D(POLICY["initial_cash"])
    run_id = f"subing-C:{key}:{entry['sha256'][:12]}"
    result = module.replay(
        xs,
        obs,
        run_id,
        slippage_ticks=slip,
        execution_model="theoretical_open",
        regime_research_profile=REGIME_PROFILE,
    )
    scenario_policy = dict(POLICY)
    if variant == "capital_control":
        result["experiment_profile"] = "capital_only_1000000_v1"
        result["version"] += "_capital_only_1000000_v1"
        scenario_policy = dict(
            version="subing_unified_demand_candidate_v1_capital_only",
            initial_cash="1000000",
            max_lots=3,
            round_loss_budget="2000",
            daily_loss_budget="5000",
            planned_stop_budget="NOT_APPLIED",
            loss_streak_trigger="NOT_APPLIED",
        )
    measured = metrics(xs, result)
    if variant == "one_lot":
        if measured["max_lots"] > 1 or any(
            f["action"] == "ADD" for f in result["fills"]
        ):
            raise ValueError("ONE_LOT_CONSTRAINT_FAILED")
        if fee == 1 and slip == 1:
            if (
                Candidate.restore(result["decision_checkpoint"]).state()
                != result["decision_state"]
            ):
                raise ValueError("DECISION_RESTORE_CONFLICT")
    if index["code_hashes"] != hashes() or sha(path) != entry["sha256"]:
        raise ValueError("RESEARCH_INPUT_CHANGED")
    dump(
        result_path,
        dict(
            kind="SEEN_DEVELOPMENT_PRESSURE_NOT_OOS",
            contract=contract,
            since=entry["since"],
            through=entry["through"],
            variant=variant,
            fee_multiplier=fee,
            slippage_ticks=slip,
            prepared_sha256=entry["sha256"],
            context_hash=context,
            policy=scenario_policy,
            boundary=entry["boundary"],
            result=result,
        ),
        compressed=True,
    )
    record = dict(
        contract=contract,
        since=entry["since"],
        through=entry["through"],
        variant=variant,
        fee_multiplier=fee,
        slippage_ticks=slip,
        result_file=result_path.name,
        result_sha256=sha(result_path),
        boundary=entry["boundary"],
        **measured,
    )
    dump(summary_path, record)
    print(json.dumps(record, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--locked-at", type=datetime.fromisoformat, required=True)
    p = sub.add_parser("run")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--contract", required=True)
    p.add_argument("--variant", choices=("one_lot", "capital_control"), required=True)
    p.add_argument("--fee", type=int, choices=(1, 2, 3), required=True)
    p.add_argument("--slip", type=int, choices=(1, 2, 3), required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        if args.locked_at.utcoffset() is None:
            raise ValueError("NAIVE_LOCK_TIME")
        prepare(args.output, args.locked_at)
    else:
        run(
            args.prepared, args.output, args.contract, args.variant, args.fee, args.slip
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        code = str(exc.args[0]) if exc.args else ""
        print(
            json.dumps(
                dict(
                    status="RESEARCH_FAILED",
                    error_type=type(exc).__name__,
                    error_code=code
                    if re.fullmatch(r"[A-Z][A-Z0-9_]{2,100}", code)
                    else "DETAIL_REDACTED",
                )
            ),
            flush=True,
        )
        raise SystemExit(2) from None
