"""Compare recovery clocks after a visible lock without inferring the author's account state."""

import argparse
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Action, Position, Zone, apply_action
from guiyi_quant.lms405.handoff import Handoff, assess_handoff
from guiyi_quant.lms405.recovery_path import RecoveryPlan
from lms405_common_protection_window import OCT27_QUOTES
from lms405_i2701_case import FROZEN_COMPARISON_SHA256
from lms405_oi_leg_intent import CONTINUITY, CONTINUITY_SHA
from lms405_portfolio_replay import ARCHIVE
from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import VARIANTS, read_window
from lms405_recovery_confirmation_audit import ORIGINAL, ORIGINAL_SHA, strict_runs
from lms405_recovery_signal_study import compare
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest
from lms405_visible_lock_handoff import stamp
from lms_near405_replay import encoded, sha

DAYS = date(2026, 10, 27), date(2026, 10, 28)
CASES = (
    ("iron_afternoon", "I2701", DAYS[0], "WRoAkcEppg", "U03", "A5358325549629506", "668.5 671.5", "654 662.5",
     "PUBLISHED_STRONG_SIDE_RECOVERY", "2026-10-27T15:00"),
    ("sh_afternoon", "SH2701", DAYS[0], "WRoAkcEppg", "U03", "A5358325972992140", "1511 1516", "1506 1520",
     "EARLIER_RESISTANCE_AS_RECOVERY_PROXY", "2026-10-27T15:00"),
    ("iron_night", "I2701", DAYS[1], "U03", "WRoEvasxQR", "A5358686423089344", "668.5 671.5", "654 662.5",
     "PUBLISHED_STRONG_SIDE_RECOVERY", "2026-10-27T22:12"),
)
CLOCKS = {
    "CONFIRMATION_CLOSE": "recovery_at_confirmation",
    "BEFORE_CONFIRMATION": "recovery_strictly_before_confirmation_start_same_run",
    "BEFORE_SHAPE": "recovery_strictly_before_shape_start_same_run",
}
# The U03 archive added glass and PVC software-report notes. Its two studied position rows and image are unchanged.
U03_CURRENT_SHA = "1cd9686676d3bb87de6947e84ab919d2b73c77497b4dff22c373172564912d5f"


def positions(continuity, contract, first, last):
    (transition,) = [row for row in continuity["contracts"][contract]["transitions"]
                     if (row["earlier"], row["later"]) == (first, last)]
    before, after = transition["earlier_legs"], transition["later_legs"]
    if set(before) != {"long", "short"} or before["short"]["today_quantity"] != 0 or (
        before["short"]["quantity"] != before["long"]["quantity"]
    ):
        raise ValueError("SEEDED_CLOCK_LOCK_VISIBLE_SCOPE_CHANGED")
    photos = {}
    for key in (first, last):
        item = continuity["sources"][key]
        image = item["image"]
        if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
            raise ValueError("SEEDED_CLOCK_IMAGE_CHANGED")
        photos[key] = {name: item[name] for name in ("image", "binding", "quote_anchor", "trading_day")}
    return Position(contract, Decimal(before["long"]["quantity"]), Decimal(before["short"]["quantity"])), (
        before, after, photos,
    )


def selection_rows(series, plan, start, cut, mark_minutes):
    full = {f"{shape}m_to_{confirm}m": compare(series, plan, shape, confirm, cut) for shape, confirm in VARIANTS}
    records = [event | dict(variant=variant) for variant, rows in full.items() for event in rows]
    records.sort(key=lambda event: event["available_at"])
    cutoffs = {event["available_at"] for event in records} | set(mark_minutes)
    for split in sorted(cutoffs):
        for shape, confirm in VARIANTS:
            ref = full[f"{shape}m_to_{confirm}m"]
            if compare(series, plan, shape, confirm, split) != [event for event in ref if event["available_at"] < split]:
                raise ValueError("SEEDED_CLOCK_CAUSAL_PREFIX_DIVERGED")

    # A sequence may start a session already beyond the edge. Preserve the fresh-crossing alternative.
    runs = strict_runs(completed(series[1], start, cut), plan.recovery.lower, plan.side)
    for event in records:
        run = runs.get(event["confirmed_at"])
        event["fresh_crossing_known_at"] = run["fresh_crossing_known_at"] if run is not None else None
        event["available_before_whole_quote_minutes"] = (
            sum(event["available_at"] + US < end - ONE for end in mark_minutes) if mark_minutes else None
        )
    return records, len(cutoffs)


