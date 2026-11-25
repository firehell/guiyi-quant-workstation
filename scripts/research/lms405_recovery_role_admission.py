"""Check which near-edge price candidates have an explicit original-position recovery role."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lms405_portfolio_replay import CONTRACTS, input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US, at
from lms405_unlock_boundary_comparison import evaluate
from lms_near405_replay import encoded, sha

VERSION = "lms405-recovery-role-admission-v1"
PORTFOLIO_DAY = date(2026, 10, 27)
REGULAR = "A5358325549629506"
ALTERNATIVE = "A5358325972992140"
RETROSPECTIVE = Path("output/lms405-unlock-boundary-20261125/final.json")
RETROSPECTIVE_SHA = "4a0c6c836fc64b0c5c0af5b4310395b5a8c7d9026c14b31ec459f433f715e541"
EXPLICIT_NEAR = "EXPLICIT_ORIGINAL_RECOVERY_NEAR"
PORTFOLIO = {
    "OI2701": ("SHORT", "10240 10283", "DIVIDE", (REGULAR,)),
    "RU2701": ("SHORT", "19505 19570", "STRONG_SIDE_ENVIRONMENT", (ALTERNATIVE,)),
    "JM2701": ("SHORT", "1392 1415.5", "DIVIDE", (REGULAR,)),
    "FG2701": ("SHORT", "828 832", "STRONG_SIDE_ENVIRONMENT", (REGULAR,)),
    "SA2701": ("SHORT", "951 957", "DIVIDE", (REGULAR,)),
    "V2701": ("LONG", "5195 5195", "RIGHT_SIDE_ENTRY", (REGULAR,)),
    "TA2701": (None, None, "MODEL_PAUSED_NO_BAND", (ALTERNATIVE,)),
    "SH2701": ("SHORT", "1511 1516", "OLD_RESISTANCE_REASSESSED", (ALTERNATIVE, "WRouYm67Bc")),
    "I2701": ("SHORT", "668.5 671.5", "STRONG_SIDE_ENVIRONMENT", (REGULAR,)),
}


def terminal_candidate(event, *, role, published_minute_end, retrospective):
    if "NEAR" not in event["modes"]:
        return "NEAR_PRICE_NOT_CONFIRMED"
    if role != EXPLICIT_NEAR:
        return "NO_EXPLICIT_NEAR_RECOVERY_ROLE"
    if retrospective:
        return "RETROSPECTIVE_PRICE_CANDIDATE"
    shape_start = event["shape_end"] - event["shape_minutes"] * ONE
    if published_minute_end is None or published_minute_end >= shape_start:
        return "SOURCE_NOT_STRICTLY_BEFORE_CANDIDATE"
    return "CONDITIONAL_PRICE_CANDIDATE_ONLY"


def observed(series, *, start, cut, side, band, role, published_minute_end):
    def with_admission(rows):
        return [event | dict(near_admission=terminal_candidate(
            event, role=role, published_minute_end=published_minute_end, retrospective=False,
        )) for event in rows]

    args = dict(start=start, side=side, band=band)
    paths = evaluate(series, cut=cut, **args)
    candidates = with_admission(paths["candidates"])
    instants = {event["available_at"] for event in candidates if "NEAR" in event["modes"]}
    cuts = instants | {instant + US for instant in instants}
    for endpoint in sorted(cuts):
        prefix = {p: [bar for bar in bars if bar.end + US < endpoint] for p, bars in series.items()}
        earlier = with_admission(evaluate(prefix, cut=endpoint, **args)["candidates"])
        expected = [event for event in candidates if event["available_at"] < endpoint]
        if earlier != expected:
            raise ValueError("NEAR_ROLE_PREFIX_DIVERGED")
    return dict(minute_count=paths["minute_count"], candidates=candidates, near_prefix_checks=len(cuts))


def study(session, market):
    index = input_sources()
    if set(PORTFOLIO) != set(CONTRACTS):
        raise ValueError("NEAR_ROLE_PORTFOLIO_SCOPE_CHANGED")
    portfolio = {}
    day = PORTFOLIO_DAY.isoformat()
    for contract, (side, raw_band, role, source_ids) in PORTFOLIO.items():
        sources = [load_source(index, key) for key in source_ids]
        known_after = max(datetime.fromisoformat(source["published_at"]).replace(second=0, microsecond=0) + ONE
                          for source in sources)
        series = read_window(session, market, contract, PORTFOLIO_DAY)
        minutes = series[1]
        if not minutes:
            raise ValueError("NEAR_ROLE_MARKET_WINDOW_EMPTY")
        market_input = {f"{p}m": dict(count=len(rows), sha256=sha(encoded([
            (bar.start, bar.end, bar.open, bar.high, bar.low, bar.close) for bar in rows
        ]).encode())) for p, rows in series.items()}
        row = dict(contract=contract, side_scenario=side, role=role, sources=sources, market_input=market_input,
                   current_historical_revision_verified=False, source_minute_end=known_after,
                   band=None, minute_count=None, candidates=None)
        if raw_band is not None:
            band = tuple(map(Decimal, raw_band.split()))
            start, cut = max(minutes[0].start, known_after + US), at(f"{day}T15:01")
            if role == "OLD_RESISTANCE_REASSESSED":
                lunch = load_source(index, "WRoAkcEppg")
                row["position_context_sources"] = [lunch, load_source(index, "U03")]
                start = max(start, datetime.fromisoformat(lunch["published_at"]).replace(second=0, microsecond=0) + ONE)
                cut = at(f"{day}T15:00")
            row.update(band=band, start=start, cutoff_exclusive=cut, **observed(
                series, start=start, cut=cut, side=side, band=band, role=role,
                published_minute_end=known_after,
            ))
        portfolio[contract] = row

    reference = verified_json(RETROSPECTIVE, RETROSPECTIVE_SHA)
    controls = {}
    for name in ("pvc_not_unlocked", "pvc_target_completed", "coal_morning"):
        case = reference["cases"][name]
        source = case["source"]
        is_coal = name == "coal_morning"
        source_time = (at(source["published_shanghai"].replace("；入口", "T"))
                       if is_coal else datetime.fromisoformat(source["published_at"]))
        known_after = source_time.replace(second=0, microsecond=0) + ONE
        role = EXPLICIT_NEAR if is_coal else "STRONG_TARGET"
        events = []
        for row in case["candidates"]:
            event = row | dict(shape_end=datetime.fromisoformat(row["shape_end"]),
                               available_at=datetime.fromisoformat(row["available_at"]))
            events.append(event | dict(
                replay_admission=terminal_candidate(event, role=role, published_minute_end=known_after,
                                                    retrospective=False),
                retrospective_admission=terminal_candidate(event, role=role, published_minute_end=known_after,
                                                           retrospective=True),
            ))
        controls[name] = dict(
            contract=case["contract"], role=role, source=source, source_minute_end=known_after,
            replay_cutoff=case["cutoff_exclusive"], candidates=events, author_action_at=None,
            post_session_plan_used_for_replay=False,
        )
    return dict(
        version=VERSION, portfolio_trading_day=day, portfolio=portfolio, controls=controls,
        reference_sha256=RETROSPECTIVE_SHA, execution_authority=False,
        provisional_price_role_only=True, author_match_rate=None, admitted_author_action_samples=0,
        fills=None, pnl=None,
    )


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
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError):
        parser.exit(2, "NEAR_ROLE_SCOPE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()
