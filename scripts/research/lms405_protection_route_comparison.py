"""Compare advance and ordinary protection on fixed carried shorts with quote-prefix checks."""

import argparse
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant.lms405 import Action, Event, Position, replay_events
from guiyi_quant.lms405.public_conditions import PublicCase
from lms405_first_night_early_protection import touched
from lms405_first_night_pa import REFERENCE, REFERENCE_HASH
from lms405_portfolio_leg_audit import scoped_input_quotes
from lms405_portfolio_replay import ARCHIVE, CONTRACTS
from lms405_protection_layers_replay import ORDER, ROUTES, fact, trace
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_next_night_replay import PROTECTION, TOUCH, TOUCH_SHA
from lms405_protection_quote_bounds import CAUSTIC_REFERENCE, CAUSTIC_SHA, gate_price_support
from lms405_protection_timeframes import VARIANTS, read_window
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms_near405_replay import encoded, sha

VERSION = "lms405-protection-route-comparison-v1"
WICK_VERSION = "lms405-protection-route-wick-comparison-v1"
FROZEN_ROUTES = (Path("output/lms405-protection-route-comparison-20261125/checked.json"),
                 "f71a5a8a6bfd444c67d7f349cd97ccea3b21556904225569a595067a96dd6abe")
FROZEN_LOCATIONS = (Path("output/lms405-protection-location-20261125/final.json"),
                    "70b1f43e9980383a6ba8f1e67a14a4aa0dca358dc90bb64ceb37b0539e8a9677")
ROUTE_MODES = {
    "public_only": (),
    "ordinary_only": ("ordinary",),
    "advance_at_contact": ("contact",),
    "advance_from_open": ("opening",),
    "advance_on_precontact_geometry": ("precontact",),
    "either_on_geometry": ("ordinary", "precontact"),
    "either_from_contact": ("ordinary", "contact"),
}
WICK_BRANCHES = {pair: f"wick_{pair[0]}m_to_{pair[1]}m" for pair in VARIANTS}
WICK_MODES = {
    **{name: (name,) for name in WICK_BRANCHES.values()},
    "wick_only": tuple(WICK_BRANCHES.values()),
    "geometry_with_wick": (*ROUTE_MODES["either_on_geometry"], *WICK_BRANCHES.values()),
}


def wick_beyond(ohlc, confirmed, band, *, side):
    opened, high, low, closed = ohlc
    lower, upper = band
    if side == "LONG":
        return low <= upper < min(opened, closed) and confirmed > upper
    if side == "SHORT":
        return high >= lower > max(opened, closed) and confirmed < lower
    raise ValueError("PROTECTION_ROUTE_WICK_SIDE_INVALID")


def candidate_clocks(series, band, *, start, cutoff, compare_wick=False):
    minutes = completed(series[1], start, cutoff)
    contact = touched(minutes, band)
    if band is None or not minutes:
        return {}, contact
    opening_signal = minutes[0].end + 2 * US
    candidates = {"opening": opening_signal} if opening_signal < cutoff else {}
    per_period = {pair: signals(series, *pair, side="LONG", start=start, cut=cutoff) for pair in VARIANTS}
    events = [event for group in per_period.values() for event in group]
    # A touch in a still-forming minute is not a fact at the confirmation clock.
    advancing = min((event["available_at"] for event in events
                     if (contact is None or event["available_at"] < contact.end + US)
                     and event["close"] < band[0]), default=None)
    if advancing is not None:
        candidates["precontact"] = advancing
    if contact is not None:
        known = contact.end + US
        if known + US < cutoff:
            candidates["contact"] = known + US
        ordinary = min((event["available_at"] for event in events
                        if known < event["available_at"] and band[0] <= event["close"] <= band[1]), default=None)
        if ordinary is not None:
            candidates["ordinary"] = ordinary
        if compare_wick:
            for pair, group in per_period.items():
                by_end = {bar.end: bar for bar in series[pair[0]]}
                for event in group:
                    shape = by_end[event["shape_end"]]
                    if known < event["available_at"] and wick_beyond(
                        (shape.open, shape.high, shape.low, shape.close), event["close"], band, side="LONG",
                    ):
                        candidates[WICK_BRANCHES[pair]] = event["available_at"]
                        break
    return candidates, contact


