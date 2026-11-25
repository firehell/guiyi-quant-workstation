"""Replay conditional protective-leg releases and new trading-day locks on the same original leg."""

import argparse
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Action, Event, Position, replay_events
from lms405_portfolio_replay import ARCHIVE
from lms405_protection_lot_timing import displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_next_night_replay import CUT, START, TOUCH, TOUCH_SHA, signal_route
from lms405_protection_quote_bounds import CAUSTIC_REFERENCE, CAUSTIC_SHA, SPECS_SHA, gate_price_support
from lms405_protection_timeframes import read_window
from lms405_right_side_study import US, at
from lms405_sh_lock_lifecycle import LUNCH, NIGHT, completed, digest
from lms405_sh_protection_replacement import LIFECYCLE, LIFECYCLE_SHA
from lms405_sizing_audit import SPECS, load_specs
from lms_near405_replay import encoded, sha

NIGHT_DAY, DAY = date(2026, 10, 28), date(2026, 10, 27)
SH, RU = "SH2701", "RU2701"


def fixture_event(contract, action, amount, at_time, *, source):
    return Event(action, contract, at_time, at_time - US, Action(action, amount), f"TEST_FIXTURE:{source}")


def projection(seed, steps, anchors, minutes, tick, observed, average):
    """A visible old leg is a scenario input. Every new lot requires its own created leg and price window."""
    lots = observed["long"]["quantity"]
    totals = displayed_tick_totals(average, lots, tick)
    terminal = replay_events(seed.contract, steps, initial=seed, cutoff=CUT)
    matches = {}
    for end in anchors:
        visible_steps = [e for e in steps if e.effective_at < end]
        actual = replay_events(seed.contract, steps, initial=seed, cutoff=end - US)
        if actual != replay_events(seed.contract, visible_steps, initial=seed, cutoff=end - US):
            raise ValueError("REBUILD_REPLAY_PREFIX_DIVERGED")
        new = next((e for e in reversed(visible_steps) if e.action.kind == "LOCK"), None)
        compatible_quantities = all(getattr(actual, side) == leg["quantity"] for side, leg in observed.items())
        prefix = [b for b in minutes if b.end <= end]
        envelope = bool(earlier_lot_counts(None, tick_bounds(prefix, tick), lots, totals))
        support = gate_price_support(prefix, new.effective_at, tick=tick, lots=lots, totals=totals) if new and envelope else None
        new_today = bool(new and new.effective_at >= START)
        matches[end.isoformat()] = dict(
            position=asdict(actual), new_protection_at=new.effective_at if new else None,
            both_quantities_match=compatible_quantities, new_leg_created_in_snapshot_trading_day=new_today,
            price_support=support, compatible=compatible_quantities and new_today and bool(
                support and support["only_complete_minutes_after_permission"]["whole_leg_possible"]),
        )
    return dict(steps=[asdict(e) for e in steps], terminal=asdict(terminal), quote_checks=matches,
                compatible_quotes=sum(r["compatible"] for r in matches.values()))


