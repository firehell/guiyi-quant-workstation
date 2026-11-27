"""Compare typed protection references against directional reach in the frozen LMS portfolio."""

import argparse
from bisect import bisect_right
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant import lms_near405 as candidate
from guiyi_quant.lms405.protection_band import ProtectionBandUpdate, active_band, visible_bands
from lms405_locked_exit_audit import BASELINE_SHA256
from lms405_m_permission_study import read_pair
from lms405_portfolio_replay import ARCHIVE, CONTRACTS, DAYS, FIVE, batch_fixture_transitions, input_sources
from lms405_protection_lot_timing import EXPOSURE, displayed_tick_totals, earlier_lot_counts, tick_bounds, verified_json
from lms405_protection_quote_bounds import gate_price_support
from lms405_protection_route_comparison import FROZEN_ROUTES
from lms405_public_plan_roles import load_source
from lms405_replay import ohlc
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import digest, signals
from lms405_sizing_audit import EXPOSURE_SHA256
from lms_near405_replay import encoded, sha

VERSION = "lms405-portfolio-protection-price-admission-v1"
ADVANCE_VERSION = "lms405-portfolio-advance-protection-v1"
JOINT_CLOSE_VERSION = "lms405-portfolio-protection-joint-close-v1"
BASELINE = Path("output/lms405-portfolio-oct-20261125/fixture.json")
CONTROLS = Path("output/lms405-public-protection-and-m-20261126/final-a.json")
CONTROL_SHA = "0d3068a8a05cf32fa8f4954c413d4d2534d198ea79b5a1915ac5cb92d2cc9cad"
PLANS = (
    ("A5356884629782554", "A5356884885635211", {
        "FG2701": ((829, 836), (842, 844)), "JM2701": (("1382.5", "1397.5"), ("1410.5", 1420)),
        "SA2701": ((931, 936), (942, 945)), "SH2701": ((1610, 1632), (1660, 1668)),
        "RU2701": ((19530, 19680), (19790, 19935)), "I2701": (None, (675, "677.5")),
    }),
    ("A5357264059367516", "A5357264793370945", {
        "FG2701": ((829, 836), (842, 844)), "I2701": ((667, 671), (675, "677.5")),
        "RU2701": ((19530, 19680), (19790, 19935)), "SH2701": ((1595, 1603), (1614, 1628)),
    }),
    ("A5358325549629506", "A5358325972992140", {
        "FG2701": ((829, 836), (842, 844)), "I2701": ((667, 671), (675, "677.5")),
        "RU2701": ((19530, 19680), (19790, 19935)), "SH2701": ((1516, 1529), (1544, 1547)),
    }),
    ("A5358686423089344", "A5358686695981271", {
        "FG2701": ((829, 836), (842, 844)), "I2701": ((667, 671), (675, "677.5")),
        "RU2701": ((19360, 19405), (19515, 19610)), "SH2701": ((1490, 1501), (1513, 1523)),
    }),
)
ALTERNATIVES = {"RU2701", "SH2701", "TA2701"}
OBSERVED_REVIEW = "WRouYm67Bc"
CARRY_SOURCE = "WRov1j6e10"
OPPOSITE = {"LONG": "SHORT", "SHORT": "LONG"}
ADVANCE_PLAN_SCOPE = {
    "A5356884629782554": {"FG2701", "JM2701"},
    "A5356884885635211": {"RU2701", "SH2701"},
    "A5357264793370945": {"RU2701", "SH2701"},
    "A5358686423089344": {"FG2701", "I2701"},
    "A5358686695981271": {"RU2701", "SH2701"},
}


