"""Test whether an earlier protective confirmation can remain valid to first zone contact."""

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

from lms405_original_leg_study import verified_json
from lms405_portfolio_replay import ARCHIVE, input_sources
from lms405_protection_lot_timing import EXPOSURE, displayed_tick_totals, earlier_lot_counts, tick_bounds
from lms405_protection_timeframes import VARIANTS, geometry_events, read_window
from lms405_protection_zone_order import price_band_status
from lms405_right_side_study import ONE, US, at
from lms405_sh_lock_lifecycle import completed, digest, signals
from lms405_sizing_audit import EXPOSURE_SHA256, SPECS, load_specs
from lms_near405_replay import encoded, sha

REFERENCES = {
    "zone_order": (Path("output/lms405-sized-portfolio-20261125/protection-zone-order.json"),
                   "f8aca6e77cf418c0ec2e2cf26d8d56a9a8d2d9db756084fe014297474d4bab60"),
    "sh_lifecycle": (Path("output/lms405-sh-lock-lifecycle-20261125/report.json"),
                     "4bd0e828b6e654decbe6e2e8a5e3c547835c607f658b904b727aad3699368986"),
    "exposure": (EXPOSURE, EXPOSURE_SHA256),
}
DISPLAY_AVERAGES = {
    "WRnTlEfj1t": {"FG2701": "828.0", "JM2701": "1400.10", "RU2701": "19505.0", "SA2701": "935.0"},
    "WRoEvasxQR": {"RU2701": "19470.0", "SH2701": "1492.0"},
}


def first_touches(minutes, lower, upper):
    segments, touches = {}, {}
    previous = segment = None
    for bar in minutes:
        if previous is None or previous.end != bar.start:
            segment = bar.start
        segments[bar.end] = segment
        if segment not in touches and bar.low <= upper and lower <= bar.high:
            touches[segment] = bar
        previous = bar
    return segments, touches


def price_after(minutes, known_at, leg):
    if leg is None or known_at is None:
        return None
    later = [b for b in minutes if known_at < b.start]
    if not later:
        return dict(minute_count=0, whole_leg_possible=None)
    tick, lots, totals = leg
    envelope = tick_bounds(later, tick)
    return dict(minute_count=len(later), extrema=[envelope[0] * tick, envelope[1] * tick],
                whole_leg_possible=bool(earlier_lot_counts(None, envelope, lots, totals)))


def analyze(series, *, start, cut, band, side, leg):
    lower, upper = band
    approach, other_side = ("BELOW", "SHORT") if side == "LONG" else ("ABOVE", "LONG")
    minutes = completed(series[1], start, cut)
    segments, touches = first_touches(minutes, lower, upper)
    variants = {}
    for shape, confirm in VARIANTS:
        key = f"{shape}m_to_{confirm}m"
        forward = signals(series, shape, confirm, side=side, start=start, cut=cut)
        opposing = signals(series, shape, confirm, side=other_side, start=start, cut=cut)
        events = []
        for event in forward:
            when, available = event["confirmed_at"], event["available_at"]
            relation = price_band_status(event["close"], band)
            segment = segments[when]
            touch = touches.get(segment)
            armed = relation == approach and (touch is None or when < touch.end)
            retained = armed and touch is not None and available < touch.start
            gate = touch.end + US if retained else None
            first_reset = first_opposite = None
            if retained:
                boundary = event["boundary"]
                first_reset = next((b.end for b in series[confirm]
                                    if when < b.end <= touch.end and segments.get(b.end) == segment
                                    and (b.close <= boundary if side == "LONG" else b.close >= boundary)), None)
                first_opposite = next((op["confirmed_at"] for op in opposing
                                       if available <= op["available_at"] <= gate
                                       and segments.get(op["confirmed_at"]) == segment), None)
            events.append(event | dict(
                relation=relation, segment_start=segment, segment_first_touch=touch.end if touch else None,
                in_band=relation == "INSIDE", pre_touch_arm=armed, touch_known_at=gate,
                first_touch_known_before_shape=(touch is not None
                                                and touch.end + US < event["shape_end"] - timedelta(minutes=shape)),
                delay_to_touch=touch.end - when if retained else None,
                points_to_approach_edge=(lower - event["close"] if side == "LONG" else event["close"] - upper)
                if armed else None, first_boundary_reset=first_reset, first_opposing_confirmation=first_opposite,
                survives_both_diagnostics=first_reset is None and first_opposite is None if retained else None,
                observed_leg_price_after_signal=price_after(minutes, available, leg),
                observed_leg_price_after_touch=price_after(minutes, gate, leg),
            ))
        variants[key] = events
    return dict(minute_count=len(minutes), contact_bar_ends=[b.end for b in touches.values()], variants=variants)


