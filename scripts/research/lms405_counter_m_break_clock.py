"""Compare break clocks and new shapes for the OI2605 and RU2701 counter-M plans."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_counter_m_study import beyond
from lms405_m_permission_study import completed_paths
from lms405_portfolio_replay import input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import PERIODS, VARIANTS, read_window
from lms405_public_plan_roles import load_source
from lms405_right_side_study import US, at
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms_near405_replay import encoded

CASES = (
    ("oi2605", "oil", {"near": "m_near", "far": "m_far"}),
    ("oi2609_before_update", "oil", {"protection_reference_lower": "prior_protection_far",
                                    "prior_completed_day_low": "prior_day_low"}),
    ("ru2701_day", "rubber", {"near": "m_near", "far": "m_far"}),
)
REFERENCES = {
    "oil": ("lms405-counter-m-20261125/report.json", "70b45150fe0f08179ffec2b738b7ba556a5ffd2ed196044e4ea8d4cbeedd94c0"),
    "rubber": ("lms405-counter-m-ru-20261125/report.json", "a8c97015d4184caa35ec160c424245192518448f7e1ce3075627a20b83e1ef2d"),
}


def observe(series, *, side, edge, start, cut):
    scoped = {period: completed(rows, start, cut) for period, rows in series.items()}
    minute_runs = completed_paths(scoped[1], edge, side)
    breaks = {period: [bar.end for bar in scoped[period] if beyond(bar.close, edge, side)] for period in PERIODS}
    events_by_variant = {
        (shape, confirm): signals(scoped, shape, confirm, side=side, start=start, cut=cut)
        for shape, confirm in VARIANTS
    }
    gates = {}
    for period, closes in breaks.items():
        first = next(iter(closes), None)
        groups = {}
        for (shape, confirm), events in events_by_variant.items():
            starts = {bar.end: bar.start for bar in scoped[shape]}
            rows = []
            for event in events:
                shape_start = starts[event["shape_end"]]
                if first is None or first + US >= shape_start:
                    continue
                _, run = minute_runs[event["confirmed_at"]]
                # A previous break is insufficient for this alternative if
                # the current contiguous 1m run has no qualifying gate close.
                renewed = next((close for close in closes if run is not None
                                and run <= close and close + US < shape_start), None)
                rows.append(dict(event, shape_start=shape_start, first_gate_close=first,
                                 active_minute_run_start=run, gate_in_active_run=renewed,
                                 still_beyond=beyond(event["close"], edge, side)))
            groups[f"{shape}m_to_{confirm}m"] = dict(
                after_first_gate=next(iter(rows), None),
                still_beyond=next((row for row in rows if row["still_beyond"]), None),
                gate_in_active_run=next((row for row in rows if row["gate_in_active_run"] is not None), None),
            )
        gates[f"{period}m"] = dict(first_strict_close=first, groups=groups)
    return dict(edge=edge, gates=gates)


def check_prefixes(series, *, side, edge, start, cut):
    full = observe(series, side=side, edge=edge, start=start, cut=cut)
    clocks = {cut}
    for gate in full["gates"].values():
        if gate["first_strict_close"] is not None:
            clocks.update((gate["first_strict_close"] + US, gate["first_strict_close"] + 2 * US))
        for group in gate["groups"].values():
            for row in group.values():
                if row:
                    clocks.update((row["available_at"], row["available_at"] + US))
    for clock in sorted(clocks):
        prefix = {p: [b for b in rows if b.end + US < clock] for p, rows in series.items()}
        before = observe(prefix, side=side, edge=edge, start=start, cut=clock)
        for period, gate in full["gates"].items():
            first = gate["first_strict_close"]
            expected_first = first if first is not None and first + US < clock else None
            if before["gates"][period]["first_strict_close"] != expected_first:
                raise ValueError("COUNTER_M_BREAK_PREFIX_DIVERGED")
            for group, paths in gate["groups"].items():
                expected = {key: row if row and row["available_at"] < clock else None for key, row in paths.items()}
                if before["gates"][period]["groups"][group] != expected:
                    raise ValueError("COUNTER_M_SHAPE_PREFIX_DIVERGED")
    return full | dict(prefix_checks=len(clocks))


def study(session, market):
    index = input_sources()
    reports = {key: verified_json(Path("output") / path, fingerprint)["cases"]
               for key, (path, fingerprint) in REFERENCES.items()}
    result = {}
    for key, reference, edges in CASES:
        ref = reports[reference][key]
        days = [read_window(session, market, ref["contract"], date.fromisoformat(day)) for day in ref["trading_days"]]
        series = {period: [bar for day in days for bar in day[period]] for period in PERIODS}
        inputs = {f"{p}m": dict(count=len(bars), ohlc_sha256=digest(bars)) for p, bars in series.items()}
        if {p: inputs[p] for p in ref["series"]} != ref["series"]:
            raise ValueError("COUNTER_M_MARKET_INPUT_CHANGED")
        start, cut = map(at, ref["window"])
        # F09 in the original frozen study is the same author post as the archive's WR2IUYCQHj.
        source_keys = ["WR2IUYCQHj" if sid == "F09" else sid for sid in ref["source_ids"]]
        if key == "oi2609_before_update":
            source_keys.append("S5306128623993006")
        sources = {sid: load_source(index, sid) for sid in source_keys}
        source_availability = {sid: datetime.fromisoformat(source["published_at"]) for sid, source in sources.items()}
        result[key] = dict(
            contract=ref["contract"], start=start, cutoff=cut, market=inputs, reference_sha256=REFERENCES[reference][1],
            sources=sources, displayed_publication=source_availability, historical_plan_verified=False,
            scope="RETROSPECTIVE_PRICE_GEOMETRY_ONLY", author_permission=None, author_action_at=None,
            edges={role: check_prefixes(series, side=ref["side"], edge=Decimal(ref["events"][edge]["level"]),
                                        start=start, cut=cut) for role, edge in edges.items()},
        )
    return dict(version="lms405-counter-m-break-clock-v1", cases=result, author_action_samples=0,
                author_match_rate=None, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError
    from sqlalchemy.exc import OperationalError

    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("COUNTER_M_")
                        else "COUNTER_M_EVIDENCE_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