def study(session, market):
    joined = verified_json(CAUSTIC_REFERENCE, CAUSTIC_SHA)
    protect = verified_json(TOUCH, TOUCH_SHA)["cases"]
    sh_life = verified_json(LIFECYCLE, LIFECYCLE_SHA)
    for image in (joined["sources"][NIGHT]["image"], sh_life["snapshots"][LUNCH]["image"]):
        if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
            raise ValueError("REBUILD_SOURCE_IMAGE_CHANGED")
    specs = load_specs(verified_json(SPECS, SPECS_SHA))
    results = {}
    for contract, role, mark, expected_average in (
        (SH, "sh_second_night", Decimal(1491), Decimal("1492.0")),
        (RU, "ru_before_m", Decimal(19480), Decimal("19470.0")),
    ):
        scoped, visible = protect[role], joined["cases"][contract]
        series = read_window(session, market, contract, NIGHT_DAY)
        if {f"{p}m": digest(rows) for p, rows in series.items()} != scoped["market"]:
            raise ValueError("REBUILD_NIGHT_MARKET_CHANGED")
        minutes = completed(series[1], START, CUT)
        anchors = [b.end for b in minutes if b.low <= mark <= b.high]
        observed = visible["displayed_night"]
        lots = Decimal(observed["short"]["quantity"])
        if (visible["close_display"]["short"] != observed["short"]
                or Decimal(observed["long"]["opening_average"]) != expected_average
                or observed["long"]["quantity"] != lots or observed["long"]["today_quantity"] != lots
                or observed["short"]["today_quantity"] != 0 or visible["carry_bounds"]["short"] != [lots, lots]):
            raise ValueError("REBUILD_NIGHT_FIELDS_CHANGED")
        def inspect(seed, steps):
            return projection(seed, steps, anchors, minutes, specs[contract]["tick"], observed, expected_average)

        scopes = dict(protection_band=scoped["band"], night_source=joined["sources"][NIGHT], quote_mark=mark,
                      conditional_original_short=visible["close_display"]["short"],
                      night_visible=observed, author_action_at=None,
                      author_permission=None, quote_clock=None, short_identity_confirmed=False)
        paths = {}
        conditional_single = Position(contract, short=lots)
        conditional_dual = Position(contract, lots, lots)
        paths["retain_earlier_protection"] = inspect(conditional_dual, ())
        if contract == SH:
            original = sh_life["snapshots"][LUNCH]["legs"]
            if original["short"] != observed["short"] or original["long"]["quantity"] != lots:
                raise ValueError("REBUILD_NOON_FIELDS_CHANGED")
            prior = read_window(session, market, contract, DAY)
            if any(digest(prior[p]) != sh_life["market"][f"{p}m"]["afternoon"] for p in (1, 5)):
                raise ValueError("REBUILD_AFTERNOON_MARKET_CHANGED")
            scopes["noon_visible"] = sh_life["snapshots"][LUNCH]
            immediate, wait = (datetime.fromisoformat(row["first_projection_at"])
                               for row in (visible["fixture"], visible["fixture"]["deferred_until_touch"]))
            for variant, edge in (("5m_to_1m", "old_resistance_near"), ("1m_to_1m", "old_resistance_far")):
                recovery = sh_life["variants"][variant]["edge_comparisons"][edge]
                signal = recovery["recovery"]["first_shape_after_fresh_cross_and_still_beyond"]
                release = datetime.fromisoformat(signal["available_at"]) + 2 * US
                if recovery["afternoon_action"] != "UNLOCK_SHORT" or not at("2026-10-27T11:35") < release < START:
                    raise ValueError("REBUILD_RECOVERY_SCOPE_CHANGED")
                unlock = fixture_event(contract, "UNLOCK_SHORT", lots, release, source=f"{variant}:{edge}")
                paths[f"{variant}:{edge}:release_only"] = inspect(conditional_dual, (unlock,))
                for name, when in (("immediate", immediate), ("after_touch", wait)):
                    lock = fixture_event(contract, "LOCK", lots, when, source=f"advance:{name}")
                    paths[f"{variant}:{edge}:{name}"] = inspect(conditional_dual, (unlock, lock))
        else:
            paths["scoped_evening_from_single_short"] = inspect(conditional_single, ())
            band = tuple(map(Decimal, scoped["band"]))
            shapes = {period: {b.end: b for b in rows} for period, rows in series.items()}
            outside = []
            for variant, events in scoped["variants"].items():
                period = int(variant.split("m", 1)[0])
                for e in events:
                    bar = shapes[period][datetime.fromisoformat(e["shape_end"])]
                    signal = datetime.fromisoformat(e["available_at"])
                    overlaps = bar.low <= band[1] and band[0] <= bar.high
                    route = signal_route(e, band)
                    if route is not None:
                        raise ValueError("REBUILD_RUBBER_SCOPED_ROUTE_CHANGED")
                    key = f"unscoped_{variant}_{signal.isoformat()}"
                    lock = fixture_event(contract, "LOCK", lots, signal + 2 * US, source=key)
                    paths[key] = inspect(conditional_single, (lock,))
                    outside.append(dict(path=key, variant=variant, shape_end=bar.end, shape_start=bar.start,
                                        shape_intersects_band=overlaps, shape_low=bar.low, shape_high=bar.high,
                                        confirmation=e["confirmed_at"], confirmation_close=e["close"]))
            scopes["outside_shape_comparison"] = outside
            scopes["prior_protection_long_quantity"] = None
        results[contract] = dict(scopes=scopes, paths=paths)
    return dict(version="lms405-protection-rebuild-audit-v1", contracts=results,
                author_action_samples=0, author_match_rate=None, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
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
    except (KeyError, OSError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, (code if code.startswith("REBUILD_") and code.isidentifier() else "REBUILD_INPUT_UNVERIFIED") + "\n")


if __name__ == "__main__":
    main()
