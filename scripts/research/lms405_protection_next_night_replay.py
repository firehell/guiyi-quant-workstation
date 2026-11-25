"""Reapply the layered protection contract to the 27 October close and overnight holdings."""

import argparse
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Action, Position, apply_action
from guiyi_quant.lms405.handoff import Handoff, assess_handoff
from guiyi_quant.lms405.public_conditions import PublicCase
from lms405_oi_leg_intent import CONTINUITY, CONTINUITY_SHA, CUT, DAY, START, lot_bound
from lms405_portfolio_replay import ARCHIVE, CONTRACTS, input_sources
from lms405_protection_layers_replay import ORDER, ROUTES, VERSION, fact, measure, trace
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_portfolio_study import totals
from lms405_protection_timeframes import read_window
from lms405_public_plan_roles import load_source
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import completed, digest
from lms_near405_replay import encoded, sha

BASELINE = Path("output/lms405-protection-layers-20261125/verified.json")
BASELINE_SHA = "666389ac77d214b551c9612e22bd31158fecc669b672e3eb1b61fd62d63ad193"
TOUCH = Path("output/lms405-pre-touch-protection-20261125/final.json")
TOUCH_SHA = "d5053217c8be047d853955709fdca77b8b268656f5cb2af0b078574399e94a60"
OI = Path("output/lms405-oi-leg-intent-20261125/verified.json")
OI_SHA = "b2f5e9c6bdfa25d28ccdffa0618c643d64f54c682a98cc4b54b766d54271821b"
SH = Path("output/lms405-sh-protection-replacement-20261125/verified.json")
SH_SHA = "700523eff5ab60c4330cd180b223c58dd3f664feadcc8fa1df8dc67283733286"
CLOSE, NIGHT = "U03", "WRoEvasxQR"
REGULAR, ALTERNATIVE = "A5358686423089344", "A5358686695981271"
PROTECTION = {"RU2701": "ru_before_m", "SH2701": "sh_second_night"}


def observed_price_cross(minutes, edge):
    return next((b for b in minutes if b.open <= edge < b.high or b.low <= edge < b.close), None)


def boundary_facts(case, published, minutes, band):
    bar = minutes[0]
    facts = [fact(case, "OPENING_CONTEXT", bar.end, "FROZEN_COMPLETED_OPENING_BAR", known_at=bar.end + US)]
    if not band:
        return facts, None
    facts.append(fact(case, "PROTECTION_REFERENCE", published, case.source))
    crossed = observed_price_cross(minutes, band[0])
    if crossed is not None:
        facts.append(fact(case, "PA_PRICE_OBSERVATION", crossed.end, "OHLC_UPWARD_CROSSING_PROXY",
                          known_at=crossed.end + US))
    return facts, crossed


def signal_route(event, band):
    value = Decimal(event["close"])
    if value < band[0] and event.get("pre_touch_arm"):
        return "ADVANCE"
    return "IN_BAND" if band[0] <= value <= band[1] else None


def fixture_projection(case, before, facts, permission, cut):
    rows = trace(case, before, (*facts, fact(case, "LOCK_PERMISSION", permission, "TEST_FIXTURE_PERMISSION")), cut)
    first = next((row["cutoff"] for row in rows if row["after"] is not None), None)
    return dict(status=rows[-1]["status"], first_projection_at=first, trace=rows)


def delayed_permission(event, cross):
    if cross is None or event["touch_known_at"] is None or not event["survives_both_diagnostics"]:
        return None
    known = datetime.fromisoformat(event["touch_known_at"])
    if known != cross.end + US or datetime.fromisoformat(event["available_at"]) >= cross.start:
        return None
    return known + US


def price_timing(minutes, known_at, *, lots, tick, totals):
    later = [bar for bar in minutes if known_at < bar.start]
    first_end = next((bar.end for i, bar in enumerate(later, 1)
                      if earlier_lot_counts(None, tick_bounds(later[:i], tick), lots, totals)), None)
    return dict(first_whole_leg_price_compatible_prefix_end=first_end,
                **lot_bound(minutes, known_at, lots=lots, tick=tick, totals=totals))


