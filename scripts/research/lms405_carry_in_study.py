"""Compare cold start and disclosed starting legs for two frozen LMS research cases."""

import argparse
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from guiyi_quant.lms405 import Action, Bar, Position, apply_action
from lms405_locked_exit_audit import confirmed_shapes, verify_aggregation
from lms405_portfolio_replay import ARCHIVE, DAYS, FIVE, LOCAL
from lms405_replay import ohlc, read_session_series
from lms405_snapshot_comparison import ONE, RESPONSE_DELAY, visible_leg_checks
from lms405_sizing_audit import EXPOSURE_SHA256, positive_decimal
from lms_near405_replay import encoded, sha

CONTRACTS = ("I2701", "SH2701")
SNAPSHOT_SHA256 = "1075e7bfedb49307b28ef0ae7139f9d355f025e831e7c235c336f7caf093310a"
POLICIES = ("CARRY_ONLY", "KEYBAR_1M_CLOSE", "KEYBAR_5M_CLOSE")


def position_fields(position):
    return dict(
        long=str(position.long), short=str(position.short),
        net=str(position.long - position.short), gross=str(position.long + position.short),
    )


def keybar_events(fives, minutes, available_at, through):
    """Reuse the frozen geometry. A complete shape must start after seed availability."""
    events = {policy: defaultdict(list) for policy in POLICIES[1:]}
    shape_starts = {bar.end.isoformat(): bar.start for bar in fives}
    for side in ("LONG", "SHORT"):
        rows = confirmed_shapes(fives, minutes, start=available_at, through=through, side=side)
        for row in rows:
            shape_start = shape_starts[row["shape_at"]].astimezone(LOCAL)
            if shape_start <= available_at:
                continue
            for policy, field in zip(POLICIES[1:], ("fast_at", "slow_at"), strict=True):
                if row[field] is not None:
                    close = datetime.fromisoformat(row[field]).astimezone(LOCAL)
                    at = close + RESPONSE_DELAY
                    if at < through:
                        events[policy][at].append(dict(
                            direction=side, shape_start=shape_start, shape_end=(shape_start + FIVE).isoformat(),
                            confirmation_close=close.isoformat(), level=row["level"],
                        ))
    return events


def project(seed, available_at, batches):
    """For sensitivity only, change the protection leg and preserve the original short."""
    if seed.short <= 0 or seed.long not in (0, seed.short):
        raise ValueError("SHORT_CARRY_IN_SEED_REQUIRED")
    position, since = seed, available_at
    retained_seed_long = seed.long > 0
    steps = []
    for at, signals in sorted(batches.items()):
        if at <= since:
            continue
        fresh = [signal for signal in signals if since < signal["shape_start"]]
        sides = {signal["direction"] for signal in fresh}
        if len(sides) > 1:
            steps.append(dict(at=at, action=None, reason="CONFLICTING_CONFIRMATIONS", signals=fresh))
            continue
        if position.long == 0 and sides == {"LONG"}:
            action = "LOCK"
        elif position.long > 0 and sides == {"SHORT"}:
            action = "UNLOCK_SHORT"
            retained_seed_long = False
        else:
            continue
        before = position_fields(position)
        position = apply_action(position, Action(action, seed.short))
        since = at
        steps.append(dict(
            at=at, action=action, before=before, after=position_fields(position),
            retained_seed_long=retained_seed_long, signals=fresh,
        ))
    return steps


def at_anchor(seed, steps, anchor, author, starting_legs):
    prior = [step for step in steps if step["at"] < anchor and step["action"] is not None]
    position = prior[-1]["after"] if prior else position_fields(seed)
    retained_seed_long = prior[-1]["retained_seed_long"] if prior else seed.long > 0
    comparisons = {}
    for side in ("long", "short"):
        retained = side == "short" or retained_seed_long
        observed = author.get(side, {}).get("opening_average")
        earlier = starting_legs[side]["opening_average"]
        comparisons[side] = (
            Decimal(observed) == Decimal(earlier) if retained and observed is not None and earlier is not None
            else None
        )
    return dict(
        projected_position=position, legs=visible_leg_checks(author, position),
        retained_seed_long=retained_seed_long, retained_leg_opening_average_agrees=comparisons,
        last_action=prior[-1] if prior else None, prior_actions=len(prior),
    )


