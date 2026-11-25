"""Compare completed-price hypotheses with an author's high-difficulty M case."""

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Bar
from lms405_fg_sa_case import identity
from lms405_hold_clock_study import compare
from lms405_locked_exit_audit import verify_aggregation
from lms405_protection_timeframes import geometry_events
from lms405_replay import display, ohlc, read_session_series
from lms405_right_side_study import FIVE, ONE, US, at
from lms405_sa_reentry_study import source_evidence
from lms405_volatility_context import METRICS, PERIOD, minute_context, read_inputs
from lms_near405_replay import encoded

CONTRACT = "JM2701"
SEPTEMBER = tuple(date(2026, 9, value) for value in (7, 8, 9, 10))
OCTOBER = (date(2026, 10, 23),)
NEGATIVE = SEPTEMBER[2]
POSITIVE = OCTOBER[0]
SOURCE_HASHES = {
    "S5341270434121818": "7572cd44e11e109cbc481308cece8875b967e2bd22a327b94596170f94b1cad2",
    "WRo0OCbeQG": "85d00788723516a8053017b8657a53f01b3b0f4098f3956866a88eabb64ed2da",
}
MARKET_5M = {
    SEPTEMBER: "37bf727d336611bf04838e59379f1c90773139f92bb5dae9bf1a6328877fa9b2",
    OCTOBER: "d7a9e5a4567d353e5f5816b44972426b0b77af68689a1d28e2f2773fbd6da94c",
}
METRIC_INPUT_HASHES = {
    SEPTEMBER[1]: ("c73061b27b2f3fd9210cb2900e5c2f0e87008a8ad1577e03e52b079e9fb4e884",
                   "e98f87545e507153ac7d86df0dc3b5e8b4b0fca93c3b0d63cd620c58a7b0ee72"),
    NEGATIVE: ("d0db62f61caf23dd422b3b5aa2a53aa8bd65d8b38e1646f77543179ba2bcd9f3",
               "dcef88aa7208e28856314b898a36354a062c50c5b98f67a914e1b0bea5985aa3"),
    SEPTEMBER[3]: ("965f25378b2032188f1950d3ea3068b2b79ab0a604d69552e24292ffd813d4d7",
                   "131887630babb9af62e3aef209816289c838de434a25cd0eb0186d9a8a81e996"),
    POSITIVE: ("133c90a735f864f09b13ad3573abedfa179e3b47fa7ec971e250abc8a8549757",
               "176849eb2cf76813b7be5e34ca6a0484d70cd8ee3b04a5868d30a7b3ef51433c"),
}
BANDS = {
    NEGATIVE: ("SHORT", ("1657", "1663.5"), ("1619", "1627.5")),
    POSITIVE: ("LONG", ("1410.5", "1420"), ("1420.5", "1427.5")),
}


def fresh_candidates(events, shape_period, contact_at, band, side):
    """Keep only a whole shape starting after the contact was knowable."""
    result = []
    for event in events:
        if event["shape_end"] - timedelta(minutes=shape_period) <= contact_at + US:
            continue
        close = event["close"]
        result.append(event | dict(inside_m=band[0] <= close <= band[1],
                                   beyond_m=close < band[0] if side == "SHORT" else close > band[1]))
    return result


def retrospective_bands(day, minutes, fives, start, cutoff):
    side, raw_m, raw_extreme = BANDS[day]
    band, extreme = tuple(map(Decimal, raw_m)), tuple(map(Decimal, raw_extreme))
    m_touch = next((b.bar_end for b in minutes if b.low <= band[1] and b.high >= band[0]), None)
    extreme_touch = next((b.bar_end for b in minutes if b.low <= extreme[1] and b.high >= extreme[0]), None)
    series = {1: [Bar(CONTRACT, b.bar_end, *ohlc(b), start=b.bar_end - ONE) for b in minutes], 5: fives}
    variants = {}
    for shape, confirm in ((1, 1), (5, 1), (5, 5)):
        events = geometry_events(series, shape, confirm, start=start, as_of=cutoff, side=side)
        variants[f"{shape}m_to_{confirm}m"] = dict(
            events=events,
            fresh_after_m_contact=fresh_candidates(events, shape, m_touch, band, side) if m_touch else [],
        )
    return dict(side=side, m=band, extreme_m=extreme, first_m_contact=m_touch,
                first_extreme_m_contact=extreme_touch, geometry=variants)