def admitted_fixture(case, before, facts, events, band, published, cross):
    """Test signal admission at the given geometry timestamp, with explicit mock permission."""
    if not band or not events:
        return dict(status="BAND_OR_SIGNAL_MISSING", trace=None), before
    candidates = [(signal_route(event, band), event) for event in events]
    chosen = next(((route, event) for route, event in candidates if route), None)
    if chosen is None:
        return dict(status="SIGNAL_CLOSE_OUTSIDE_SCOPED_REFERENCE", trace=None), before
    route, event = chosen
    confirmed = datetime.fromisoformat(event["confirmed_at"])
    known = datetime.fromisoformat(event["available_at"])
    extras = []
    if route == "ADVANCE":
        extras.append(fact(case, "EXPLICIT_ADVANCE_ROUTE", published, "TEST_FIXTURE_ADVANCE_ROUTE"))
    signal_facts = (*facts, *extras,
                    fact(case, "OPPOSITE_VPLUS", confirmed, "TEST_FIXTURE_ADOPTED_GEOMETRY", known_at=known))
    immediate = fixture_projection(case, before, signal_facts, known + US, CUT)
    permission = delayed_permission(event, cross) if route == "ADVANCE" else None
    deferred = fixture_projection(case, before, signal_facts, permission, CUT) if permission is not None else None
    result = dict(route=route, signal_at=confirmed, deferred_until_touch=deferred, **immediate)
    return result, measure(before, immediate["trace"][-1])