def plan_rows(index, contract):
    updates, m_by_revision, sources = [], {}, {}
    for regular, alternative, rows in PLANS:
        source_id = alternative if contract in ALTERNATIVES else regular
        source = sources[source_id] = load_source(index, source_id)
        known = datetime.fromisoformat(source["published_at"]).replace(second=0, microsecond=0) + ONE
        protection, m = rows.get(contract, (None, None))
        # Reviewed references here apply to original shorts only. Plans lacking an
        # identified protection area do not inherit the previous day's area.
        bounds = tuple(Decimal(str(price)) for price in protection) if protection else ()
        updates.append(ProtectionBandUpdate(
            contract, source_id, "PROTECTION" if bounds else "REVIEW_PENDING",
            known, known, source["source_url"], "SHORT", *bounds,
        ))
        if m:
            m_by_revision[source_id] = tuple(Decimal(str(price)) for price in m)
    if contract == "SH2701":
        source = sources[OBSERVED_REVIEW] = load_source(index, OBSERVED_REVIEW)
        known = datetime.fromisoformat(source["published_at"]).replace(second=0, microsecond=0) + ONE
        updates.append(ProtectionBandUpdate(
            contract, OBSERVED_REVIEW, "REVIEW_PENDING", known, known, source["source_url"], "SHORT",
        ))
    return tuple(updates), m_by_revision, sources


def price_admission(minutes, band, event, *, position_since=None, shape_step=FIVE, allow_joint_close=False):
    """Read only completed bars from the signal's continuous segment and plan revision."""
    shape_start = event["shape_end"] - shape_step
    known = event["available_at"]
    from_time = max(band.effective_after, position_since) if position_since is not None else band.effective_after
    if from_time >= shape_start:
        return dict(status="PLAN_NOT_KNOWN_BEFORE_SHAPE", loose_due_at=None, ordinary_due_at=None)
    window = []
    for bar in reversed(minutes):
        bar_known = bar.end + US
        if bar_known > known or (bar_known == known and not allow_joint_close):
            continue
        if bar_known == known and (bar.completed is not True or bar.contract != band.contract):
            raise ValueError("PROTECTION_JOINT_CLOSE_BAR_IDENTITY_MISMATCH")
        if bar.start < from_time or (window and bar.end != window[-1].start):
            break
        window.append(bar)
    window.reverse()
    lower, upper = band.lower, band.upper
    up = band.side == "SHORT"
    near = lower if up else upper
    reached = next((bar for bar in window if (bar.high >= near if up else bar.low <= near)), None)
    contact = next((bar for bar in window if bar.low <= upper and bar.high >= lower), None)
    inside = lower <= event["close"] <= upper
    starts_beyond = bool(window and (window[0].open > upper if up else window[0].open < lower))
    if reached is None:
        status = "NO_PRIOR_DIRECTIONAL_REACH"
    elif contact is None:
        status = "REACH_WITHOUT_RANGE_CONTACT"
    elif not inside:
        status = "CONFIRMATION_OUTSIDE_PROTECTION_RANGE"
    else:
        status = "ORDINARY_PRICE_CONTEXT"
    return dict(status=status, window_starts_beyond=starts_beyond, confirmation_inside=inside,
                first_contact_at=contact.end if contact else None,
                loose_due_at=reached.end + US if reached else None,
                ordinary_due_at=contact.end + US if status == "ORDINARY_PRICE_CONTEXT" else None)


def advance_due(bar, band, price):
    """A test route needs scoped wording and remains on the approach side through confirmation."""
    if bar.contract != band.contract:
        raise ValueError("PROTECTION_ADVANCE_CONFIRMATION_BAR_MISMATCH")
    if band.contract not in ADVANCE_PLAN_SCOPE.get(band.revision, ()):
        return None
    if price["status"] != "NO_PRIOR_DIRECTIONAL_REACH":
        return None
    entire_bar_before = bar.high < band.lower if band.side == "SHORT" else bar.low > band.upper
    return bar.end if entire_bar_before else None


def route_due(price, band, confirming_bar, route):
    if route in ("ordinary_or_advance", "advance_only"):
        if route == "ordinary_or_advance" and price["ordinary_due_at"] is not None:
            return price["ordinary_due_at"], "ORDINARY_CONTACT"
        return advance_due(confirming_bar, band, price), "ADVANCE_APPROACH"
    return price[route], "DIRECTIONAL_REACH" if route == "loose_due_at" else "ORDINARY_CONTACT"


def describe_advance_candidates(bars, events):
    by_end = {bar.end: bar for bar in bars}
    rows = []
    for (end, _), item in sorted(events.items()):
        band, price = item["area"], item["price"]
        if band is None or advance_due(by_end[end], band, price) is None:
            continue
        close = item["event"]["close"]
        distance = band.lower - close if band.side == "SHORT" else close - band.upper
        rows.append(dict(confirmed_at=end, close=close, revision=band.revision, points_to_near=distance))
    return rows


