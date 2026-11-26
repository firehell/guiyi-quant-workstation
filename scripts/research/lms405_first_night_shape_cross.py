"""Compare a completed five-minute keybar's intraminute breach with close confirmation."""

from argparse import ArgumentParser
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms_keybar_approx import classify
from lms405_first_night_confirmation_clocks import DAY, POST, START, price_envelope
from lms405_first_night_pa import REFERENCE, REFERENCE_HASH
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_replay import display, ohlc
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import completed, digest
from lms_near405_replay import encoded, sha

PA = "WRnThF3x5C"
PHOTO = "WRnTlEfj1t"


def breaches(fives, minutes, start, cutoff):
    """Record the first breach in the next five minutes as an OHLC observation."""
    eligible = {bar.start: bar for bar in completed(minutes, start, cutoff)}
    rows = []
    for mother, shape in zip(fives, fives[1:]):
        if shape.end + US >= cutoff:
            break
        if shape.start < start or mother.end != shape.start:
            continue
        frame = classify(mother, shape)
        if not (frame.ibar or frame.pinbar == "LONG"):
            continue
        for offset in range(5):
            minute = eligible.get(shape.end + offset * ONE)
            if minute is None:
                break
            if minute.high > shape.high:
                rows.append(dict(
                    mother_end=mother.end, mother_ohlc=ohlc(mother), shape_end=shape.end, shape_ohlc=ohlc(shape),
                    ibar=frame.ibar, pinbar=frame.pinbar, boundary=shape.high,
                    breach_start=minute.start, breach_end=minute.end, breach_ohlc=ohlc(minute),
                    first_open_above=minute.open > shape.high,
                    within_minute_upward_cross_proven=minute.open <= shape.high or minute.low <= shape.high < minute.close,
                    observation_known_at=minute.end + US, actual_cross_at=None,
                ))
                break
    return rows


def price_bounds(minutes, breach, quote_end, *, tick, lots, totals):
    prefix = [bar for bar in minutes if bar.end <= quote_end]
    boundary = breach["breach_end"]
    if boundary > quote_end:
        raise ValueError("FIRST_SHAPE_BREACH_AFTER_QUOTE")
    before = [bar for bar in prefix if bar.end < boundary]
    through = [bar for bar in prefix if bar.end <= boundary]
    including_breach = [bar for bar in prefix if bar.end >= boundary]
    after = [bar for bar in prefix if bar.end > boundary]
    before_breach = earlier_lot_counts(tick_bounds(before, tick), tick_bounds(including_breach, tick), lots, totals)
    through_breach = earlier_lot_counts(tick_bounds(through, tick), tick_bounds(after, tick), lots, totals)
    quote_lots = earlier_lot_counts(tick_bounds(prefix[-1:], tick), tick_bounds(prefix[:-1], tick), lots, totals)
    # Sensitivity only: retain every price in the first invalidation minute.
    shape_low = breach["shape_ohlc"][2]
    invalidation = next((bar for bar in after if bar.close < shape_low), None)
    needs_after_invalidation = None
    if invalidation is not None:
        until = [bar for bar in including_breach if bar.end <= invalidation.end]
        beyond = [bar for bar in after if bar.end > invalidation.end]
        counts = earlier_lot_counts(tick_bounds(before + until, tick), tick_bounds(beyond, tick), lots, totals)
        needs_after_invalidation = lots - max(counts) if counts else None
    completed_observation = price_envelope(prefix, {"available_at": breach["observation_known_at"]},
                                           tick, lots, totals, quote_end)
    return dict(
        minimum_lots_before_breach_minute=min(before_breach, default=None),
        minimum_lots_after_breach_minute=lots - max(through_breach) if through_breach else None,
        minimum_lots_in_quote_minute=min(quote_lots, default=None),
        first_later_close_below_shape_low=invalidation.end if invalidation else None,
        minimum_lots_after_invalidation_minute=needs_after_invalidation,
        after_breach_observed=completed_observation,
    )


def study(session, market):
    reference = verified_json(REFERENCE, REFERENCE_HASH)
    index = input_sources()
    photo = reference["photo"]
    if (sha((ARCHIVE.parent / photo["path"]).read_bytes()) != photo["sha256"]
            or load_source(index, PHOTO) != reference["photo_source"]):
        raise ValueError("FIRST_SHAPE_PHOTO_CHANGED")
    results, checks = {}, 0
    for contract, case in reference["cases"].items():
        series = read_window(session, market, contract, DAY)
        if {f"{p}m": digest(rows) for p, rows in series.items()} != case["market"]:
            raise ValueError("FIRST_SHAPE_MARKET_CHANGED")
        minutes = completed(series[1], START, POST)
        candidates = breaches(series[5], minutes, START, POST)
        tick, lots = Decimal(case["tick"]), case["displayed_long"]["quantity"]
        totals = displayed_tick_totals(Decimal(case["average"]), lots, tick)
        mark = Decimal(case["quote"])
        anchors = [b.end for b in minutes if b.low <= mark <= b.high]
        if anchors != [datetime.fromisoformat(value) for value in case["individual_quote_ends"]]:
            raise ValueError("FIRST_SHAPE_QUOTE_CHANGED")
        quoted = {}
        for end in anchors:
            # Both sides of quote-minute visibility are tested. Only the earlier cutoff uses known evidence.
            for cutoff in (end, end + 2 * US):
                found = breaches(series[5], minutes, START, cutoff)
                expected = [row for row in candidates if row["observation_known_at"] < cutoff]
                if found != expected:
                    raise ValueError("FIRST_SHAPE_PREFIX_DIVERGED")
                checks += 1
            first = next((row for row in candidates if row["observation_known_at"] < end), None)
            quoted[display(end)] = dict(
                first_observed_breach=first,
                bounds=price_bounds(minutes, first, end, tick=tick, lots=lots, totals=totals) if first else None,
            )
        results[contract] = dict(
            visible_long=case["displayed_long"], protection_band=case["protection_band"], market=case["market"],
            quote_mark=mark, plan=case["plan"], breaches=candidates, by_quote_minute=quoted,
            completed_close_confirmations={key: value["events"] for key, value in case["clocks"].items()},
        )
    return dict(
        study="FIVE_MINUTE_SHAPE_WITH_INTRAMINUTE_BREACH_PRICE_OBSERVATION",
        first_night_reference_sha256=REFERENCE_HASH, photo=photo, photo_source=reference["photo_source"],
        pa_comment=load_source(index, PA), trading_day=DAY, cases=results, quote_visibility_checks=checks,
        author_action_samples=0, author_match_rate=None, actual_quote_time=None, executable=False, fills=None, pnl=None,
    )


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
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
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("FIRST_SHAPE_")
                        else "FIRST_SHAPE_SOURCE_OR_MARKET_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
