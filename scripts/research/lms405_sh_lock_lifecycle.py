"""Replay SH2701 from a displayed noon lock through the next night snapshot."""

import argparse
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

from guiyi_quant import lms_near405 as candidate
from guiyi_quant.lms405 import Action, Bar, Position, apply_action
from lms405_carry_in_study import SNAPSHOT_SHA256, position_fields
from lms405_managed_portfolio import SNAPSHOTS, action_rows
from lms405_original_leg_study import verified_json
from lms405_portfolio_replay import ARCHIVE, DAYS, input_sources
from lms405_protection_lot_timing import EXPOSURE, displayed_tick_totals, latest_whole_leg_start
from lms405_protection_snapshot_window import price_window
from lms405_protection_timeframes import geometry_events
from lms405_recovery_confirmation_audit import edge_candidates
from lms405_replay import display, ohlc, read_session_series
from lms405_right_side_study import FIVE, ONE, US, at
from lms405_sizing_audit import EXPOSURE_SHA256, SPECS, load_specs
from lms_near405_replay import encoded, sha

CONTRACT = "SH2701"
LUNCH, CLOSE, NIGHT = "WRoAkcEppg", "U03", "WRoEvasxQR"
PLAN, OLD_PLAN, RECAP = "A5358686695981271", "A5358325972992140", "WRoCCdf0i5"
OLD_RANGE = (Decimal("1511"), Decimal("1516"))
NIGHT_RANGE = (Decimal("1490"), Decimal("1501"))
M_NEAR = Decimal("1513")
NIGHT_LONG_DISPLAY_AVERAGE = Decimal("1492.0")  # Original image retains the trailing decimal.
TIMEFRAMES = ((5, 5), (5, 1), (1, 1))
REFERENCES = {
    "exposure": (EXPOSURE, EXPOSURE_SHA256),
    "snapshots": (SNAPSHOTS, SNAPSHOT_SHA256),
    "managed": (Path("output/lms405-managed-portfolio-20261125/checked.json"),
                "189be2418f2872c1ef0060de54d3c1490d232534a39e34f5534a45dbdeb81a2d"),
    "afternoon": (Path("output/lms405-recovery-confirmation-20261125/checked.json"),
                  "1d38f1d4c6f869458f5b1760ee4e488721cd928089c388b0135d1cadc0024f82"),
    "night": (Path("output/lms405-oct-m-regions-20261125/report.json"),
              "3e1ca6dbf1fe06e5d813d5569f68524dc4c37d0d1bf6fd0f50174d9ee2936f54"),
}


def digest(bars):
    return sha(encoded([[b.end.isoformat(), *map(str, ohlc(b))] for b in bars]).encode())


def completed(bars, start, cut):
    return [b for b in bars if b.start >= start and b.end + US < cut]


def signals(series, shape_period, confirmation_period, *, side, start, cut):
    # Match the managed variant's rule that the mother and shape are contiguous.
    shapes = series[shape_period]
    contiguous = {bar.end for previous, bar in zip(shapes, shapes[1:]) if previous.end == bar.start}
    result = geometry_events(series, shape_period, confirmation_period, side=side, start=start, as_of=cut)
    return sorted((row for row in result if row["shape_end"] in contiguous), key=lambda row: row["available_at"])