def observations_for_contract(series, updates, m_bands, cutoff, *, period=5, allow_joint_close=False):
    minutes, fives = series[1], series[5]
    step = period * ONE
    events = {}
    for signal_side in ("LONG", "SHORT"):
        for event in signals(series, period, period, side=signal_side, start=fives[0].start, cut=cutoff):
            key = event["confirmed_at"], signal_side
            shown = visible_bands(updates, fives[0].contract, event["available_at"])
            area, issue = active_band(shown, event["available_at"], OPPOSITE[signal_side])
            price = (price_admission(minutes, area, event, shape_step=step, allow_joint_close=allow_joint_close) if area else
                     dict(status=issue, loose_due_at=None, ordinary_due_at=None))
            m = m_bands.get(area.revision) if area else None
            events[key] = dict(event=event, area=area, price=price,
                               m_reference=m, close_also_in_m=m[0] <= event["close"] <= m[1] if m else None)
    return events


def replay_with_price_context(series, updates, events, *, cutoff, due_field, seed=None, period=5,
                              recovery_boundary=None):
    minutes, fives = series[1], series[5]
    proofs, attempts = [], []
    replay_args = dict(protection_bands=updates, timely_fixture=True)
    if seed:
        replay_args.update(carry_in=seed, carry_exit_evidence=())
    if recovery_boundary is not None:
        replay_args["carry_recovery"] = recovery_boundary
    driver_ends = [bar.end for bar in fives]
    confirming_bars = {bar.end: bar for bar in series[period]}
    step = period * ONE
    for (end, side), row in sorted(events.items()):
        signal, band = row["event"], row["area"]
        bar = confirming_bars[end]
        if band is None or route_due(row["price"], band, bar, due_field)[0] is None:
            continue
        known = signal["available_at"]
        next_index = bisect_right(driver_ends, end)
        if ((seed and known <= seed.known_at) or next_index == len(fives)
                or fives[next_index].start > end):
            continue
        # Give other actions from the signal bar time to update the position.
        state = candidate.replay(fives, as_of=known + US, protection_confirmations=tuple(proofs),
                                 **replay_args)["current_state"]
        if state["original_side"] != band.side or state["long"] == state["short"]:
            continue
        since = datetime.fromisoformat(state["since"])
        price = price_admission(minutes, band, signal, position_since=since, shape_step=step)
        due_at, route = route_due(price, band, bar, due_field)
        if due_at is None:
            continue
        advance = due_field in ("ordinary_or_advance", "advance_only")
        version = ADVANCE_VERSION if advance else VERSION
        proof = candidate.ScopedProtectionConfirmation(
            band.contract, candidate.fingerprint(state), due_at, end, known,
            f"{version}:{due_field}", "TEST_FIXTURE", band.scope, signal["shape_end"] - step, side,
        )
        proofs.append(proof)
        attempts.append(dict(
            proof=asdict(proof), price=price, next_driver_end=fives[next_index].end,
            signal_close=signal["close"], protection_revision=band.revision, m_reference=row["m_reference"],
            confirmed_in_m=row["close_also_in_m"],
        ))
        if advance:
            attempts[-1]["route"] = route
            attempts[-1]["signal_period_minutes"] = period
    args = replay_args | dict(protection_confirmations=tuple(proofs))
    result = candidate.replay(fives, as_of=cutoff, **args)
    default_probe = seed.known_at if seed else fives[len(fives) // 2].end
    probes = [proof.known_at - US for proof in proofs] or [default_probe]
    for probe in probes:
        prefix = [bar for bar in fives if bar.end + US <= probe]
        known_proofs = tuple(proof for proof in proofs if proof.known_at <= probe)
        prev = candidate.replay(prefix, as_of=probe, protection_confirmations=known_proofs, **replay_args)
        if (prev != candidate.replay(fives, as_of=probe, **args)
                or result != candidate.replay(fives, as_of=cutoff,
                                              checkpoint=json.loads(encoded(prev["checkpoint"])), **args)):
            raise ValueError("PROTECTION_PRICE_PREFIX_OR_RESTART_DIVERGED")
    return result, attempts


def check_baseline_locks(baseline, events):
    proposals = {p["proposal_id"]: p for p in baseline["proposals"]}
    bar_by_index = {e["index"]: datetime.fromisoformat(e["bar_end"]) for e in baseline["evaluations"]}
    rows = []
    for transition in baseline["transitions"]:
        if transition["action"] != "LOCK":
            continue
        signal_side = OPPOSITE[transition["before"]["original_side"]]
        driver = bar_by_index[proposals[transition["proposal_id"]]["index"]]
        price = events.get((driver, signal_side))
        rows.append(dict(driver=driver, original_side=OPPOSITE[signal_side],
                         price_status=price["price"]["status"] if price else "NO_CONTIGUOUS_GEOMETRY",
                         area_revision=price["area"].revision if price and price["area"] else None))
    return rows


def carry_seeds(exposure):
    (table,) = (row for row in exposure["tables"] if row["source"] == CARRY_SOURCE)
    img = table["image"]
    if (table["binding"] != "SYSTEM_COVER" or table["system"] != "4.0.5"
            or sha((ARCHIVE.parent / img["path"]).read_bytes()) != img["sha256"]):
        raise ValueError("PROTECTION_PRICE_CARRY_IMAGE_CHANGED")
    # The observed row sets direction only. One unit is a research projection.
    known = datetime.fromisoformat(table["published_at"]).replace(second=0, microsecond=0) + ONE
    states = {}
    for contract, row in table["contracts"].items():
        legs = row["legs"]
        if set(legs) not in ({"long"}, {"short"}):
            raise ValueError("PROTECTION_PRICE_EXPECTED_DIRECTIONAL_CARRY")
        (side,) = legs
        states[contract] = candidate.CarryInSeed(contract, known, side.upper(), False,
                                                  "VISIBLE_405_DIRECTION_UNIT_HYPOTHESIS")
    return states, table


def compare_caustic_quote(minutes, transitions, frozen):
    """Compare simulated position through each possible quote minute under same-row assumptions."""
    inputs = frozen["inputs"]
    start, cutoff = (datetime.fromisoformat(inputs[key]) for key in ("start", "cutoff"))
    image = inputs["photo"]
    if sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]:
        raise ValueError("PROTECTION_ADVANCE_QUOTE_IMAGE_CHANGED")
    context = [bar for bar in minutes if start <= bar.start and bar.end + US < cutoff]
    tick, mark = Decimal(inputs["tick"]), Decimal(inputs["mark"])
    lots = inputs["long"]["quantity"]
    totals = displayed_tick_totals(Decimal(inputs["average"]), lots, tick)
    quoted = [bar for bar in context if bar.low <= mark <= bar.high]
    if {bar.end.isoformat() for bar in quoted} != set(frozen["modes"]["ordinary_only"]["quotes"]):
        raise ValueError("PROTECTION_ADVANCE_QUOTE_WINDOWS_CHANGED")
    changes = [(datetime.fromisoformat(row["known_at"]), Decimal(row["after"]["long"]) > 0)
               for row in transitions]

    def locked_at(time):
        return next((locked for changed_at, locked in reversed(changes) if changed_at < time), False)

    opens = [when for when, locked in changes if locked]
    first_lock = opens[0] if opens else None
    rows = []
    for quote in quoted:
        locked_before = locked_at(quote.start)
        locked_through = locked_at(quote.end)
        price = {}
        if first_lock is not None and locked_before:
            for name, include in (("before_quote_minute", False), ("through_quote_minute", True)):
                prefix = [bar for bar in context if bar.end < quote.end or (include and bar.end == quote.end)]
                possible = bool(earlier_lot_counts(None, tick_bounds(prefix, tick), lots, totals))
                price[name] = (gate_price_support(prefix, first_lock, tick=tick, lots=lots, totals=totals)[
                    "only_complete_minutes_after_permission"
                ]["whole_leg_possible"] if possible else False)
        rows.append(dict(quote_minute_end=quote.end, locked_before=locked_before, locked_at_end=locked_through,
                         later_complete_minute_price_support=price))
    return dict(image=image, quote=mark, displayed_long_lots=lots, displayed_long_opening_average=inputs["average"],
                first_fixture_lock=first_lock, author_capture_at=None, author_account_continuity=None, minutes=rows)