def inspect_day(day, session_input, fives, replay):
    if (session_input["minute_sha256"], session_input["daily_sha256"]) != METRIC_INPUT_HASHES[day]:
        raise ValueError("DIFFICULTY_CONTEXT_INPUT_CHANGED")
    start, cutoff = at(f"{day}T09:00"), at(f"{day}T15:01")
    minutes = session_input["minutes"]
    day_minutes = [b for b in minutes if start < b.bar_end < cutoff]
    if len(day_minutes) != 225 or session_input["day_reopen"] != day_minutes[0].bar_end:
        raise ValueError("DIFFICULTY_DAY_SESSION_CHANGED")
    day_fives = [b for b in fives if start < b.end < cutoff]
    verify_aggregation(day_fives, minutes)
    last = session_input["dailies"][-1]
    rows = minute_context(minutes, initial_close=last.close, atr_total=session_input["atr_total"],
                          day_reopen_end=session_input["day_reopen"], as_of=cutoff)
    first_seen = {key: next((display(row["bar_end"]) for row in rows if row["exceeds_atr14"][key]), None)
                  for key in METRICS}
    proposals = []
    for p in replay["proposals"]:
        when = datetime.fromisoformat(p["generated_at"])
        if not start < when < cutoff:
            continue
        before = next(row for row in reversed(rows) if row["known_at"] < when)
        proposals.append(dict(time=when, action=p["action"], reason=p["reason"],
                              measure_at=before["bar_end"], exceeds_atr14=before["exceeds_atr14"]))
    return dict(
        trading_day=day.isoformat(), prior_trading_day_close=last.close,
        day_open=day_minutes[0].open, day_open_vs_prior_trading_day_close=day_minutes[0].open - last.close,
        night_close=next(b.close for b in reversed(minutes) if b.bar_end < start),
        night_open_gap=rows[-1]["open_gap_signed"], day_reopen_gap=rows[-1]["day_reopen_gap_signed"],
        first_day_1m=ohlc(day_minutes[0]), first_day_5m=ohlc(day_fives[0]),
        day_low=min(b.low for b in day_minutes), day_high=max(b.high for b in day_minutes),
        atr14=session_input["atr_total"] / PERIOD, true_range_at_cut=rows[-1]["measures"]["trading_day_true_range"],
        first_exceeds_atr14=first_seen, minute_sha256=session_input["minute_sha256"],
        daily_sha256=session_input["daily_sha256"], baseline_fixture_proposals=proposals,
        retrospective_bands=retrospective_bands(day, day_minutes, day_fives, start, cutoff) if day in BANDS else None,
    )


def study(session, market, evidence, resolver):
    results = {}
    for days in (SEPTEMBER, OCTOBER):
        raw = read_session_series(session, market, "jm", CONTRACT, "5m", FIVE, days)
        five_input = identity(raw)
        if five_input["ohlc_sha256"] != MARKET_5M[days]:
            raise ValueError("DIFFICULTY_FROZEN_FIVES_CHANGED")
        fives = [Bar(CONTRACT, b.bar_end, *ohlc(b), start=b.bar_end - FIVE) for b in raw]
        replay = compare(fives, None, as_of=fives[-1].end + 3 * US)
        for day in days:
            if day in METRIC_INPUT_HASHES:
                inp = read_inputs(session, market, CONTRACT, day, resolver)
                results[day.isoformat()] = inspect_day(day, inp, fives, replay) | dict(replay_input=five_input)
    return dict(
        version="lms405-m-difficulty-study-v1", contract=CONTRACT, sources=evidence, cases=results,
        author_case_scope={NEGATIVE.isoformat(): dict(source="S5341270434121818", role="DIFFICULTY_SKIP_REPORTED"),
                           POSITIVE.isoformat(): dict(source="WRo0OCbeQG", role="SHORT_TERM_TRIAL_REPORTED")},
        author_report_time_used_as_signal=False, exact_author_opportunity_window=None,
        candidate_threshold="PRIOR_ATR14_COMPARISON_ONLY", difficulty_formula=None,
        admitted_author_samples=0, author_matches=None, fills=None, pnl=None, executable=False,
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
    from app.market_data.session_clock import resolved_session_windows_for_trading_day
    from sqlalchemy.exc import OperationalError

    try:
        evidence = source_evidence(SOURCE_HASHES, {})
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            result = study(session, build_market_data_service(session), evidence, resolved_session_windows_for_trading_day)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(result))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError, StopIteration):
        parser.exit(2, "DIFFICULTY_SOURCE_OR_PRICE_COVERAGE_UNVERIFIED\n")


if __name__ == "__main__":
    main()