def source_evidence(refs):
    index = input_sources()
    sources = {}
    for key in (LUNCH, CLOSE, NIGHT, PLAN, OLD_PLAN, RECAP):
        source = index[key]
        sources[key] = source | dict(archive_sha256=sha((ARCHIVE.parent / source["archive_path"]).read_bytes()))
    snapshots = {}
    for table in refs["exposure"]["tables"]:
        source = table["source"]
        if source not in (LUNCH, CLOSE, NIGHT):
            continue
        image = table["image"]
        if (sha((ARCHIVE.parent / image["path"]).read_bytes()) != image["sha256"]
                or table["published_at"] != sources[source]["published_at"]):
            raise ValueError("SH_SNAPSHOT_EVIDENCE_CHANGED")
        snapshots[source] = dict(image=image, published_at=table["published_at"],
                                 legs=table["contracts"][CONTRACT]["legs"], quote_anchor=None)
    for row in refs["snapshots"]["snapshots"]:
        source = row["source"]
        if source in (LUNCH, CLOSE):
            contract = row["contracts"][CONTRACT]
            if contract["quote_aligned"] is not True or contract["author_visible_legs"] != snapshots[source]["legs"]:
                raise ValueError("SH_QUOTE_SNAPSHOT_CHANGED")
            snapshots[source]["quote_anchor"] = row["quote_anchor"]
            snapshots[source]["displayed_quote"] = contract["displayed_quote"]
    return sources, snapshots


def night_price_gate(minutes, gate, tick, lots, totals):
    if gate is None:
        return None
    known_at = gate.end + US
    # The immediate next minute straddles availability. Preserve both envelopes.
    optimistic = [bar for bar in minutes if bar.bar_end > known_at]
    strict = [bar for bar in minutes if bar.bar_end - ONE > known_at]
    return dict(bar_end=gate.end, known_at=known_at, close=gate.close,
                overlap_allowed=price_window(optimistic, tick, lots, totals),
                wholly_after_known_at=price_window(strict, tick, lots, totals))