def joint_close_comparison(series, updates, m_bands, cutoff, *, ordinary_five):
    minutes = {bar.end: bar for bar in series[1]}
    results = {}
    for period, strict in ((1, observations_for_contract(series, updates, m_bands, cutoff, period=1)),
                           (5, ordinary_five)):
        joint = observations_for_contract(series, updates, m_bands, cutoff, period=period, allow_joint_close=True)
        if joint.keys() != strict.keys():
            raise ValueError("PROTECTION_JOINT_CLOSE_GEOMETRY_DIVERGED")
        additions = []
        for (end, side), row in sorted(joint.items()):
            due = row["price"]["ordinary_due_at"]
            earlier = strict[end, side]["price"]
            if earlier["ordinary_due_at"] is not None and earlier["ordinary_due_at"] != due:
                raise ValueError("PROTECTION_JOINT_CLOSE_CHANGED_PRIOR_CONTACT")
            if due is None or earlier["ordinary_due_at"] is not None:
                continue
            band, event = row["area"], row["event"]
            if due != event["available_at"] or row["price"]["first_contact_at"] != end:
                raise ValueError("PROTECTION_JOINT_CLOSE_ADDED_NON_COINCIDENT_CONTACT")
            current, previous = minutes[end], minutes.get(end - ONE)
            upward = side == "LONG"
            edge = band.lower if upward else band.upper
            fresh = previous is not None and previous.end == current.start and (
                previous.close <= edge < current.close if upward else previous.close >= edge > current.close
            )
            additions.append(dict(confirmed_at=end, known_at=due, direction=side, revision=band.revision,
                                  lower=band.lower, upper=band.upper, confirmation_close=event["close"],
                                  first_contact_minute_ohlc=ohlc(current), strict_fresh_near_close_same_minute=fresh,
                                  prior_price_status=earlier["status"]))
        results[f"{period}m"] = dict(
            geometry_count=len(strict),
            ordinary_before_count=sum(row["price"]["ordinary_due_at"] is not None for row in strict.values()),
            ordinary_joint_count=sum(row["price"]["ordinary_due_at"] is not None for row in joint.values()),
            additions=additions,
        )
    return results