def replay_case(seed, row, series, anchors, *, compare_wick=False):
    start, cutoff, band = row["start"], row["cutoff"], row["band"]
    if series[1][0].start != start:
        raise ValueError("PROTECTION_ROUTE_OPENING_MISMATCH")
    args = dict(start=start, compare_wick=compare_wick)
    candidates, contact = candidate_clocks(series, band, cutoff=cutoff, **args)
    opening = series[1][0].end
    plan = row["plan"]
    published = datetime.fromisoformat(plan["published_at"]) + ONE
    if published >= start:
        raise ValueError("PROTECTION_ROUTE_PLAN_NOT_BEFORE_SESSION")
    case = PublicCase(f"{VERSION}:{start.isoformat()}:{seed.contract}", seed.contract, plan["source_url"], published,
                      True, ("LOCK",), ROUTES, ORDER)
    facts = [fact(case, "OPENING_CONTEXT", opening, "COMPLETED_LOCAL_OPENING_MINUTE", known_at=opening + US)]
    if band is not None:
        facts.append(fact(case, "PROTECTION_REFERENCE", published, case.source))
    if contact is not None:
        facts.append(fact(case, "PA_PRICE_OBSERVATION", contact.end, "LOCAL_RANGE_CONTACT_PROXY",
                          known_at=contact.end + US))
    public = trace(case, seed, facts, cutoff)
    if public[-1]["after"] is not None:
        raise ValueError("PROTECTION_ROUTE_UNAUTHORIZED_PUBLIC_LOCK")

    steps = {}
    for name, signal in candidates.items():
        permission = signal + US
        event_at = permission + US
        if event_at >= cutoff:
            continue
        inputs = [*facts]
        if name in ("opening", "contact", "precontact"):
            inputs.append(fact(case, "EXPLICIT_ADVANCE_ROUTE", signal - US, f"TEST_FIXTURE_ADVANCE:{name}"))
        inputs.extend((fact(case, "OPPOSITE_VPLUS", signal, f"TEST_FIXTURE_VPLUS:{name}"),
                       fact(case, "LOCK_PERMISSION", permission, f"TEST_FIXTURE_PERMISSION:{name}")))
        verdict = trace(case, seed, inputs, cutoff)
        first = next((view for view in verdict if view["after"] is not None), None)
        if first is None or first["cutoff"] != event_at:
            raise ValueError("PROTECTION_ROUTE_AUTHORIZATION_ORDER_CHANGED")
        steps[name] = Event(f"{case.id}:{name}", seed.contract, event_at, permission,
                            Action("LOCK", seed.short), f"TEST_FIXTURE:{name}", manual=True)

    lots, tick, avg = int(seed.short), Decimal(row["tick"]), Decimal(row["average"])
    integer_totals = displayed_tick_totals(avg, lots, tick)
    minutes = completed(series[1], start, cutoff)
    for anchor in anchors:
        prefix = {p: [bar for bar in bars if bar.end + US < anchor] for p, bars in series.items()}
        scoped, _ = candidate_clocks(prefix, band, cutoff=anchor, **args)
        if scoped != {k: signal for k, signal in candidates.items() if signal < anchor}:
            raise ValueError("PROTECTION_ROUTE_SIGNAL_PREFIX_DIVERGED")
    results = {}
    modes = ROUTE_MODES | WICK_MODES if compare_wick else ROUTE_MODES
    for mode, branches in modes.items():
        permitted = sorted((steps[key] for key in branches if key in steps), key=lambda event: event.effective_at)
        selected = permitted[:1]
        end_state = replay_events(seed.contract, selected, cutoff=cutoff, initial=seed)
        quote_checks = {}
        for anchor in anchors:
            eligible = [event for event in selected if event.effective_at < anchor]
            known_permitted = [event for event in permitted if event.effective_at < anchor]
            state = replay_events(seed.contract, selected, cutoff=anchor - US, initial=seed)
            if eligible != known_permitted[:1] or state != replay_events(
                seed.contract, known_permitted[:1], cutoff=anchor - US, initial=seed,
            ):
                raise ValueError("PROTECTION_ROUTE_POSITION_PREFIX_DIVERGED")
            before_quote_minute = [bar for bar in minutes if bar.end < anchor]
            through_quote_minute = [bar for bar in minutes if bar.end <= anchor]
            price = {}
            if eligible:
                for name, rows in (("previous_minutes_only", before_quote_minute),
                                   ("through_quote_minute", through_quote_minute)):
                    if earlier_lot_counts(None, tick_bounds(rows, tick), lots, integer_totals):
                        price[name] = gate_price_support(
                            rows, eligible[0].effective_at, tick=tick, lots=lots, totals=integer_totals,
                        )["only_complete_minutes_after_permission"]
                    else:
                        price[name] = None
            quote_checks[anchor.isoformat()] = dict(
                position=asdict(state), conditional_whole_leg_prices=price,
            )
        results[mode] = dict(
            modeled_event=asdict(selected[0]) if selected else None, position=asdict(end_state), quotes=quote_checks,
            strict_price_compatible_quote_count=sum(bool((q["conditional_whole_leg_prices"].get(
                "previous_minutes_only") or {}).get("whole_leg_possible")) for q in quote_checks.values()),
            through_quote_compatible_quote_count=sum(bool((q["conditional_whole_leg_prices"].get(
                "through_quote_minute") or {}).get("whole_leg_possible")) for q in quote_checks.values()),
        )
    return dict(public_assessment=public[-1], opening_ohlc=asdict(series[1][0]),
                first_protection_contact_minute_end=contact.end if contact else None,
                branches={k: asdict(event) for k, event in steps.items()}, modes=results)