def study(session, market, refs):
    sources, snapshots = source_evidence(refs)
    afternoon_start = datetime.fromisoformat(snapshots[LUNCH]["published_at"]) + ONE
    afternoon_cut = datetime.fromisoformat(snapshots[CLOSE]["quote_anchor"])
    night_start = at("2026-10-27T21:00")
    night_cut = datetime.fromisoformat(snapshots[NIGHT]["published_at"])
    if not (afternoon_cut < datetime.fromisoformat(sources[RECAP]["published_at"])
            < datetime.fromisoformat(sources[PLAN]["published_at"]) + ONE <= night_start < night_cut):
        raise ValueError("SH_SOURCE_AVAILABILITY_ORDER_CHANGED")

    series = {}
    for period, step, days in ((1, ONE, DAYS[-2:]), (5, FIVE, DAYS)):
        raw = read_session_series(session, market, "sh", CONTRACT, f"{period}m", step, days)
        if period == 1:
            minute_market_rows = {bar.bar_end: bar for bar in raw}
        series[period] = [Bar(CONTRACT, b.bar_end, *ohlc(b), start=b.bar_end - step) for b in raw]
    one_by_end = {b.end: b for b in series[1]}
    afternoon_ref = refs["afternoon"]["cases"]["sh_afternoon"]["market"]
    night_ref = refs["night"]["contract_cases"][CONTRACT]["inputs"]
    fingerprints = {}
    for period, bars in series.items():
        name = f"{period}m"
        afternoon = [b for b in bars if at("2026-10-26T21:00") < b.end <= afternoon_cut]
        overnight = [b for b in bars if night_start < b.end <= at("2026-10-28T15:00")]
        fingerprints[name] = dict(afternoon=digest(afternoon), night=digest(overnight))
        if (dict(bars=len(afternoon), sha256=digest(afternoon)) != afternoon_ref[name]
                or dict(count=len(overnight), sha256=digest(overnight)) != night_ref[name]):
            raise ValueError("SH_FROZEN_SESSION_DATA_CHANGED")
        if period == 5:
            for bar in afternoon + overnight:
                parts = [one_by_end[bar.start + i * ONE] for i in range(1, 6)]
                if (parts[0].open, max(p.high for p in parts), min(p.low for p in parts), parts[-1].close) != ohlc(bar):
                    raise ValueError("SH_FIVE_MINUTE_AGGREGATE_CHANGED")
    for source in (LUNCH, CLOSE):
        snap = snapshots[source]
        if one_by_end[datetime.fromisoformat(snap["quote_anchor"])].close != Decimal(snap["displayed_quote"]):
            raise ValueError("SH_QUOTE_ANCHOR_CHANGED")

    managed_ref = refs["managed"]["cases"][CONTRACT]
    full = series[5]
    if digest(full) != managed_ref["input_prefix_sha256"]:
        raise ValueError("SH_MANAGED_FROZEN_INPUT_CHANGED")
    managed = candidate.replay(full, as_of=datetime.fromisoformat(refs["managed"]["as_of"]),
                               timely_fixture=True, managed_lifecycle=True)
    if action_rows(managed) != managed_ref["variants"]["managed"]["transitions"]:
        raise ValueError("SH_MANAGED_TRANSITIONS_CHANGED")
    noon = candidate.replay(full, as_of=afternoon_start, timely_fixture=True, managed_lifecycle=True)["current_state"]
    if (noon["long"], noon["short"], noon["original_side"]) != ("1", "1", "SHORT"):
        raise ValueError("SH_MANAGED_SEED_NOT_COMPARABLE")
    edges = dict(managed_generated=Decimal(noon["plan"]["lower"]), old_resistance_near=OLD_RANGE[1],
                 old_resistance_far=OLD_RANGE[0])

    seed_legs = snapshots[LUNCH]["legs"]
    seed = Position(CONTRACT, Decimal(seed_legs["long"]["quantity"]), Decimal(seed_legs["short"]["quantity"]))
    evening_long = snapshots[NIGHT]["legs"]["long"]
    evening_lots = evening_long["quantity"]
    if (seed.short != seed.long or seed.short != evening_lots
            or any(snap["legs"]["short"] != seed_legs["short"] for snap in snapshots.values())
            or set(snapshots[CLOSE]["legs"]) != {"short"}
            or NIGHT_LONG_DISPLAY_AVERAGE != Decimal(evening_long["opening_average"])):
        raise ValueError("SH_CARRY_ASSUMPTION_INPUT_CHANGED")
    tick = load_specs(json.loads(SPECS.read_bytes()))[CONTRACT]["tick"]
    noon_totals = displayed_tick_totals(Decimal(seed_legs["long"]["opening_average"]), evening_lots, tick)
    night_totals = displayed_tick_totals(NIGHT_LONG_DISPLAY_AVERAGE, evening_lots, tick)
    if not noon_totals or not night_totals:
        raise ValueError("SH_REPORTED_AVERAGE_OFF_TICK")

    minutes = completed(series[1], night_start, night_cut)
    market_minutes = [minute_market_rows[bar.end] for bar in minutes]
    windows = dict(
        first_completed_overlap=next((b for b in minutes if b.low <= NIGHT_RANGE[1] and b.high >= NIGHT_RANGE[0]), None),
        first_close_inside=next((b for b in minutes if NIGHT_RANGE[0] <= b.close <= NIGHT_RANGE[1]), None),
        first_close_strictly_above=next((b for b in minutes if b.close > NIGHT_RANGE[1]), None),
    )
    touch = windows["first_completed_overlap"]
    price_only = {name: night_price_gate(market_minutes, bar, tick, evening_lots, night_totals)
                  for name, bar in windows.items()}
    variants = {}
    for shape, confirm in TIMEFRAMES:
        afternoon = signals(series, shape, confirm, side="SHORT", start=afternoon_start, cut=afternoon_cut)
        overnight = signals(series, shape, confirm, side="LONG", start=night_start, cut=night_cut)
        inside = [row for row in overnight if NIGHT_RANGE[0] <= row["close"] <= NIGHT_RANGE[1]]
        prior = [row for row in overnight if touch and row["available_at"] < touch.start
                 and row["close"] < NIGHT_RANGE[0]]
        # Test an old signal still being usable at first touch. The retention
        # requirement is unknown, so this projection stays separate.
        armed = prior[-1] if prior else None
        pending = None
        if armed is not None:
            signal_bar = next(b for b in series[confirm] if b.end == armed["confirmed_at"])
            before_touch = [b for b in market_minutes if b.bar_end < touch.end]
            pending = dict(
                signal=armed, gate=price_only["first_completed_overlap"],
                elapsed_to_gate=touch.end - armed["confirmed_at"],
                signal_close_below_band=NIGHT_RANGE[0] - armed["close"],
                after_signal_only=night_price_gate(market_minutes, signal_bar, tick, evening_lots, night_totals),
                after_signal_before_touch_bar=night_price_gate(before_touch, signal_bar, tick, evening_lots, night_totals),
                actual_signal_retention_permission=None,
            )
        close_bars = completed(series[confirm], afternoon_start, afternoon_cut)
        comparisons = {}
        for name, edge in edges.items():
            recovery = edge_candidates(close_bars, afternoon, edge, "SHORT")
            unlock = recovery["first_shape_after_fresh_cross_and_still_beyond"]
            after_day = apply_action(seed, Action("UNLOCK_SHORT", seed.short)) if unlock else seed
            relock = next(iter(inside), None) if unlock else None
            after_night = apply_action(after_day, Action("LOCK", seed.short)) if relock else after_day
            pending_possible = unlock is not None and pending is not None
            comparisons[name] = dict(recovery=recovery, afternoon_action="UNLOCK_SHORT" if unlock else None,
                                     day_state=position_fields(after_day), night_signal=relock,
                                     night_state=position_fields(after_night),
                                     preserves_noon_long_unchanged=unlock is None,
                                     night_state_if_pre_touch_signal_retained=position_fields(
                                         apply_action(after_day, Action("LOCK", seed.short))
                                     ) if pending_possible else None)
        variants[f"{shape}m_to_{confirm}m"] = dict(afternoon_signals=afternoon, night_signals=overnight,
                                                  night_signals_in_band=inside, edge_comparisons=comparisons,
                                                  retained_signal_sensitivity=pending)

    return dict(version="lms405-sh-lock-lifecycle-v1", contract=CONTRACT, sources=sources, snapshots=snapshots,
                references={name: digest for name, (_, digest) in REFERENCES.items()}, market=fingerprints,
                seed=position_fields(seed), afternoon_start=afternoon_start, afternoon_cut=afternoon_cut,
                night_start=night_start, night_cut=night_cut, night_band=NIGHT_RANGE,
                night_minute_count=len(minutes), night_extrema=[min(b.low for b in minutes), max(b.high for b in minutes)],
                night_m_near=M_NEAR, night_m_touched=any(b.high >= M_NEAR for b in minutes),
                managed_seed_lower=edges["managed_generated"], managed_plan_origin=full[noon["plan"]["created_index"]].end,
                unchanged_noon_long_average_compatible=any(total in night_totals for total in noon_totals),
                night_price_only=price_only, night_long_display_average=NIGHT_LONG_DISPLAY_AVERAGE,
                display_tick_totals=dict(noon_long=list(noon_totals), night_long=list(night_totals)),
                latest_possible_whole_long_minute_start=latest_whole_leg_start(market_minutes, tick, evening_lots, night_totals),
                night_last_completed=display(minutes[-1].end), variants=variants,
                old_range_scope="OLDER_RESISTANCE_SENSITIVITY_ONLY", night_plan_historical_revision_verified=False,
                original_exit_permission=None, account_continuity=None, afternoon_long_visible_quantity=None,
                author_signal_at=None, author_action_at=None, admitted_author_action_samples=0,
                author_match_rate=None, executable=False, fills=None, pnl=None)


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
        refs = {key: verified_json(*reference) for key, reference in REFERENCES.items()}
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session), refs)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, ValueError, OSError):
        parser.exit(2, "SH_LOCK_LIFECYCLE_INPUT_UNVERIFIED\n")


if __name__ == "__main__":
    main()
