"""Replay SH2701 release alternatives after the same simulated advance protection."""

import argparse
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant import lms_near405 as candidate
from lms405_m_permission_study import read_pair
from lms405_portfolio_protection_gate import (
    compare_caustic_quote,
    observations_for_contract,
    plan_rows,
    replay_with_price_context,
)
from lms405_portfolio_replay import DAYS, input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_route_comparison import FROZEN_ROUTES
from lms405_right_side_study import US
from lms405_sh_lock_lifecycle import digest
from lms_near405_replay import encoded

VERSION = "lms405-sh-advance-recovery-v1"
PRIOR = Path("output/lms405-portfolio-advance-protection-20261126/verified-a.json")
PRIOR_SHA = "8bbf892fbce5ea5b2d40465113ee9522d22ca2a167e9b867f4fb40cee3734815"
CONTRACT = "SH2701"
PLAN = "A5358686695981271"
REFERENCES = (
    ("protection_near", Decimal(1490), "DOCUMENTED_PROTECTION_RANGE_NEAR_EDGE"),
    ("strong_near", Decimal(1460), "DOCUMENTED_SHORT_TARGET_NEAR_EDGE"),
    ("strong_far", Decimal(1450), "DOCUMENTED_SHORT_TARGET_FAR_EDGE"),
)


def next_prices(series, edge, lock_time, quote_cutoff):
    minutes = [bar for bar in series[1] if lock_time < bar.start and bar.end + US < quote_cutoff]
    fives = [bar for bar in series[5] if lock_time < bar.start and bar.end + US < quote_cutoff]
    reached = next((bar.end for bar in minutes if bar.low <= edge), None)
    touched = next((bar.end for bar in minutes if bar.low <= edge <= bar.high), None)
    minute_close = next((bar.end for bar in minutes if bar.close < edge), None)
    five_close = next((bar.end for bar in fives if bar.close < edge), None)
    return dict(first_directional_reach_minute=reached, first_range_contains_level_minute=touched,
                first_strict_minute_close=minute_close,
                first_strict_five_minute_close=five_close)


def counts(quote):
    rows = quote["minutes"]
    locked = [row for row in rows if row["locked_before"] and row["locked_at_end"]]
    return dict(
        quote_minutes=len(rows), fully_locked_minutes=len(locked),
        split_minutes=sum(row["locked_before"] != row["locked_at_end"] for row in rows),
        fully_locked_and_prices_before_quote=sum(
            row["later_complete_minute_price_support"].get("before_quote_minute") is True for row in locked
        ),
        fully_locked_and_prices_through_quote=sum(
            row["later_complete_minute_price_support"].get("through_quote_minute") is True for row in locked
        ),
    )


def study(session, market, reference):
    _, series = read_pair(session, market, CONTRACT, DAYS)
    prior = reference["contracts"][CONTRACT]
    hashes = {f"{p}m": dict(count=len(rows), sha256=digest(rows)) for p, rows in series.items()}
    if hashes != prior["market"]:
        raise ValueError("SH_ADVANCE_RECOVERY_MARKET_CHANGED")
    seed_row = reference["carry_context"]["seeds"][CONTRACT]
    seed = candidate.CarryInSeed(**(seed_row | {"known_at": datetime.fromisoformat(seed_row["known_at"])}))
    updates, m_bands, sources = plan_rows(input_sources(), CONTRACT)
    if encoded([asdict(row) for row in updates]) != encoded(prior["schedules"]) or sources != prior["sources"]:
        raise ValueError("SH_ADVANCE_RECOVERY_SOURCES_CHANGED")
    day_end = series[5][-1].end + 3 * US
    events = observations_for_contract(series, updates, m_bands, day_end, period=1)
    args = dict(cutoff=day_end, due_field="advance_only", seed=seed, period=1)
    base, preclose_attempts = replay_with_price_context(series, updates, events, **args)
    expected = prior["unit_carry_fixtures"]["fast_advance_only_fixture"]
    if encoded(base["transitions"]) != encoded(expected["transitions"]) or encoded(preclose_attempts) != encoded(
        expected["attempts"]
    ):
        raise ValueError("SH_ADVANCE_RECOVERY_PRIOR_REPLAY_DIVERGED")
    lock, *_ = base["transitions"]
    if lock["action"] != "LOCK":
        raise ValueError("SH_ADVANCE_RECOVERY_LOCK_REQUIRED")
    locked_at = datetime.fromisoformat(lock["known_at"])
    zone = next(row for row in updates if row.revision == PLAN)
    quote = verified_json(*FROZEN_ROUTES)["case_days"]["2026-10-27"][CONTRACT]
    quote_cutoff = datetime.fromisoformat(quote["inputs"]["cutoff"])

    five_by_end = {bar.end: bar for bar in series[5]}

    def describe(transitions, *, boundary=None, attempts=None, evaluations=()):
        if (not transitions or transitions[0]["action"] != "LOCK"
                or transitions[0]["known_at"] != lock["known_at"]
                or transitions[0]["after"]["long"] != lock["after"]["long"]
                or transitions[0]["after"]["short"] != lock["after"]["short"]):
            raise ValueError("SH_ADVANCE_RECOVERY_FIRST_LOCK_CHANGED")
        compared = compare_caustic_quote(series[1], transitions, quote)
        return dict(boundary=asdict(boundary) if boundary else None, attempts=attempts,
                    actions=[dict(action=row["action"], known_at=row["known_at"], reason=row["reason"],
                                  research_units=[row["after"]["long"], row["after"]["short"]]) for row in transitions],
                    blocked_recovery_candidates=[
                        dict(bar_end=row["bar_end"], status=row["status"],
                             close=five_by_end[datetime.fromisoformat(row["bar_end"])].close)
                        for row in evaluations if row["status"].startswith("RECOVERY_")
                    ],
                    snapshot=compared, snapshot_counts=counts(compared))

    scenarios = dict(keybar_only=describe(base["transitions"], attempts=preclose_attempts),
                     retain_first_lock_without_release=describe([lock]))
    diagnostics = {}
    for name, edge, documented_role in REFERENCES:
        diagnostics[name] = dict(price=edge, documented_role=documented_role,
                                 after_lock_before_post=next_prices(series, edge, locked_at, quote_cutoff))
        for confirmation in ("CLOSE_BEYOND", "FRESH_TWO_CLOSES"):
            boundary = candidate.CarryRecoveryBoundary(
                CONTRACT, "SHORT", edge, zone.known_at, confirmation, f"{VERSION}:{PLAN}:{name}",
            )
            replay, attempts = replay_with_price_context(series, updates, events, recovery_boundary=boundary, **args)
            key = f"{name}_{confirmation.lower()}"
            scenarios[key] = describe(replay["transitions"], boundary=boundary, attempts=attempts,
                                      evaluations=replay["evaluations"])
    return dict(version=VERSION, contract=CONTRACT, scope="UNIT_CARRY_SENSITIVITY",
                prior_report_sha256=PRIOR_SHA, quote_reference_sha256=FROZEN_ROUTES[1],
                market=hashes, plan_source=sources[PLAN], first_fixture_lock=locked_at,
                references=diagnostics, scenarios=scenarios, retain_is_counterfactual=True,
                author_recovery_reference=None, author_actions_scored=0, author_match_rate=None,
                executable=False, fills=None, pnl=None)


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
        reference = verified_json(PRIOR, PRIOR_SHA)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=75):
            report = study(session, build_market_data_service(session), reference)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.isidentifier() else 'SH_ADVANCE_RECOVERY_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