def compare_policies(cases):
    policies = {
        "IN_BAND_CLOSE": ("in_band", "observed_leg_price_after_signal"),
        "APPROACH_SIGNAL_WITHOUT_WAITING": ("pre_touch_arm", "observed_leg_price_after_signal"),
        "WAIT_FOR_FIRST_TOUCH": ("touch_known_at", "observed_leg_price_after_touch"),
        "WAIT_AND_SURVIVE_THROUGH_FIRST_TOUCH": ("survives_both_diagnostics", "observed_leg_price_after_touch"),
        "FIRST_TOUCH_KNOWN_BEFORE_SHAPE": ("first_touch_known_before_shape", "observed_leg_price_after_signal"),
    }
    result = {}
    for policy, (gate, price) in policies.items():
        result[policy] = {}
        for name, case in cases.items():
            events = [e for group in case["variants"].values() for e in group if e[gate]]
            assessments = [(e[price] or {}).get("whole_leg_possible") for e in events]
            result[policy][name] = dict(candidates=len(events), price_compatible=assessments.count(True),
                                        price_incompatible=assessments.count(False), price_unknown=assessments.count(None))
    return result


def opening_pinbar_sensitivity(series, *, start, cut, band, side, leg):
    """Only a standalone pinbar can form without an adjacent mother bar."""
    minutes = completed(series[1], start, cut)
    results = {}
    for shape, confirm in VARIANTS:
        bars = series[shape]
        previous = None
        opening_ends = set()
        for bar in bars:
            if previous is None or previous.end != bar.start:
                opening_ends.add(bar.end)
            previous = bar
        rows = geometry_events(series, shape, confirm, start=start, as_of=cut, side=side)
        results[f"{shape}m_to_{confirm}m"] = [
            event | dict(ibar=False, observed_leg_price_after_signal=price_after(minutes, event["available_at"], leg))
            for event in rows if event["shape_end"] in opening_ends and event["pinbar"] == side
            and band[0] <= event["close"] <= band[1]
        ]
    return results


def snapshot_leg(exposure, source, contract, cut, spec, index):
    (table,) = [t for t in exposure["tables"] if t["source"] == source]
    image = table["image"]
    if (sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]
            or table["published_at"] != index[source]["published_at"]
            or datetime.fromisoformat(table["published_at"]) < cut):
        raise ValueError("PRE_TOUCH_SNAPSHOT_CHANGED")
    long = table["contracts"][contract]["legs"]["long"]
    tick, lots = spec["tick"], long["quantity"]
    average = Decimal(DISPLAY_AVERAGES.get(source, {}).get(contract, long["opening_average"]))
    if average != Decimal(long["opening_average"]):
        raise ValueError("PRE_TOUCH_SNAPSHOT_AVERAGE_CHANGED")
    totals = displayed_tick_totals(average, lots, tick)
    if not totals:
        raise ValueError("PRE_TOUCH_SNAPSHOT_TICK_TOTALS_EMPTY")
    return (tick, lots, totals), dict(
        source=source, system=table["system"], published_at=table["published_at"], image=image,
        display_average=average, quantity=lots, shown_as_today_quantity=long["today_quantity"],
        tick_size=tick, displayed_tick_total_interval=[totals.start, totals.stop - 1],
        on_same_account=None, new_whole_leg_assumption="PRICE_ENVELOPE_ONLY",
    )