def case(contract, starting_legs, available_at, snapshots, fives, minutes):
    if any(bar.contract != contract for bar in fives):
        raise ValueError("CONTRACT_BOUNDARY")
    verify_aggregation(fives, minutes)
    quote_closes = {bar.bar_end: bar.close for bar in minutes}
    through = max(datetime.fromisoformat(snap["quote_anchor"]) for snap in snapshots)
    if (starting_legs["short"]["today_quantity"] != 0
            or starting_legs["long"]["today_quantity"] <= 0):
        raise ValueError("OLDER_SHORT_AND_CURRENT_LONG_REQUIRED")
    short, long = (positive_decimal(starting_legs[side]["quantity"]) for side in ("short", "long"))
    if long != short:
        raise ValueError("MATCHED_SEED_LEGS_REQUIRED")
    scenarios = {}
    events = keybar_events(fives, minutes, available_at, through)
    for name, seed in (
        ("OLDER_SHORT_ONLY", Position(contract, short=short)),
        ("DISCLOSED_BOTH_LEGS", Position(contract, long=long, short=short)),
    ):
        scenarios[name] = {policy: (seed, project(seed, available_at, events.get(policy, {}))) for policy in POLICIES}
    anchors = []
    for snapshot in snapshots:
        anchor = datetime.fromisoformat(snapshot["quote_anchor"])
        row = snapshot["contracts"][contract]
        if (not available_at < anchor or row["quote_aligned"] is not True
                or quote_closes.get(anchor) != Decimal(row["mds_close"])):
            raise ValueError("UNVERIFIED_CARRY_IN_QUOTE_ANCHOR")
        author = row["author_visible_legs"]
        if row["same_fields_on_first_night_older_legs"] != ["short"]:
            raise ValueError("OLD_SHORT_NOT_REOBSERVED")
        anchors.append(dict(
            quote_anchor=snapshot["quote_anchor"], source=snapshot["source"],
            source_published_at=snapshot["source_published_at"], author_visible_legs=author,
            cold_start=row["variants"]["BASELINE"]["before_quote_close"],
            carry_in={name: {
                policy: at_anchor(seed, steps, anchor, author, starting_legs)
                for policy, (seed, steps) in policies.items()
            } for name, policies in scenarios.items()},
        ))
    return dict(
        seed_visible_legs=starting_legs, anchors=anchors,
        scenario_steps={name: {policy: steps for policy, (_, steps) in policies.items()}
                        for name, policies in scenarios.items()},
    )


def compute(session, market, exposure, comparison):
    (first,) = [row for row in exposure["tables"] if row["source"] == comparison["first_night_source"]]
    if first["system"] != "4.0.5" or first["binding"] != "SYSTEM_COVER":
        raise ValueError("EXPECTED_405_COVER")
    if sha((ARCHIVE.parent / first["image"]["path"]).read_bytes()) != first["image"]["sha256"]:
        raise ValueError("FIRST_NIGHT_IMAGE_CHANGED")
    available_at = datetime.fromisoformat(first["published_at"]) + ONE
    cases, coverage = {}, {}
    for contract in CONTRACTS:
        symbol = contract[:-4].lower()
        coverage[contract] = {}
        series = {}
        for frequency, step in (("1m", ONE), ("5m", FIVE)):
            bars = series[frequency] = read_session_series(session, market, symbol, contract, frequency, step, DAYS[:3])
            rows = [(bar.bar_end.isoformat(), *map(str, ohlc(bar))) for bar in bars]
            coverage[contract][frequency] = dict(count=len(rows), sha256=sha(encoded(rows).encode()))
            if frequency == "1m":
                for key, frozen in comparison["market_1m"].items():
                    if key.startswith(contract + ":"):
                        # Each anchor is in a trading day whose overnight rows begin at 21:00.
                        day = datetime.fromisoformat(key.split(":", 1)[1]).date()
                        items = [(bar.bar_end.isoformat(), *map(str, ohlc(bar)))
                                 for bar in bars if bar.trading_day == day]
                        if sha(encoded(items).encode()) != frozen["sha256"]:
                            raise ValueError("FROZEN_MINUTE_SERIES_CHANGED")
        fives = [Bar(contract, bar.bar_end, *ohlc(bar), start=bar.bar_end - FIVE) for bar in series["5m"]]
        cases[contract] = case(
            contract, first["contracts"][contract]["legs"], available_at,
            comparison["snapshots"], fives, series["1m"],
        )
    return dict(
        version="lms405-short-carry-in-study-v1", seed_source=first["source"],
        seed_published_at=first["published_at"], seed_available_at=available_at,
        seed_archive_path=first["archive_path"], seed_quote_anchor=None,
        trading_days=[day.isoformat() for day in DAYS[:3]], market=coverage, cases=cases,
        original_side_assumption="SHORT", cold_start_is_existing_fixture=True,
        old_plan=None, author_permission=None, account_continuity=None, author_action_matches=None,
        admitted_author_action_samples=0, fills=None, pnl=None, executable=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--exposure-audit", type=Path, required=True)
    parser.add_argument("--snapshot-comparison", type=Path, required=True)
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
        raw_exposure = args.exposure_audit.read_bytes()
        raw_comparison = args.snapshot_comparison.read_bytes()
        if sha(raw_exposure) != EXPOSURE_SHA256 or sha(raw_comparison) != SNAPSHOT_SHA256:
            raise ValueError("FROZEN_INPUT_HASH_MISMATCH")
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = compute(session, build_market_data_service(session), json.loads(raw_exposure), json.loads(raw_comparison))
        result["input_sha256"] = dict(exposure=EXPOSURE_SHA256, comparison=SNAPSHOT_SHA256)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as error:
        parser.exit(2, f"MDS_BLOCKED: {error.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, ValueError, KeyError, InvalidOperation) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