def study(session, market):
    baseline = verified_json(BASELINE, BASELINE_SHA)
    continuity = verified_json(CONTINUITY, CONTINUITY_SHA)
    timing = verified_json(TOUCH, TOUCH_SHA)["cases"]
    oil = verified_json(OI, OI_SHA)
    sh = verified_json(SH, SH_SHA)
    reread = sh["with_night_today_quantity"]
    if baseline["version"] != VERSION:
        raise ValueError("NEXT_NIGHT_CONTRACT_CHANGED")
    sources = input_sources()
    photos = {source: continuity["sources"][source] for source in (CLOSE, NIGHT)}
    for row in photos.values():
        image = row["image"]
        if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
            raise ValueError("NEXT_NIGHT_IMAGE_CHANGED")
    if photos[NIGHT]["binding"] != "SYSTEM_COVER" or reread["image_sha256"] != photos[NIGHT]["image"]["sha256"]:
        raise ValueError("NEXT_NIGHT_VERSION_OR_REREAD_SCOPE_CHANGED")
    current = {}
    positions, geometry_only, fixture_positions = {}, {}, {}
    for contract in CONTRACTS:
        rows = continuity["contracts"].get(contract, {}).get("transitions", ())
        pair = next((r for r in rows if (r["earlier"], r["later"]) == (CLOSE, NIGHT)), None)
        if pair is None:
            current[contract] = dict(status="NO_COMPARABLE_ROW", position=None, displayed_night=None)
            continue
        earlier, later = pair["earlier_legs"], pair["later_legs"]
        visible = {side: dict(values) for side, values in later.items()}
        if contract == "SH2701":
            visible["long"]["today_quantity"] = reread["today_quantity"]
        before = Position(contract, *(Decimal(earlier.get(side, {}).get("quantity", 0)) for side in ("long", "short")))
        positions[contract] = geometry_only[contract] = fixture_positions[contract] = before
        current[contract] = dict(position=asdict(before), close_display=earlier, displayed_night=visible,
                                 carry_bounds={side: values["bounds"] for side, values in pair["sides"].items()},
                                 unlisted_close_sides=[side for side in ("long", "short") if side not in earlier],
                                 unlisted_night_sides=[side for side in ("long", "short") if side not in visible])
        case_row = current[contract]
        clock = datetime.fromisoformat(photos[CLOSE]["published_at"]) + ONE
        if before.long and before.short:
            if contract != "I2701":
                raise ValueError("NEXT_NIGHT_EXISTING_LOCK_SCOPE_CHANGED")
            series = read_window(session, market, contract, DAY)
            minute_hash = digest(series[1])
            if minute_hash != pair["verified_session_boundary"]["later_day"]["sha256"]:
                raise ValueError("NEXT_NIGHT_SESSION_CHANGED")
            minutes = completed(series[1], START, CUT)
            crossing = observed_price_cross(minutes, Decimal("667"))
            request = Handoff("RESUME_ORIGINAL", before, "SHORT", f"{contract}:plan", f"{contract}:cycle",
                              None, clock, clock)
            plan = load_source(sources, REGULAR)
            published = datetime.fromisoformat(plan["published_at"]) + ONE
            case_row.update(status="EXISTING_LOCK_ASSUMED", minute_sha256=minute_hash,
                            published_protection_reference=(Decimal("667"), Decimal("671")),
                            first_protection_near_upcross=crossing.end if crossing else None, recovery=assess_handoff(
                request, (), as_of=CUT, source=plan["source_url"], source_available_at=published, version_405=None,
            ))
            if case_row["recovery"]["after"] is not None:
                raise ValueError("NEXT_NIGHT_RECOVERY_WITHOUT_EVIDENCE")
            continue
        if before.long:
            case_row["status"] = "CARRY_VISIBLE_LONG_NO_PROTECTION_TEST"
            continue
        config = timing[PROTECTION[contract]] if contract in PROTECTION else oil
        if config["contract"] != contract:
            raise ValueError("NEXT_NIGHT_MARKET_SCOPE_CHANGED")
        series = read_window(session, market, contract, DAY)
        if digest(series[1]) != pair["verified_session_boundary"]["later_day"]["sha256"]:
            raise ValueError("NEXT_NIGHT_SESSION_CHANGED")
        minutes = completed(series[1], START, CUT)
        band = tuple(map(Decimal, config["band"])) if contract in PROTECTION else None
        plan = load_source(sources, ALTERNATIVE if band else REGULAR)
        if band and (plan["archive_sha256"] != config["plan"]["archive_sha256"]
                     or {f"{p}m": digest(bars) for p, bars in series.items()} != config["market"]):
            raise ValueError("NEXT_NIGHT_PLAN_OR_SIGNAL_INPUT_CHANGED")
        published = datetime.fromisoformat(plan["published_at"]) + ONE
        if published >= START:
            raise ValueError("NEXT_NIGHT_PLAN_AFTER_OPEN")
        case = PublicCase(f"{VERSION}:{NIGHT}:{contract}", contract, plan["source_url"], published,
                          True, ("LOCK",), ROUTES, ORDER)
        facts, cross = boundary_facts(case, published, minutes, band)
        events = sorted((e for group in (config["variants"] if band else config["geometry"]).values()
                         for e in group
                         if "confirmed_at" in e),
                        key=lambda e: datetime.fromisoformat(e["confirmed_at"]))
        if events:
            geometry_only[contract] = apply_action(before, Action("LOCK", before.short))
        public = trace(case, before, facts, CUT)
        if public[-1]["after"] is not None:
            raise ValueError("NEXT_NIGHT_PUBLIC_ACTION_WITHOUT_EVIDENCE")
        fixture, fixture_positions[contract] = admitted_fixture(case, before, facts, events, band, published, cross)
        if contract == "SH2701":
            delayed = fixture.get("deferred_until_touch")
            if delayed is not None:
                display = config["visible_leg"]
                lots, tick = visible["long"]["today_quantity"], Decimal(sh["specification"]["tick"])
                average = Decimal(display["display_average"])
                total_ticks = displayed_tick_totals(average, lots, tick)
                if (display["source"] != NIGHT or display["image"] != photos[NIGHT]["image"]
                        or average != Decimal(visible["long"]["opening_average"])
                        or lots != display["quantity"] or tick != Decimal(display["tick_size"])
                        or [total_ticks.start, total_ticks.stop - 1] != display["displayed_tick_total_interval"]):
                    raise ValueError("NEXT_NIGHT_DISPLAY_PRECISION_CHANGED")
                case_row["whole_leg_price_reference"] = display
                for scenario in (fixture, delayed):
                    scenario["whole_leg_price_support"] = price_timing(
                        minutes, scenario["first_projection_at"], lots=lots, tick=tick, totals=total_ticks,
                    )
            case_row["later_author_report"] = dict(action="LOCK", source=NIGHT,
                                                  published_at=photos[NIGHT]["published_at"], action_at=None)
        case_row.update(status="RESEARCH_PROTECTION_CONDITIONS", plan=plan, band=band,
                        open_price=minutes[0].open, first_pa_at=cross.end if cross is not None else None,
                        geometry_candidate=events[0] if events else None, layered_public=public, fixture=fixture,
                        author_action_at=None)
    return dict(
        version="lms405-layered-protection-next-night-v1", layered_contract=baseline["version"],
        sources=photos, cases=current, portfolio=dict(
            carry_assumption=totals(positions), geometry_only=totals(geometry_only),
            layered_public_evidence=totals(positions), scoped_geometry_fixture=totals(fixture_positions),
        ),
        assumption="CLOSE_TABLE_MODEL_SEED_NOT_FULL_ACCOUNT;UNLISTED_LEGS_REMAIN_UNKNOWN",
        strategy_version_scope="4.0.5_NIGHT_SNAPSHOT_ONLY;CLOSE_TABLE_MIXED",
        author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None,
        cutoff_exclusive=CUT, trading_day=DAY,
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
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.startswith("NEXT_NIGHT_") and code.isidentifier()
                        else "NEXT_NIGHT_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