def study(session, market, refs):
    index = input_sources()
    specs = load_specs(json.loads(SPECS.read_bytes()))
    old = {name: value for name, value in refs["zone_order"]["cases"].items() if value["plan_band"] is not None}
    sh = refs["sh_lifecycle"]
    configs = old | {
        "oi_regular": old["oi"] | dict(plan_band=("10019", "10151")),
        "sh_second_night": dict(
            contract=sh["contract"], trading_day="2026-10-28", start=sh["night_start"], cutoff=sh["night_cut"],
            side="LONG", plan_band=sh["night_band"], source_id="A5358686695981271",
            market={period: info["night"] for period, info in sh["market"].items()},
            display_comparison=dict(source="WRoEvasxQR"),
        ),
    }
    results, market_inputs = {}, {}
    for name, config in configs.items():
        contract, day = config["contract"], date.fromisoformat(config["trading_day"])
        start, cut = [datetime.fromisoformat(config[key]) for key in ("start", "cutoff")]
        if start.tzinfo is None:
            start, cut = at(config["start"]), at(config["cutoff"])
        plan = index[config["source_id"]]
        if datetime.fromisoformat(plan["published_at"]) + ONE > start or start >= cut:
            raise ValueError("PRE_TOUCH_PLAN_LATE_OR_WINDOW_INVALID")
        pair = contract, day
        if pair not in market_inputs:
            market_inputs[pair] = read_window(session, market, contract, day)
        series = market_inputs[pair]
        fingerprints = {f"{p}m": digest(bars) for p, bars in series.items()}
        if any(fingerprints[key] != value for key, value in config["market"].items()):
            raise ValueError("PRE_TOUCH_FROZEN_MARKET_CHANGED")
        holder = (config.get("display_comparison") or {}).get("source")
        if name == "iron":
            holder = "WRoAkcEppg"
        leg, evidence = snapshot_leg(refs["exposure"], holder, contract, cut, specs[contract], index) if holder else (None, None)
        params = dict(start=start, band=tuple(map(Decimal, config["plan_band"])), side=config["side"], leg=leg)
        measured = analyze(series, cut=cut, **params)
        # The decision-time prefix must reproduce events and touches already known.
        # Future-price envelopes and a scheduled future touch are outcome diagnostics.
        prefix_cut = start + (cut - start) / 2
        earlier = analyze(series, cut=prefix_cut, **params)
        for variant, prefix_events in earlier["variants"].items():
            full_events = [event for event in measured["variants"][variant] if event["available_at"] < prefix_cut]
            keys = ("shape_end", "confirmed_at", "available_at", "in_band", "pre_touch_arm")
            if [tuple(e[k] for k in keys) for e in prefix_events] != [tuple(e[k] for k in keys) for e in full_events]:
                raise ValueError("PRE_TOUCH_PREFIX_DIVERGED")
            gate_keys = ("touch_known_at", "first_boundary_reset", "first_opposing_confirmation")
            early_gates = [tuple(e[k] for k in gate_keys) for e in prefix_events if e["touch_known_at"] is not None]
            full_gates = [tuple(e[k] for k in gate_keys) for e in full_events
                          if e["touch_known_at"] is not None and e["touch_known_at"] < prefix_cut]
            if early_gates != full_gates:
                raise ValueError("PRE_TOUCH_GATE_PREFIX_DIVERGED")
        results[name] = measured | dict(
            contract=contract, trading_day=day.isoformat(), start=start, cut=cut, band=params["band"], side=params["side"],
            opening_pinbar_in_band_sensitivity=opening_pinbar_sensitivity(series, cut=cut, **params),
            market=fingerprints, visible_leg=evidence, plan=plan | dict(
                id=config["source_id"], archive_sha256=sha((ARCHIVE.parent / plan["archive_path"]).read_bytes())),
        )
    return dict(version="lms405-pre-touch-protection-v1", cases=results, policy_comparison=compare_policies(results),
                references={name: value for name, (_, value) in REFERENCES.items()},
                source_revision_at_session_verified=False, author_match_rate=None, admitted_author_action_samples=0,
                executable=False, fills=None, pnl=None)


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
        refs = {name: verified_json(*reference) for name, reference in REFERENCES.items()}
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=60):
            report = study(session, build_market_data_service(session), refs)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError) as exc:
        code = str(exc)
        parser.exit(2, f"{code if code.startswith('PRE_TOUCH_') and code.isidentifier() else 'PRE_TOUCH_INPUT_UNVERIFIED'}\n")


if __name__ == "__main__":
    main()
