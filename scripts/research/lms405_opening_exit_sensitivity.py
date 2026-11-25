"""Isolate one proxy exit at a time after a frozen LMS opening fixture."""

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant import lms_near405 as candidate
from guiyi_quant.lms405 import Bar
from lms405_opening_portfolio_replay import (
    BASE_SHA, BASELINE, CASES, DAYS, FIVE, OPENING, OPENING_SHA, US, VERSION as SEED_VERSION,
    opening_selection, state_before, verified_json,
)
from lms405_replay import ohlc, read_session_series
from lms_near405_replay import encoded, sha

VERSION = "lms405-opening-exit-sensitivity-v1"
FROZEN = Path("output/lms405-opening-portfolio-20261125/final.json")
FROZEN_SHA = "aa978486f1536ddff45df4fe0a792513cae83be9e4d493ea885a3ba1c662f8f4"
MODE = "FIRST_COMPLETED_MINUTE"
SCENARIOS = (
    ("pta_new_long", "1m_to_1m"),
    ("jm_new_short", "1m_to_1m"),
    ("soda_new_long", "5m_to_1m"),
    ("soda_new_long", "5m_to_5m"),
    ("soda_new_short", "15m_to_15m"),
)


def evaluate_scenario(bars, case, name, clock, reference):
    audit = reference["audits"][name]
    quotes = reference["opening_quote_comparisons"][name]
    signal = opening_selection(case, CASES[name], MODE, clock)
    known = signal["confirmed_at"] + 2 * US
    until = datetime.fromisoformat(case["cutoff_exclusive"])
    anchors = {label: datetime.fromisoformat(label) for label in case["capture_boundaries"]}
    if (audit["status"] != "TEST_FIXTURE_ONLY" or known != datetime.fromisoformat(audit["at"])
            or encoded(signal) != encoded(audit["candidate"]) or set(quotes) != set(anchors)
            or not all(t < until for t in anchors.values()) or max(anchors.values()) <= known):
        raise ValueError("OPENING_EXIT_FIXTURE_DRIFT")
    scope = f"{SEED_VERSION}:{case['contract']}:{case['start']}:{MODE}:{clock}"
    seed = candidate.CarryInSeed(case["contract"], known, case["direction"], False, f"TEST_FIXTURE:{scope}")
    side = case["direction"].lower()
    pre_entry = candidate.replay(bars, as_of=known - US, timely_fixture=True)
    if any(Decimal(pre_entry["current_state"][leg]) for leg in ("long", "short")):
        raise ValueError("OPENING_EXIT_BASELINE_NOT_FLAT_AT_ENTRY")
    outcomes = {}
    fixed_state = None
    for omitted in (None, *candidate.CARRY_PROXY_EXIT_REASONS):
        options = dict(carry_in=seed, timely_fixture=True, omitted_proxy_exit=omitted)
        run = candidate.replay(bars, as_of=until, **options)
        initial = run["checkpoint"]["initial_state"]
        if omitted is None:
            fixed_state = initial
        elif initial != fixed_state:
            raise ValueError("OPENING_EXIT_FIXED_PLAN_DRIFT")
        cut = max(anchors.values()) - US
        prefix = candidate.replay(bars, as_of=cut, **options)
        trimmed = [bar for bar in bars if bar.end + US <= cut]
        if (prefix != candidate.replay(trimmed, as_of=cut, **options)
                or run != candidate.replay(bars, as_of=until, checkpoint=prefix["checkpoint"], **options)):
            raise ValueError("OPENING_EXIT_PREFIX_OR_RESTART_DRIFT")
        actions = [row for row in run["transitions"] if datetime.fromisoformat(row["known_at"]) < until]
        compact = [{key: row[key] for key in ("known_at", "action", "reason")} for row in actions]
        at_quote = {}
        for label, t in anchors.items():
            if t <= known:
                state = state_before(pre_entry["transitions"], pre_entry["checkpoint"]["initial_state"], t)
            else:
                state = state_before(actions, initial, t)
            has_direction = Decimal(state[side]) > 0
            at_quote[label] = dict(
                visible_direction=has_direction,
                original_cycle_intact=t > known and has_direction and state["cycle_id"] == initial["cycle_id"],
                long=state["long"], short=state["short"],
            )
        if omitted is None and (compact != audit["management_until_post"] or any(
            row["visible_direction"] != quotes[label]["scenario_direction_visible"]
            for label, row in at_quote.items()
        )):
            raise ValueError("OPENING_EXIT_CONTROL_DRIFT")
        outcomes[omitted or "CONTROL"] = dict(
            rule_hash=run["rule_hash"], actions=compact, quotes=at_quote,
            first_original_clear=next((entry for row, entry in zip(actions, compact, strict=True)
                                       if row["action"] == "CLEAR"
                                       and row["before"]["cycle_id"] == initial["cycle_id"]), None),
            quote_direction_count=sum(row["visible_direction"] for row in at_quote.values()),
            original_cycle_quote_count=sum(row["original_cycle_intact"] for row in at_quote.values()),
            original_cycle_and_whole_leg_price_compatible_count=sum(
                row["original_cycle_intact"] and quotes[label]["whole_observed_leg_compatible_after_scenario"] is True
                for label, row in at_quote.items()
            ),
        )
    return dict(contract=seed.contract, fixture_authorized_at=known, confirmed_at=signal["confirmed_at"],
                direction=seed.original_side, fixed_plan=fixed_state["plan"], cutoff_exclusive=until,
                quote_alternatives=len(anchors), fixed_price_bounds=quotes, outcomes=outcomes)


def study(session, market):
    baseline = verified_json(BASELINE, BASE_SHA)
    openings = verified_json(OPENING, OPENING_SHA)
    reference = verified_json(FROZEN, FROZEN_SHA)
    if reference["baseline_sha256"] != BASE_SHA or reference["opening_sha256"] != OPENING_SHA:
        raise ValueError("OPENING_EXIT_REFERENCE_IDENTITY_DRIFT")
    cases = {name: openings["cases"][name] for name, _ in SCENARIOS}
    latest = datetime.fromisoformat(baseline["as_of"])
    series_by_contract, input_hashes = {}, {}
    for contract in sorted({case["contract"] for case in cases.values()}):
        raw = read_session_series(session, market, contract[:-4].lower(), contract, "5m", FIVE, DAYS)
        bars = [Bar(contract, b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in raw if b.bar_end + US <= latest]
        digest = sha(encoded([[b.end.isoformat(), *map(str, ohlc(b))] for b in bars]).encode())
        if digest != baseline["contract_summaries"][contract]["input_prefix_sha256"]:
            raise ValueError("OPENING_EXIT_BASELINE_BAR_DRIFT")
        series_by_contract[contract] = bars
        input_hashes[contract] = dict(bar_count=len(bars), input_prefix_sha256=digest)
    scenarios = {
        f"{name}/{clock}": evaluate_scenario(
            series_by_contract[cases[name]["contract"]], cases[name], name, clock,
            reference["variants"][f"{MODE}/{clock}"],
        ) for name, clock in SCENARIOS
    }
    return dict(version=VERSION, frozen_opening_replay_sha256=FROZEN_SHA, frozen_opening_clock_sha256=OPENING_SHA,
                baseline_sha256=BASE_SHA, input_hashes=input_hashes, scenarios=scenarios, executable=False,
                admitted_author_actions=0, author_match_rate=None, fills=None, pnl=None)


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
    except (KeyError, OSError, TypeError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('OPENING_EXIT_') and code.isidentifier() else 'OPENING_EXIT_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