def input_rows(first, later, touch):
    for contract, old in first["cases"].items():
        yield "2026-10-22", contract, dict(
            plan=old["plan"], start=datetime.fromisoformat(first["start"]),
            cutoff=datetime.fromisoformat(first["cutoff_exclusive"]), market=old["market"], short=old["original_short"],
            long=old["displayed_long"], average=old["average"], tick=old["tick"], mark=old["quote"],
            band=tuple(map(Decimal, old["protection_band"])) if old["protection_band"] else None,
            anchors=old["individual_quote_ends"], trading_day=first["trading_day"], photo=first["photo"],
        )
    quotes = scoped_input_quotes()
    for contract, key in PROTECTION.items():
        row, scoped = later["cases"][contract], touch[key]
        visible = scoped["visible_leg"]
        if (row["band"] != scoped["band"] or row["plan"]["archive_sha256"] != scoped["plan"]["archive_sha256"]
                or row["close_display"]["short"] != row["displayed_night"]["short"]):
            raise ValueError("PROTECTION_ROUTE_CARRY_SCOPE_CHANGED")
        yield "2026-10-27", contract, dict(
            plan=row["plan"], start=datetime.fromisoformat(scoped["start"]), cutoff=datetime.fromisoformat(scoped["cut"]),
            market=scoped["market"], short=row["close_display"]["short"], long=row["displayed_night"]["long"],
            average=visible["display_average"], tick=visible["tick_size"], mark=quotes[visible["source"], contract]["mark"],
            band=tuple(map(Decimal, row["band"])), anchors=None, trading_day=scoped["trading_day"], photo=visible["image"],
        )


def wick_delta(report, baseline):
    results = {}
    for day, cases in report.items():
        results[day] = {}
        for contract, case in cases.items():
            if "modes" not in case:
                if case != baseline[day][contract]:
                    raise ValueError("PROTECTION_ROUTE_BASELINE_SCOPE_CHANGED")
                continue
            modes = case["modes"]
            projection = case | dict(modes={key: modes[key] for key in ROUTE_MODES},
                                     branches={key: v for key, v in case["branches"].items()
                                               if key not in WICK_BRANCHES.values()})
            if json.loads(encoded(projection)) != baseline[day][contract]:
                raise ValueError("PROTECTION_ROUTE_BASELINE_CHANGED")
            base, expanded = (modes[name] for name in ("either_on_geometry", "geometry_with_wick"))
            compatible = [{stamp for stamp, q in row["quotes"].items()
                           if (q["conditional_whole_leg_prices"].get("previous_minutes_only") or {}).get(
                               "whole_leg_possible")} for row in (base, expanded)]
            results[day][contract] = dict(
                strict_quote_gain=sorted(compatible[1] - compatible[0]),
                strict_quote_loss=sorted(compatible[0] - compatible[1]),
                geometry_origin_replaced=bool(base["modeled_event"] and base["modeled_event"] != expanded["modeled_event"]),
            )
    return results


