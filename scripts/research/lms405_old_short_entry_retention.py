"""Separate opening-price and retention constraints for two repeated LMS short legs."""

from argparse import ArgumentParser
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant import lms_near405 as near
from lms405_m_permission_study import read_pair
from lms405_portfolio_origin_window import ALL_DAYS, FROZEN_SCOPE
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_portfolio_task_policy import replay_scoped_policy
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import digest, signals
from lms405_v_ta_case import identity
from lms_near405_replay import encoded, sha

ORIGIN = (Path("output/lms405-portfolio-origin-window-20261126/final-a.json"),
          "0479d3f0df92d440789d3bcb2986d4672e9f325b5ff71c03d7e110da629f96c2")
FIRST_PHOTO = "WRnTlEfj1t"
CASES = {
    "I2701": dict(tick=Decimal("0.5"), display=Decimal("682.50"), lots=16,
                  sources=("S5354683459701283", "A5356507058536457")),
    "SH2701": dict(tick=Decimal(1), display=Decimal("1720.0"), lots=20,
                   sources=("A5355789916438626", "A5356507360788540")),
}


def strict_price(rows, *, since, through, lots, totals, tick):
    """Use complete post-trigger minutes through the stated cutoff."""
    eligible = [bar for bar in rows if since < bar.bar_end - ONE and bar.bar_end <= through]
    bounds = tick_bounds(eligible, tick)
    compatible = bool(earlier_lot_counts(None, bounds, lots, totals))
    first = next((bar.bar_end for bar in eligible
                  if earlier_lot_counts(None, tick_bounds((bar,), tick), lots, totals)), None) if compatible else None
    return dict(minutes=len(eligible), tick_bounds=bounds, price_compatible=compatible,
                first_single_minute_price_compatible_end=first)


def before_first_photo(bars, actions, last_quote):
    """Recover frozen directional decisions up to the last candidate photo quote."""
    state = near.initial_state(bars)
    indexes = {bar.end + 5 * US: index for index, bar in enumerate(bars)}
    trace = []
    for action in actions:
        at = datetime.fromisoformat(action["at"])
        if at >= last_quote:
            break
        if action["action"] not in {"ENTER_LONG", "ENTER_SHORT", "CLEAR"}:
            raise ValueError("OLD_SHORT_NON_DIRECTIONAL_ACTION_BEFORE_PHOTO")
        index = indexes[at]
        proposal = near.evaluate(state, bars[:index + 1], index, managed_lifecycle=True)["proposal"]
        if proposal is None or proposal["action"] != action["action"] or (
            [state["long"], state["short"]] != action["before"]
        ):
            raise ValueError("OLD_SHORT_FROZEN_PROPOSAL_CHANGED")
        state = near._apply(state, proposal, at, None)
        if [state["long"], state["short"]] != action["after"]:
            raise ValueError("OLD_SHORT_FROZEN_STATE_CHANGED")
        trace.append(dict(at=at, action=action["action"], reason=proposal["reason"], plan=proposal["plan"],
                          confirmation_close=bars[index].close, shape_end=proposal["signal_bar_end"]))
    return trace


def attempts(trace, minute_by_day, *, first_quote, last_quote, observed_day, tick, lots, totals):
    results = []
    for index, row in enumerate(trace):
        if row["action"] != "ENTER_SHORT":
            continue
        at = row["at"]
        same_day = next(values for values in minute_by_day.values()
                        if values[0].bar_end <= at <= values[-1].bar_end + 5 * US)
        clear = trace[index + 1] if len(trace) > index + 1 else None
        if clear is not None and clear["action"] != "CLEAR":
            raise ValueError("OLD_SHORT_UNEXPECTED_TRANSITION")
        no_clear_through = min(last_quote - ONE, same_day[-1].bar_end)
        during = min(clear["at"], no_clear_through) if clear else no_clear_through
        trading_day = same_day[0].trading_day
        first_clock, last_clock = first_quote - ONE, last_quote - ONE
        results.append(dict(
            entry=row, trading_day=trading_day, clear=clear, qualifies_as_prior_trading_day=trading_day < observed_day,
            active_before_first_quote_minute=at < first_clock and (clear is None or first_clock <= clear["at"]),
            active_before_last_quote_minute=at < last_clock and (clear is None or last_clock <= clear["at"]),
            price_during_open_leg=strict_price(same_day, since=at, through=during, lots=lots, totals=totals, tick=tick),
            price_if_kept_through_day=strict_price(same_day, since=at, through=no_clear_through,
                                                  lots=lots, totals=totals, tick=tick),
        ))
    return results