def projection(position, end_rows, event, mark_minutes):
    result = apply_action(position, Action("UNLOCK_SHORT", position.long)) if event else position
    return dict(
        candidate=event, projected_if_one_fixture_action_and_no_later_actions=dict(long=result.long, short=result.short),
        visible_quantities_agree={side: getattr(result, side) == row["quantity"] for side, row in end_rows.items()},
        observed_both_legs=len(end_rows) == 2,
        first_minute_with_potential_quote=mark_minutes[0] if mark_minutes else None,
        hypothetical_action_before_complete_quote_minutes=event["available_before_whole_quote_minutes"] if event else None,
        quote_minute_candidates=len(mark_minutes) if mark_minutes else None,
        author_permission=None, observed_author_action=None,
    )


def study(session, market):
    original = verified_json(ORIGINAL, ORIGINAL_SHA)
    continuity = verified_json(CONTINUITY, CONTINUITY_SHA)
    quotes = verified_json(OCT27_QUOTES, FROZEN_COMPARISON_SHA256)
    series_by_contract = {}
    results = {}
    for name, contract, day, first, last, plan_id, raw_band, raw_target, role, end in CASES:
        sources = {}
        for key in (first, last, plan_id):
            source = original["sources"][key]
            current = sha((ARCHIVE.parent / source["archive_path"]).read_bytes())
            expected = U03_CURRENT_SHA if key == "U03" else source["archive_sha256"]
            if current != expected:
                raise ValueError("SEEDED_CLOCK_SOURCE_CHANGED")
            sources[key] = source | dict(current_archive_sha256=current)
        position, (before, later, photos) = positions(continuity, contract, first, last)
        start = max(stamp(sources[first]), stamp(sources[plan_id])) + ONE
        cut = at(end)
        if photos[last]["quote_anchor"] is not None and datetime.fromisoformat(photos[last]["quote_anchor"]) != cut:
            raise ValueError("SEEDED_CLOCK_END_ANCHOR_CHANGED")
        if contract not in series_by_contract:
            series_by_contract[contract] = {d: read_window(session, market, contract, d) for d in DAYS}
            for period in (1, 5):
                rows = [bar for d in DAYS for bar in series_by_contract[contract][d][period]]
                if dict(count=len(rows), sha256=digest(rows)) != original["market"][contract][f"{period}m"]:
                    raise ValueError("SEEDED_CLOCK_FROZEN_MARKET_CHANGED")
        bars = series_by_contract[contract][day]
        mark_minutes = tuple(datetime.fromisoformat(value) for value in
                             quotes["photos"][last]["per_symbol"]["i"]["contains"]) if name == "iron_night" else ()
        if mark_minutes:
            mark = Decimal(quotes["photos"][last]["per_symbol"]["i"]["mark"])
            by_end = {bar.end: bar for bar in bars[1]}
            if any(not (x + US < cut and by_end[x].low <= mark <= by_end[x].high) for x in mark_minutes):
                raise ValueError("SEEDED_CLOCK_NIGHT_QUOTE_CHANGED")
        seed = Handoff("RESUME_ORIGINAL", position, "SHORT", f"{name}:plan", f"{name}:cycle", None, start, start)
        public = assess_handoff(seed, (), as_of=cut, source=plan_id, source_available_at=start, version_405=None)
        if public["after"] is not None:
            raise ValueError("SEEDED_CLOCK_ACTION_WITHOUT_PUBLIC_FACTS")
        lower, upper = map(Decimal, raw_band.split())
        target_lo, target_hi = map(Decimal, raw_target.split())
        target = Zone("author_target", contract, target_lo, target_hi, start - US, plan_id)
        by_edge = {}
        for label, price in (("near", upper), ("far", lower)):
            plan = RecoveryPlan("SHORT", Zone(label, contract, price, price, start - US, plan_id), (target,))
            events, checks = selection_rows(bars, plan, start, cut, mark_minutes)
            modes = {}
            for name_of_clock, flag in CLOCKS.items():
                passed = [event for event in events if event[flag] and event["available_at"] + US < cut]
                modes[name_of_clock] = dict(
                    price_run=projection(position, later, next(iter(passed), None), mark_minutes),
                    fresh_run=projection(position, later, next((e for e in passed if e["fresh_crossing_known_at"]), None),
                                         mark_minutes),
                )
            single_close = next((event for event in events if event["close"] < price
                                 and event["available_at"] + US < cut), None)
            by_edge[label] = dict(price=price, events=events, checked_prefixes=checks, modes=modes,
                                  shape_and_single_close=projection(position, later, single_close, mark_minutes))
        results[name] = dict(contract=contract, start=start, cut=cut, sources=sources, photos=photos,
                             before_visible=before, later_visible=later, original_side_hypothesis="SHORT",
                             price_role=role, account_continuity=None, author_assessment=public,
                             quote_minutes=mark_minutes, edges=by_edge)
    return dict(version="lms405-seeded-recovery-clocks-v1", cases=results, author_action_samples=0,
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.startswith("SEEDED_CLOCK_") and code.isidentifier()
                        else "SEEDED_CLOCK_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
