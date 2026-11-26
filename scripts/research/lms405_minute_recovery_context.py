"""Compare volatility context at fixed opt-in minute recovery candidates."""

import argparse
import csv
from datetime import date, datetime
from pathlib import Path

from lms405_jm2605_stability import SOURCE as COAL_SOURCE
from lms405_minute_recovery_replay import CASES, frozen_market
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_replay import ohlc
from lms405_right_side_study import ONE, US
from lms405_sh2609_recovery_context import contexts
from lms405_volatility_context import PERIOD, minute_context, read_inputs
from lms_near405_replay import encoded, sha

REFERENCE = Path("output/lms405-minute-recovery-20261126/final-a.json")
REFERENCE_SHA = "4891c526355d0161022c0001a99a6f3a2cf16c78dd7774ce1c2a6fae2c4ef30e"
COAL_SOURCE_SHA = "f0228fac1670a85c9340f28431664af49b08f71a095e82c6ae36b006d67f1b4c"
PERIOD_IMAGE = Path("03-单品种分析/2026-10-22/股指/RnTjn0HU8-key-screen.png")
PERIOD_IMAGE_SHA = "25b497b9312ef07cb8712be5ce78b58aca6e0f7159236d3953a2f80899992327"


def read_sources():
    if (sha(COAL_SOURCE.read_bytes()) != COAL_SOURCE_SHA
            or sha((ARCHIVE.parent / PERIOD_IMAGE).read_bytes()) != PERIOD_IMAGE_SHA):
        raise ValueError("MINUTE_CONTEXT_SOURCE_CHANGED")
    with COAL_SOURCE.open(newline="", encoding="utf-8") as stream:
        coal = next(row for row in csv.DictReader(stream) if row["id"] == "K01")
    index = input_sources()
    return dict(commodity_protection_and_recovery_condition=coal, coal_index_sha256=COAL_SOURCE_SHA,
                index_futures_period_question=load_source(index, "WRnTjn0HU8"),
                index_futures_period_image_sha256=PERIOD_IMAGE_SHA,
                commodity_protection_example=load_source(index, "S5305666088472874"),
                stable_but_unreleased=load_source(index, "S5292358960155373"))


def as_of_from_source(series, sessions, atr_inputs, cutoff):
    contraction = contexts(series[15], sessions, cutoff)
    if atr_inputs is None:
        return dict(known_before=cutoff, contraction=contraction, atr_context=None)
    minute_facts = atr_inputs["minutes"]
    facts = minute_context(minute_facts, initial_close=atr_inputs["dailies"][-1].close,
                           atr_total=atr_inputs["atr_total"], day_reopen_end=atr_inputs["day_reopen"], as_of=cutoff)
    return dict(known_before=cutoff, contraction=contraction, atr_context=facts[-1] if facts else None)


def candidates(series, sessions, atr_inputs, reference):
    rows = []
    for proposal in reference["proposed_with_test_permission"]:
        crossing, shape, confirm = (datetime.fromisoformat(proposal[k]) for k in (
            "crossing_end", "shape_start", "confirmed_at",
        ))
        checks = dict(before_crossing_bar=crossing - ONE, before_shape=shape, before_confirmation=confirm)
        contexts_by_time = {}
        for key, cut in checks.items():
            row = as_of_from_source(series, sessions, atr_inputs, cut)
            before = {p: [bar for bar in bars if bar.end + US < cut] for p, bars in series.items()}
            clipped = (atr_inputs | {"minutes": [bar for bar in atr_inputs["minutes"] if bar.bar_end + US < cut]}
                       if atr_inputs else None)
            if row != as_of_from_source(before, sessions, clipped, cut):
                raise ValueError("MINUTE_CONTEXT_PREFIX_DIVERGED")
            contexts_by_time[key] = row
        rows.append(dict(proposal=proposal, context=contexts_by_time))
    return rows


def study(session, market):
    from app.market_data.market_data_service import MarketDataError
    from app.market_data.session_clock import resolved_session_windows_for_trading_day

    ref = verified_json(REFERENCE, REFERENCE_SHA)["cases"]
    source_data = read_sources()
    results = {}
    for contract, day, *_ in CASES:
        trading_day = date.fromisoformat(day)
        symbol = contract[:-4].lower()
        series = read_window(session, market, contract, trading_day)
        market_id = frozen_market(series, contract, ref[contract])
        exchange = market.catalog.exchange_for_symbol(symbol)
        windows = resolved_session_windows_for_trading_day(session, exchange=exchange, symbol=symbol,
                                                          trading_day=trading_day)
        sessions = [(row.window.start, row.window.end) for row in windows]
        atr_inputs = None
        missing = None
        try:
            atr_inputs = read_inputs(session, market, contract, trading_day, resolved_session_windows_for_trading_day)
        except MarketDataError as exc:
            if exc.code != "DATASET_OR_PARTITION_MISSING":
                raise
            missing = exc.code
        except ValueError as exc:
            if str(exc) not in {"ATR_DAILY_PREFIX_UNVERIFIED", "ATR_ZERO_HISTORY", "PRIOR_CLOSE_DAILY_MINUTE_DISAGREEMENT"}:
                raise
            missing = str(exc)
        atr_ref = None
        if atr_inputs is not None:
            if [(b.bar_end, ohlc(b)) for b in atr_inputs["minutes"]] != [(b.end, ohlc(b)) for b in series[1]]:
                raise ValueError("MINUTE_CONTEXT_MARKET_PREFIX_CHANGED")
            atr_ref = dict(atr14_sma=atr_inputs["atr_total"] / PERIOD, daily_anchor=atr_inputs["dailies"][-1].bar_end,
                           daily_sha256=atr_inputs["daily_sha256"], daily_true_ranges=atr_inputs["true_ranges"])
        cases = candidates(series, sessions, atr_inputs, ref[contract])
        results[contract] = dict(contract=contract, trading_day=day, market=market_id, candidates=cases,
                                 price_role=ref[contract]["original_reference_role"],
                                 prefix_checks=3 * len(cases), atr_history=atr_ref, atr_gap=missing,
                                 author_timeframe_switch=None, author_permission=None)
    return dict(version="lms405-minute-recovery-volatility-context-v1", cases=results, sources=source_data,
                candidate_reference_sha256=REFERENCE_SHA, author_activation_labels=0,
                author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None)


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
    except (OSError, KeyError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("MINUTE_CONTEXT_")
                        else "MINUTE_CONTEXT_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