def wick_location_controls():
    controls = {}
    for name, row in verified_json(*FROZEN_LOCATIONS)["cases"].items():
        band = tuple(map(Decimal, row["band"])) if row["band"] else None
        qualifying = [event for event in row["events"] if band and wick_beyond(
            tuple(map(Decimal, event["shape_ohlc"])), Decimal(event["close"]), band, side=row["direction"],
        )]
        controls[name] = dict(source=row["source"], band=band, side=row["direction"],
                              eligible_geometry=qualifying if band else None)
    return controls


def study(session, market, *, compare_wick=False):
    first, later, touch = (verified_json(path, key) for path, key in (
        (REFERENCE, REFERENCE_HASH), (CAUSTIC_REFERENCE, CAUSTIC_SHA), (TOUCH, TOUCH_SHA),
    ))
    results = {day: {c: dict(status="NO_ADMITTED_PAIR") for c in CONTRACTS} for day in ("2026-10-22", "2026-10-27")}
    for day, contract, row in input_rows(first, later, touch["cases"]):
        photo = row["photo"]
        if (sha((ARCHIVE.parent / photo["path"]).read_bytes()) != photo["sha256"]
                or sha((ARCHIVE.parent / row["plan"]["archive_path"]).read_bytes()) != row["plan"]["archive_sha256"]):
            raise ValueError("PROTECTION_ROUTE_ARCHIVE_CHANGED")
        if (row["short"]["quantity"] != row["long"]["quantity"] or row["short"]["today_quantity"] != 0
                or row["long"]["today_quantity"] != row["long"]["quantity"]
                or Decimal(row["average"]) != Decimal(row["long"]["opening_average"])):
            raise ValueError("PROTECTION_ROUTE_SNAPSHOT_SCOPE_CHANGED")
        series = read_window(session, market, contract, date.fromisoformat(row["trading_day"]))
        if {f"{p}m": digest(bars) for p, bars in series.items()} != row["market"]:
            raise ValueError("PROTECTION_ROUTE_FROZEN_MARKET_CHANGED")
        mark = Decimal(row["mark"])
        anchors = [b.end for b in completed(series[1], row["start"], row["cutoff"]) if b.low <= mark <= b.high]
        if not anchors or row["anchors"] and anchors != list(map(datetime.fromisoformat, row["anchors"])):
            raise ValueError("PROTECTION_ROUTE_QUOTE_SCOPE_CHANGED")
        seed = Position(contract, short=Decimal(row["short"]["quantity"]))
        results[day][contract] = dict(status="FIXED_HYPOTHETICAL_SHORT_SEED", seed=asdict(seed), inputs=row,
                                      **replay_case(seed, row, series, anchors, compare_wick=compare_wick))
    report = dict(version=VERSION, case_days=results, author_action_samples=0, author_match_rate=None,
                  executable=False, fills=None, pnl=None)
    if compare_wick:
        report.update(version=WICK_VERSION, baseline_sha256=FROZEN_ROUTES[1], location_sha256=FROZEN_LOCATIONS[1],
                      wick_delta=wick_delta(results, verified_json(*FROZEN_ROUTES)["case_days"]),
                      wick_location_controls=wick_location_controls(),
                      wick_control_scope="GEOMETRY_ONLY_AUTHOR_SIGNAL_AND_PERMISSION_UNVERIFIED")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare-wick", action="store_true")
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
            report = study(session, build_market_data_service(session), compare_wick=args.compare_wick)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.isidentifier() and code.startswith("PROTECTION_ROUTE_")
                        else "PROTECTION_ROUTE_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
