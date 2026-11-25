"""Use common price clocks and independent permission for four visible LMS opens and one skip."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405.public_conditions import Condition, check_route
from lms405_jm_m_leg_handoff import BOUNDARIES, formation
from lms405_opening_ebar_audit import market_identity
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import displayed_tick_totals, verified_json
from lms405_protection_timeframes import VARIANTS, read_window
from lms405_replay import read_session_series
from lms405_reversal_stage_bounds import SPECS_SHA
from lms405_right_side_study import ONE, US, at
from lms405_sa_reentry_study import PAIRED_DAYS
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms405_sizing_audit import SPECS, load_specs
from lms405_v_ta_case import identity
from lms405_visible_lock_handoff import stamp
from lms_near405_replay import encoded, sha

REFERENCES = {
    "pta": ("lms405-pta-pause-entry-20261125/final.json", "dd1b685239a92e01296bdb30277b77a6e406b159bec213c09e72863c38062e65"),
    "jm": ("lms405-jm-m-leg-handoff-20261125/final.json", "3f768f34ccacc10739ef168aa119f3b5d6beb8c2fbf6ebe4d31e5caa787719ae"),
    "fg_sa": ("lms405-fg-sa-leg-handoff-20261125/final.json", "4e947ef9365180cb4330016fc18cff6737478c44f0473601f641425e8001d5da"),
    "soda": ("lms-fg-sa-oct-20261125/sa-paired-final.json", "505a0c14baea7759c629be45d9fac1fd1ae216f3ba1286214a7e8da41f97f952"),
    "photos": ("lms-v-ta-oct-20261125/comparison.json", "fcb5f1f9252afa59346910ef843e4d4ddfae682f4580b6acc13935fab22998af"),
    "skip": ("lms405-opening-ebar-20261125/final.json", "0cc02e2319fc4c707cad729a91146610a4e28888161864cfa2fc716faf8c69bc"),
}
NIGHT, SODA_SHORT, SKIP = "WRo2KQ43iX", "WRov1j6e10", "S5341270434121818"
ROUTE = ("OPENING_CONTEXT", "AUTHOR_SIGNAL", "PARTICIPATION_PERMISSION")
LEVEL_SOURCES = {
    "pta_new_long": (None, "PRIOR_COMPLETED_TRADING_DAY_CLOSE"),
    "jm_new_short": ("A5357264059367516", "VISIBLE_PLAN_TEXT_EDIT_HISTORY_UNKNOWN"),
    "soda_new_long": ("A5357264059367516", "VISIBLE_PLAN_TEXT_EDIT_HISTORY_UNKNOWN"),
    "soda_new_short": ("A5358325549629506", "VISIBLE_PLAN_TEXT_EDIT_HISTORY_UNKNOWN"),
    "jm_declined_m": (SKIP, "POST_EVENT_TEXT_RETROSPECTIVE_ONLY"),
}


def boundary_clocks(minutes, level, direction):
    if direction not in {"LONG", "SHORT"} or not minutes:
        raise ValueError("OPENING_CLOCK_INPUT_REQUIRED")
    sign = 1 if direction == "LONG" else -1
    first = minutes[0]
    reach = touch = close = transition = intrabar = None
    previous = None
    for bar in minutes:
        excursion = (bar.high if direction == "LONG" else bar.low) - level
        if reach is None and sign * excursion >= 0:
            reach = bar.end
        if touch is None and bar.low <= level <= bar.high:
            touch = bar.end
        if intrabar is None and sign * excursion > 0:
            intrabar = bar.end
        if sign * (bar.close - level) > 0:
            if close is None:
                close = bar.end
            if (transition is None and previous is not None and previous.end == bar.start
                    and sign * (previous.close - level) <= 0):
                transition = bar.end
        previous = bar
    return dict(level=level, direction=direction, open=first.open,
                open_already_beyond=sign * (first.open - level) > 0,
                first_range_reaches_direction=reach, first_range_contains_level=touch,
                first_intrabar_strict_beyond=intrabar, first_close_strict_beyond=close,
                first_same_segment_new_close_cross=transition)


def permission_replay(scope, contract, as_of, *, context_end, permission=None, context_known_after=None):
    facts = []
    if context_end is not None:
        known = max(context_end + US, context_known_after) if context_known_after else context_end + US
        facts.append(Condition("OPENING_CONTEXT", scope, contract, True, context_end, known,
                               "MDS:completed-price-window", "EVENT_TIME"))
    if permission is not None:
        source, revealed = permission
        # This is the first time the negative report enters this comparison, not the author's decision time.
        facts.append(Condition("PARTICIPATION_PERMISSION", scope, contract, False, revealed, revealed,
                               source, "RESEARCH_READING_TIME_NOT_AUTHOR_BAR_TIME"))
    visible = {fact.name: fact for fact in facts if fact.known_at < as_of}
    return check_route(ROUTE, (), visible)


def window_case(series, start, cut, *, name, contract, direction, levels, observation, permission=None, lot_spec=None):
    scoped = {period: completed(rows, start, cut) for period, rows in series.items()}
    clocks = {key: boundary_clocks(scoped[1], price, travel) for key, (price, travel) in levels.items()}
    gates = {f"{role}:{key}": when for role, row in clocks.items() for key, when in row.items()
             if key.startswith("first_")}
    signal_list = {}
    for shape, confirm in VARIANTS:
        label = f"keybar:{shape}m_to_{confirm}m"
        events = signals(scoped, shape, confirm, side=direction, start=start, cut=cut)
        for event in events:
            split = event["available_at"]
            earlier = signals(scoped, shape, confirm, side=direction, start=start, cut=split)
            if earlier != [row for row in events if row["available_at"] < split]:
                raise ValueError("OPENING_CLOCK_GEOMETRY_PREFIX_CHANGED")
        signal_list[label] = events
        gates[label] = events[0]["confirmed_at"] if events else None
        for role, clock in clocks.items():
            reached = clock["first_range_reaches_direction"]
            fresh = next((row for row in events if reached is not None
                          and reached + US < row["shape_end"] - shape * ONE), None)
            gates[f"{role}:fresh_{shape}m_to_{confirm}m_after_reach"] = fresh["confirmed_at"] if fresh else None
    partial = {}
    def evaluate(key, checked_at):
        # The M range is drawn from the post-session note in the skipped JM window.
        know_at = permission[1] if permission is not None and key.startswith("m_near_retrospective:") else None
        return permission_replay(name, contract, checked_at, context_end=gates[key], permission=permission,
                                 context_known_after=know_at)

    for key, when in gates.items():
        if when is None:
            continue
        verdicts = [evaluate(key, check)
                    for check in (when + US, when + 2 * US)]
        visible_after = None if key.startswith("m_near_retrospective:") else True
        if verdicts[0]["checks"]["OPENING_CONTEXT"] is not None or verdicts[1]["checks"]["OPENING_CONTEXT"] is not visible_after:
            raise ValueError("OPENING_CLOCK_STRICT_BEFORE_CHANGED")
        partial[key] = verdicts
    states = {key: evaluate(key, cut) for key in gates}
    final_end = series[1][-1].end
    states["FULL_TRADING_DAY_CLOSE"] = permission_replay(name, contract, cut, context_end=final_end, permission=permission)
    bounds = None
    lot_evidence = None
    if lot_spec is not None:
        quantity, average, tick, mark, captures = lot_spec
        totals = displayed_tick_totals(average, quantity, tick)
        lot_evidence = dict(quantity=quantity, displayed_average=average, tick=tick, possible_total_ticks=list(totals))
        available = {bar.end: bar for bar in scoped[1]}
        if any(not available[when].low <= mark <= available[when].high for when in captures):
            raise ValueError("OPENING_CLOCK_QUOTE_RECHECK_FAILED")
        bounds = {key: {scope: formation(scoped[1], captures, when, boundary=scope,
                                         tick=tick, lots=quantity, totals=totals)
                        for scope in BOUNDARIES} for key, when in gates.items()}
    late = None
    if permission is not None:
        _, revealed = permission
        if revealed <= cut:
            raise ValueError("OPENING_CLOCK_SKIP_MUST_BE_LATE")
        late = {key: evaluate(key, revealed + US) for key in gates}
    return dict(contract=contract, start=start, cutoff_exclusive=cut, direction=direction, observation=observation,
                market={f"{p}m": digest(rows) for p, rows in series.items()}, scoped_minute_count=len(scoped[1]),
                clocks=clocks, geometric_candidates=signal_list, gates=gates, known_conditions_at_window_end=states,
                post_event_negative_review=late, verified_event_prefixes=partial, lot_formation_bounds=bounds,
                lot_evidence=lot_evidence,
                full_trading_day_end=final_end, capture_boundaries=lot_spec[-1] if lot_spec else None,
                author_signal_at=None, actual_action_at=None)


def load_cases(refs, specs):
    pta, jm, pair, photos = (refs[x] for x in ("pta", "jm", "fg_sa", "photos"))

    def position(row, contract, mark, quotes, *, display_price=None):
        lots = row["quantity"]
        if row["today_quantity"] != lots:
            raise ValueError("OPENING_CLOCK_TODAY_SCOPE_CHANGED")
        shown = Decimal(display_price) if display_price is not None else Decimal(row["opening_average"])
        if shown != Decimal(row["opening_average"]):
            raise ValueError("OPENING_CLOCK_DISPLAY_AVERAGE_CHANGED")
        return (lots, shown, specs[contract]["tick"], Decimal(mark),
                [datetime.fromisoformat(mark) for mark in quotes])

    short_row = refs["soda"]["short"]["observed"][SODA_SHORT]
    short_table = dict(quantity=int(short_row["quantity"]), today_quantity=int(short_row["today_quantity"]),
                       opening_average=short_row["average"])
    return (
        ("pta_new_long", "TA2701", "2026-10-26", "2026-10-23T21:00", NIGHT, "LONG", "PUBLIC_ZONE_UNAVAILABLE",
         {"previous_close_retest": (Decimal(pta["gap"]["prior_close"]), "SHORT")},
         position(pta["snapshot"]["legs"]["long"], "TA2701", pta["row_mark"]["price"], pta["row_mark"]["quote_captures"],
                  display_price=pta["opening_average_as_displayed"])),
        ("jm_new_short", "JM2701", "2026-10-26", "2026-10-23T21:00", NIGHT, "SHORT", "VISIBLE_NEW_SHORT",
         {"divider_near": (Decimal("1415.5"), "SHORT"), "divider_far": (Decimal(1392), "SHORT")},
         position(jm["visible"][NIGHT]["legs"]["short"], "JM2701", 1397, jm["anchors"][NIGHT])),
        ("soda_new_long", "SA2701", "2026-10-26", "2026-10-23T21:00", NIGHT, "LONG", "VISIBLE_NEW_LONG",
         {"divider_far": (Decimal(957), "LONG")},
         position(pair["positions"]["SA2701"][NIGHT]["legs"]["long"], "SA2701", 968,
                  pair["quote_anchors"]["SA2701"][NIGHT])),
        ("soda_new_short", "SA2701", "2026-10-27", "2026-10-26T21:00", SODA_SHORT, "SHORT", "VISIBLE_NEW_SHORT",
         {"divider_near": (Decimal(957), "SHORT"), "divider_far": (Decimal(951), "SHORT")},
         position(short_table, "SA2701", 957, photos["photos"][SODA_SHORT]["per_symbol"]["sa"]["contains"],
                  display_price="960.0")),
        ("jm_declined_m", "JM2701", "2026-09-09", "2026-09-09T09:00", SKIP, "SHORT", "RETROSPECTIVE_EXPLICIT_SKIP",
         {"m_near_retrospective": (Decimal("1663.5"), "SHORT")}, None),
    )


def study(session, market):
    refs = {key: verified_json(Path("output") / name, expected) for key, (name, expected) in REFERENCES.items()}
    specs = load_specs(verified_json(SPECS, SPECS_SHA))
    raw_soda = read_session_series(session, market, "sa", "SA2701", "1m", ONE, PAIRED_DAYS)
    if identity(raw_soda) != refs["soda"]["frozen_inputs"]["1m"]:
        raise ValueError("OPENING_CLOCK_SODA_INPUT_CHANGED")
    index = input_sources()
    source_ids = (NIGHT, SODA_SHORT, SKIP, "WRnThF3x5C", "A5357264793370945", "A5357264059367516", "A5358325549629506")
    sources = {key: index[key] | dict(archive_sha256=sha((ARCHIVE.parent / index[key]["archive_path"]).read_bytes()))
               for key in source_ids}
    cases = {}
    for name, contract, day, open_at, post, side, label, levels, lot_spec in load_cases(refs, specs):
        series = read_window(session, market, contract, date.fromisoformat(day))
        if contract == "SA2701":
            expected = [(row.bar_end, row.open, row.high, row.low, row.close) for row in raw_soda if row.trading_day.isoformat() == day]
            if expected != [(bar.end, bar.open, bar.high, bar.low, bar.close) for bar in series[1]]:
                raise ValueError("OPENING_CLOCK_SODA_DAY_CHANGED")
        elif post == SKIP:
            if market_identity(series) != refs["skip"]["cases"][contract]["market"]:
                raise ValueError("OPENING_CLOCK_SKIP_INPUT_CHANGED")
        else:
            prior = (refs["pta"]["market"]["1m"]["sha256"] if contract == "TA2701" else refs["jm"]["markets"][day]["1m"]["sha256"])
            if prior != digest(series[1]):
                raise ValueError("OPENING_CLOCK_FROZEN_DAY_CHANGED")
        source = sources[post]
        published = stamp(source)
        permission = (source["source_url"], published + ONE) if post == SKIP else None
        cut = at("2026-09-09T10:15:00.000002") if post == SKIP else published
        level_source, scope = LEVEL_SOURCES[name]
        start = at(open_at)
        if scope == "VISIBLE_PLAN_TEXT_EDIT_HISTORY_UNKNOWN" and stamp(sources[level_source]) + ONE > start:
            raise ValueError("OPENING_CLOCK_PLAN_PUBLISHED_AFTER_OPEN")
        replay = window_case(series, start, cut, name=name, contract=contract, direction=side,
                             levels=levels, observation=label, permission=permission, lot_spec=lot_spec)
        cases[name] = replay | dict(level_source_id=level_source, level_scope=scope,
                                    negative_report_publication_minute_end=permission[1] if permission else None)
    return dict(version="lms405-opening-clock-comparison-v1", cases=cases, sources=sources,
                reference_hashes={key: digest for key, (_, digest) in REFERENCES.items()},
                raw_price_clocks_are_research_hypotheses=True, author_signal_equivalence=None,
                admitted_author_actions=0, author_match_rate=None, executable=False, fills=None, pnl=None)


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
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('OPENING_CLOCK_') and code.isidentifier() else 'OPENING_CLOCK_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