def price_candidates(series, minute_by_day, *, first_quote, start, tick, lots, totals, divider_window=None):
    """Keep price-compatible shape clocks for retrospective hypothesis comparison."""
    clocks = {}
    cutoff = min(first_quote - ONE, max(bars[-1].bar_end for bars in minute_by_day.values()) + 2 * US)
    for shape, confirm in ((1, 1), (5, 1), (5, 5)):
        rows = []
        for row in signals(series, shape, confirm, side="SHORT", start=start, cut=cutoff):
            at = row["available_at"]
            day = next((day for day, bars in minute_by_day.items()
                        if bars[0].bar_end <= at <= bars[-1].bar_end + US), None)
            if day is None:
                raise ValueError("OLD_SHORT_SIGNAL_OUTSIDE_SESSION")
            prices = strict_price(minute_by_day[day], since=at, through=first_quote - ONE,
                                  lots=lots, totals=totals, tick=tick)
            if not prices["price_compatible"]:
                continue
            beyond_known_divider = None
            if divider_window is not None:
                known, superseded, divider = divider_window
                beyond_known_divider = known < row["shape_end"] - shape * ONE and at < superseded and row["close"] < divider
            rows.append(dict(signal=row, trading_day=day, fits_opening_price=prices,
                             below_sh_published_divider=beyond_known_divider))
        clocks[f"{shape}m_to_{confirm}m"] = rows
    return clocks


def study(session, market):
    origin = verified_json(*ORIGIN)
    cutoff = datetime.fromisoformat(origin["as_of"])
    days = tuple(day for day in ALL_DAYS if day >= date(2026, 10, 19))
    index = input_sources()
    cases = {}
    for contract, case in CASES.items():
        tick, lots = case["tick"], case["lots"]
        totals = displayed_tick_totals(case["display"], lots, tick)
        frozen = origin["contracts"][contract][days[0].isoformat()]
        raw, series = read_pair(session, market, contract, days)
        fives = [b for b in series[5] if b.end + US <= cutoff]
        if identity(raw[1]) != frozen["market"]["1m"] or digest(fives) != frozen["market"]["5m_prefix_sha256"]:
            raise ValueError("OLD_SHORT_ORIGIN_MARKET_CHANGED")
        actions, *_ = replay_scoped_policy(fives, raw[1], cutoff, index, **FROZEN_SCOPE)
        if json.loads(encoded(actions)) != frozen["actions"]:
            raise ValueError("OLD_SHORT_ORIGIN_ACTIONS_CHANGED")
        row, = (r for r in frozen["comparisons"] if r["source"] == FIRST_PHOTO and r["side"] == "short")
        source = load_source(index, FIRST_PHOTO)
        displayed = row["visible"]
        if (row["source_url"] != source["source_url"] or displayed["quantity"] != lots or displayed["today_quantity"] != 0
                or Decimal(displayed["opening_average"]) != case["display"]):
            raise ValueError("OLD_SHORT_PHOTO_SCOPE_CHANGED")
        quotes = sorted(map(datetime.fromisoformat, row["by_variant"]["strict_replay"]))
        observed_day = date.fromisoformat(row["assumed_trading_day"])
        minute_by_day = {day: [bar for bar in raw[1] if bar.trading_day == day] for day in days if day <= observed_day}
        trace = before_first_photo(fives, actions, quotes[-1])
        prior_trace = [row for row in trace if row["at"] < quotes[0]]
        if before_first_photo(fives, actions, quotes[0]) != prior_trace:
            raise ValueError("OLD_SHORT_TRACE_PREFIX_CHANGED")
        sources = {key: load_source(index, key) for key in case["sources"]}
        for reference in sources.values():
            reference["archive_sha256"] = sha((ARCHIVE.parent / reference["archive_path"]).read_bytes())
        divider_window = None
        if contract == "SH2701":
            published_ends = [datetime.fromisoformat(source["published_at"]).replace(second=0, microsecond=0) + ONE
                              for source in sources.values()]
            divider_window = (*published_ends, Decimal(1726))
        candidates = price_candidates(series, {day: bars for day, bars in minute_by_day.items() if day < observed_day},
                                      first_quote=quotes[0], start=series[1][0].start, tick=tick, lots=lots,
                                      totals=totals, divider_window=divider_window)
        cases[contract] = dict(
            observed=displayed, first_photo=source, quotes=quotes, sources=sources, divider_window=divider_window,
            model_short_attempts=attempts(trace, minute_by_day, first_quote=quotes[0], last_quote=quotes[-1],
                                          observed_day=observed_day, tick=tick, lots=lots, totals=totals),
            price_only_signal_candidates=candidates,
        )
    return dict(version="lms405-old-short-entry-retention-v1", cases=cases, frozen_origin_sha256=ORIGIN[1],
                action_kind="FIXTURE_REPLAY", historical_revisions_verified=False, author_action_samples=0,
                price_candidates_are_retrospective=True, historical_match_rate=None, fills=None, pnl=None,
                executable=False)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.env_file.is_file() or args.output.exists():
        parser.error("ENV_FILE_MISSING_OR_OUTPUT_EXISTS")
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    from sqlalchemy.exc import OperationalError
    from app.db.readonly import readonly_transaction
    from app.db.session import SessionLocal
    from app.market_data.composition import build_market_data_service
    from app.market_data.market_data_service import MarketDataError

    try:
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as out:
            out.write(encoded(report))
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except MarketDataError as error:
        parser.exit(2, f"MDS_BLOCKED: {error.code}\n")
    except (OSError, ValueError, KeyError, StopIteration) as error:
        code = str(error)
        parser.exit(2, f"{code if code.startswith('OLD_SHORT_') and code.isidentifier() else 'OLD_SHORT_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