def study(session, market, baseline, control, exposure, *, advance=False, joint_close=False):
    cutoff = datetime.fromisoformat(baseline["as_of"])
    index = input_sources()
    modes = {key: [] for key in (
        "baseline", "no_protection_confirmation_fixture", "directional_reach_fixture", "ordinary_contact_fixture",
    )}
    price_modes = [("directional_reach_fixture", "loose_due_at"), ("ordinary_contact_fixture", "ordinary_due_at")]
    if advance:
        modes["ordinary_or_advance_fixture"] = []
        price_modes.append(("ordinary_or_advance_fixture", "ordinary_or_advance"))
    seeds, seed_table = carry_seeds(exposure)
    caustic_quote = None
    results = {}
    for contract in CONTRACTS:
        _, series = read_pair(session, market, contract, DAYS)
        fives = series[5]
        if digest(fives) != baseline["contract_summaries"][contract]["input_prefix_sha256"]:
            raise ValueError("PROTECTION_PRICE_FROZEN_MARKET_CHANGED")
        updates, m_bands, sources = plan_rows(index, contract)
        events = observations_for_contract(series, updates, m_bands, cutoff)
        original = candidate.replay(fives, as_of=cutoff, timely_fixture=True)
        independent = candidate.replay(fives, as_of=cutoff, timely_fixture=True, protection_bands=updates,
                                       protection_confirmations=())
        manual = candidate.replay(fives, as_of=cutoff, protection_bands=updates, protection_confirmations=())
        if manual["transitions"] or any(row["action"] == "LOCK" for row in independent["transitions"]):
            raise ValueError("PROTECTION_PRICE_PUBLIC_EVIDENCE_BECAME_ACTION")
        modes["baseline"].extend(original["transitions"])
        modes["no_protection_confirmation_fixture"].extend(independent["transitions"])
        fixtures = {}
        carry = {}
        for name, due_field in price_modes:
            outcome, attempts = replay_with_price_context(series, updates, events, cutoff=cutoff, due_field=due_field)
            modes[name].extend(outcome["transitions"])
            fixtures[name] = dict(attempts=attempts, terminal_status=outcome["terminal_status"])
            if contract in seeds:
                outcome, attempts = replay_with_price_context(series, updates, events, cutoff=cutoff,
                                                               due_field=due_field, seed=seeds[contract])
                carry[name] = dict(attempts=attempts, terminal_status=outcome["terminal_status"],
                                   transitions=outcome["transitions"])
        results[contract] = dict(
            market={f"{p}m": dict(count=len(rows), sha256=digest(rows)) for p, rows in series.items()},
            schedules=[asdict(update) for update in updates], m_by_plan=m_bands, sources=sources,
            candidate_status=Counter(row["price"]["status"] for row in events.values()),
            non_ordinary_directional=[],
            baseline_locks=check_baseline_locks(original, events),
            manual_suggestions=len(manual["proposals"]), fixtures=fixtures, unit_carry_fixtures=carry,
        )
        if joint_close:
            results[contract]["joint_close_comparison"] = joint_close_comparison(
                series, updates, m_bands, cutoff, ordinary_five=events,
            )
        if advance:
            fast = observations_for_contract(series, updates, m_bands, cutoff, period=1)
            results[contract]["pre_contact_candidates"] = {
                f"{period}m": describe_advance_candidates(series[period], rows)
                for period, rows in ((1, fast), (5, events))
            }
            if contract in seeds:
                outcome, attempts = replay_with_price_context(
                    series, updates, fast, cutoff=cutoff, due_field="advance_only", seed=seeds[contract], period=1,
                )
                carry["fast_advance_only_fixture"] = dict(
                    attempts=attempts, terminal_status=outcome["terminal_status"], transitions=outcome["transitions"],
                )
                if contract == "SH2701":
                    quote = verified_json(*FROZEN_ROUTES)["case_days"]["2026-10-27"][contract]
                    caustic_quote = compare_caustic_quote(series[1], outcome["transitions"], quote)
        for row in events.values():
            if row["price"]["loose_due_at"] is not None and row["price"]["ordinary_due_at"] is None:
                results[contract]["non_ordinary_directional"].append(dict(
                    known_at=row["event"]["available_at"], close=row["event"]["close"],
                    revision=row["area"].revision, price=row["price"], same_close_in_m=row["close_also_in_m"],
                ))
    actions = {
        mode: dict(counts=Counter(row["action"] for row in rows), timeline=batch_fixture_transitions(rows)[0])
        for mode, rows in modes.items()
    }
    if actions["baseline"]["timeline"] != [row for row in baseline["timeline"] if row["layer"] == "FIXTURE_STATE_BATCH"]:
        raise ValueError("PROTECTION_PRICE_BASELINE_DIVERGED")
    controls = control["cases"]
    report = dict(version=JOINT_CLOSE_VERSION if joint_close else ADVANCE_VERSION if advance else VERSION,
                contracts=results, actions=actions,
                baseline_sha256=BASELINE_SHA256,
                historical_plan_revision_verified=False, author_action_samples=0, author_match_rate=None,
                evidence_controls_sha256=CONTROL_SHA,
                carry_context=dict(source=CARRY_SOURCE, image=seed_table["image"], seeds={
                    key: asdict(seed) for key, seed in seeds.items()
                }, exposure_sha256=EXPOSURE_SHA256, author_account_continuity=None),
                controls={key: controls[key]["role_windows"] for key in ("S5319173366613171", "S5323519697094213")},
                executable=False, fills=None, pnl=None)
    if advance:
        report["advance_scope"] = {key: sorted(contracts) for key, contracts in ADVANCE_PLAN_SCOPE.items()}
        report["caustic_quote_comparison"] = caustic_quote
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--advance", action="store_true")
    modes.add_argument("--joint-close", action="store_true")
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
        baseline, control = verified_json(BASELINE, BASELINE_SHA256), verified_json(CONTROLS, CONTROL_SHA)
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=90):
            report = study(session, build_market_data_service(session), baseline, control,
                           verified_json(EXPOSURE, EXPOSURE_SHA256), advance=args.advance, joint_close=args.joint_close)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, KeyError, ValueError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.isidentifier() else 'PROTECTION_PRICE_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
