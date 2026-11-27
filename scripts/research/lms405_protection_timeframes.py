"""Compare frozen ibar/pinbar geometry across protection observation timeframes."""

import argparse
from dataclasses import asdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from guiyi_quant.lms405 import Bar
from guiyi_quant.lms_keybar_approx import classify_research_period
from lms405_replay import display, ohlc, read_session_series
from lms405_right_side_study import US, at
from lms_near405_replay import encoded, sha

PERIODS = (1, 5, 15)
VARIANTS = ((1, 1), (5, 1), (5, 5), (15, 15))
WINDOWS = (
    ("oi", "OI2609", "2026-06-03", "2026-06-03T10:14", "2026-06-03T15:01", "SHORT",
     ("10175", "10197"), "S5305666088472874", ("2026-06-03T10:45",)),
    ("iron", "I2701", "2026-10-27", "2026-10-26T21:00", "2026-10-27T11:30", "LONG",
     ("667", "671"), "A5358325549629506", ("2026-10-26T21:45", "2026-10-27T11:09")),
    ("sh", "SH2701", "2026-10-23", "2026-10-22T21:00", "2026-10-22T22:10", "LONG",
     ("1610", "1632"), "A5356884885635211", ("2026-10-22T22:08",)),
    ("jm_control", "JM2509", "2025-07-22", "2025-07-22T09:00", "2025-07-22T09:25", "SHORT",
     None, "H06", ("2025-07-22T09:15",)),
)


def geometry_events(bars, shape_period, confirmation_period, *, start, as_of, side,
                    range_excursion=False):
    if (shape_period, confirmation_period) not in VARIANTS or side not in ("LONG", "SHORT"):
        raise ValueError("UNSUPPORTED_TIMEFRAME_GEOMETRY")
    shape_step = timedelta(minutes=shape_period)
    close_step = timedelta(minutes=confirmation_period)
    quotes = {b.end: b for b in bars[confirmation_period] if b.end + US < as_of}
    previous, events = None, []
    for shape in bars[shape_period]:
        if shape.end + US >= as_of:
            break
        frame = classify_research_period(previous, shape, minutes=shape_period)
        previous = shape
        if shape.start < start or not (frame.ibar or frame.pinbar == side):
            continue
        boundary = shape.high if side == "LONG" else shape.low
        close_at = shape.end + close_step
        while close_at <= shape.end + shape_step:
            following = quotes.get(close_at)
            if following is None:
                break
            if (not isinstance(following, Bar) or following.completed is not True
                    or following.contract != shape.contract or following.start != close_at - close_step):
                raise ValueError("CONFIRMATION_BAR_IDENTITY_MISMATCH")
            comparison = (following.high if side == "LONG" else following.low) if range_excursion else following.close
            if (comparison > boundary if side == "LONG" else comparison < boundary):
                events.append(dict(
                    shape_end=shape.end, confirmed_at=following.end, available_at=following.end + US,
                    ibar=frame.ibar is True, pinbar=frame.pinbar, boundary=boundary, close=following.close,
                ))
                break
            close_at += close_step
    return events


def confirmation_contrast(series, shape, confirmation, *, start, as_of, side):
    """Measure range excursions and closes on identical shapes and completed prefixes."""
    shapes = series[shape]
    contiguous = {bar.end for before, bar in zip(shapes, shapes[1:]) if before.end == bar.start}
    args = dict(start=start, as_of=as_of, side=side)
    excursions = [row for row in geometry_events(
        series, shape, confirmation, **args, range_excursion=True,
    ) if row["shape_end"] in contiguous]
    closes = {row["shape_end"]: row for row in geometry_events(
        series, shape, confirmation, **args,
    ) if row["shape_end"] in contiguous}
    if not closes.keys() <= {row["shape_end"] for row in excursions}:
        raise ValueError("TIMEFRAME_CONFIRMATION_WITHOUT_RANGE_EXCURSION")
    bars = series[confirmation]
    by_start = {bar.start: bar for bar in bars if bar.end + US < as_of}
    shape_by_end = {bar.end: bar for bar in shapes}
    step = timedelta(minutes=shape)
    confirm_step = timedelta(minutes=confirmation)

    def still_beyond(value, boundary):
        return value > boundary if side == "LONG" else value < boundary

    rows = []
    for excursion in excursions:
        shape_end, boundary = excursion["shape_end"], excursion["boundary"]
        confirmed = closes.get(shape_end)
        deadline = shape_end + step
        # Inspect only the contiguous confirmation stream and the declared shape lifetime.
        reset = None
        if confirmed is not None:
            after = confirmed["confirmed_at"]
            while (bar := by_start.get(after)) is not None and bar.end <= deadline:
                if (not isinstance(bar, Bar) or bar.completed is not True
                        or bar.contract != shape_by_end[shape_end].contract or bar.end - bar.start != confirm_step):
                    raise ValueError("TIMEFRAME_RESET_BAR_IDENTITY_MISMATCH")
                if not still_beyond(bar.close, boundary):
                    reset = bar.end + US
                    break
                after = bar.end
        rows.append(dict(
            shape_end=shape_end, last_confirmation_bar_end=deadline, boundary=boundary,
            excursion_known_at=excursion["available_at"],
            excursion_bar_closes_beyond=still_beyond(excursion["close"], boundary),
            strict_close_known_at=confirmed["available_at"] if confirmed else None,
            reset_known_at=reset,
        ))
    return rows


def confirmation_window(series, *, start, as_of, side, split):
    results = {}
    for shape, confirm in VARIANTS:
        args = dict(start=start, side=side)
        rows = confirmation_contrast(series, shape, confirm, as_of=as_of, **args)
        prefix = {p: [bar for bar in bars if bar.end + US < split] for p, bars in series.items()}
        earlier = confirmation_contrast(prefix, shape, confirm, as_of=split, **args)
        expected = []
        for row in rows:
            if row["excursion_known_at"] >= split:
                continue
            visible = row.copy()
            for field in ("strict_close_known_at", "reset_known_at"):
                if visible[field] is not None and visible[field] >= split:
                    visible[field] = None
            expected.append(visible)
        if earlier != expected:
            raise ValueError("TIMEFRAME_CONFIRMATION_PREFIX_DIVERGED")
        results[f"{shape}m_to_{confirm}m"] = dict(
            excursion_count=len(rows),
            same_bar_close=sum(row["excursion_bar_closes_beyond"] for row in rows),
            later_close=sum(row["strict_close_known_at"] is not None and not row["excursion_bar_closes_beyond"]
                            for row in rows),
            no_close_observed=sum(row["strict_close_known_at"] is None for row in rows),
            reset_within_shape_window=sum(row["reset_known_at"] is not None for row in rows),
            rows=rows,
        )
    return results


def summarize(events, *, band, milestones):
    inside = [row for row in events if band and band[0] <= row["close"] <= band[1]]
    return dict(
        total=len(events), close_inside_band=len(inside) if band is not None else None,
        first=events[0] if events else None, first_inside=inside[0] if inside else None,
        at_or_after={value: sum(row["confirmed_at"] >= at(value) for row in events) for value in milestones},
        events=events,
    )


def read_window(session, market, contract, day):
    series = {}
    for period in PERIODS:
        step = timedelta(minutes=period)
        raw = read_session_series(session, market, contract[:-4].lower(), contract, f"{period}m", step, (day,))
        series[period] = [Bar(contract, bar.bar_end, *ohlc(bar), start=bar.bar_end - step) for bar in raw]
    minute_index = {bar.end: bar for bar in series[1]}
    for period in PERIODS[1:]:
        for bar in series[period]:
            parts = [minute_index[bar.start + timedelta(minutes=n)] for n in range(1, period + 1)]
            rebuilt = (parts[0].open, max(p.high for p in parts), min(p.low for p in parts), parts[-1].close)
            if rebuilt != ohlc(bar):
                raise ValueError("MINUTE_AGGREGATE_DIVERGED")
    return series


def study(session, market, *, compare_confirmations=False):
    cases = {}
    for name, contract, day, lower, upper, side, band, source, milestones in WINDOWS:
        series = read_window(session, market, contract, date.fromisoformat(day))
        start, as_of = at(lower), at(upper)
        split = at(milestones[0])
        results = {}
        for shape, confirmation in VARIANTS:
            args = dict(start=start, side=side)
            full = geometry_events(series, shape, confirmation, as_of=as_of, **args)
            prefix = {p: [bar for bar in bars if bar.end < split] for p, bars in series.items()}
            earlier = geometry_events(prefix, shape, confirmation, as_of=split, **args)
            if earlier != [row for row in full if row["available_at"] < split]:
                raise ValueError("TIMEFRAME_PREFIX_DIVERGED")
            result = summarize(full, band=tuple(map(Decimal, band)) if band else None, milestones=milestones)
            # Keep exact availability in the event. Display times are only minute labels.
            results[f"{shape}m_to_{confirmation}m"] = result
        cases[name] = dict(
            contract=contract, trading_day=day, start=display(start), as_of=display(as_of),
            side=side, source_id=source, band=band, checkpoint_boundaries=milestones, hypotheses=results,
            market={f"{p}m": dict(
                count=len(bars), sha256=sha(encoded([[b.end.isoformat(), *map(str, ohlc(b))]
                                                    for b in bars]).encode()),
            ) for p, bars in series.items()},
            actual_protection_signal=None, actual_action_at=None, historical_source_revision_verified=False,
        )
        if compare_confirmations:
            cases[name]["confirmation_contrast"] = confirmation_window(series, start=start, as_of=as_of,
                                                                         side=side, split=split)
    return dict(
        version="lms405-protection-timeframe-comparison-v1", cases=cases,
        checkpoints_role="RETROSPECTIVE_INTERVAL_COMPARISON_ONLY",
        admitted_author_action_samples=0, author_matches=None, fills=None, pnl=None, executable=False,
    )


def ibar_source_prefix(series, as_of):
    """Compare two 15m containment hypotheses using same-segment completed bars only."""
    rows = [bar for bar in series[15] if bar.end + US < as_of]
    minute = [bar for bar in series[1] if bar.end + US < as_of]
    result = []
    for index, (parent, signal) in enumerate(zip(rows, rows[1:]), start=1):
        if parent.end != signal.start:
            continue
        strict = classify_research_period(parent, signal, minutes=15).ibar
        if not (signal.high <= parent.high and signal.low >= parent.low):
            continue
        following = rows[index + 1] if index + 1 < len(rows) and rows[index + 1].start == signal.end else None
        next_minutes = [bar for bar in minute if signal.end <= bar.start < signal.end + timedelta(minutes=15)]
        first_touch = next((bar for bar in next_minutes if bar.low <= signal.low <= bar.high), None)
        first_cross = next((bar for bar in next_minutes if bar.low < signal.low), None)
        first_close = next((bar for bar in next_minutes if bar.close < signal.low), None)
        result.append(dict(
            mother=asdict(parent), signal=asdict(signal), strict_range_inside=strict,
            next_contiguous_15m=asdict(following) if following else None,
            next_contiguous_15m_strict_close_below=following.close < signal.low if following else None,
            first_1m_touch=asdict(first_touch) if first_touch else None,
            first_1m_strict_low_below=asdict(first_cross) if first_cross else None,
            first_1m_strict_close_below=asdict(first_close) if first_close else None,
        ))
    return result


def ur_ibar_source_study(session, market):
    # Source loading already uses this module for price-window helpers.
    from lms405_portfolio_replay import input_sources
    from lms405_public_plan_roles import load_source

    contract, day = "UR2609", date(2026, 4, 21)
    source = load_source(input_sources(), "S5290151945438276")
    shown_at = at("2026-04-21T14:46")
    if (datetime.fromisoformat(source["published_at"]) != shown_at
            or source["source_url"] != "https://www.sina.cn/news/detail/5290151945438276.html"):
        raise ValueError("UR_IBAR_SOURCE_CHANGED")
    series = read_window(session, market, contract, day)
    candidates = ibar_source_prefix(series, shown_at)
    minute = [bar for bar in series[1] if bar.end + US < shown_at]
    weak = Decimal(1995), Decimal(2003)
    first_area_touch = next((bar for bar in minute if bar.high >= weak[0] and bar.low <= weak[1]), None)
    first_later_below = next((bar for bar in minute if first_area_touch and first_area_touch.end < bar.end
                             and bar.close < weak[0]), None)
    anchored = [row for row in candidates if row["strict_range_inside"] and row["next_contiguous_15m_strict_close_below"]]
    for row in anchored:
        next_end = row["next_contiguous_15m"]["end"]
        before = ibar_source_prefix(series, next_end + US)
        after = ibar_source_prefix(series, next_end + 2 * US)
        key = row["signal"]["end"]
        earlier, = [match for match in before if match["signal"]["end"] == key]
        later, = [match for match in after if match["signal"]["end"] == key]
        if earlier["next_contiguous_15m"] is not None or later != row:
            raise ValueError("UR_IBAR_STRICT_BEFORE_DIVERGED")
    return dict(
        version="lms405-ur-public-ibar-geometry-v1", source=source, contract=contract, trading_day=day,
        analysis_cutoff_exclusive=shown_at, assumed_author_bar=None, author_version=None, author_action=None,
        candidates=candidates, strict_ibar_with_next_15m_down_closes=len(anchored),
        weak_side_reference=weak, later_protection_reference=(Decimal(1972), Decimal(1995)),
        first_weak_side_range_contact=asdict(first_area_touch) if first_area_touch else None,
        first_completed_close_below_after_contact=asdict(first_later_below) if first_later_below else None,
        market={f"{period}m": dict(count=len(bars), sha256=sha(encoded([asdict(bar) for bar in bars]).encode()))
                for period, bars in series.items()},
        admitted_author_bar_samples=0, admitted_author_action_samples=0, executable=False, fills=None, pnl=None,
    )


def jd_ibar_protection_study(session, market):
    from lms405_portfolio_replay import input_sources
    from lms405_public_plan_roles import load_source

    contract = "JD2612"
    index = input_sources()
    sources = {identity: load_source(index, identity) for identity in (
        "S5364440250977429", "R20261113JD2612DEFENSE", "S5365839312453793",
    )}
    prior, friday_excerpt, review = (datetime.fromisoformat(row["published_at"]) for row in sources.values())
    if (prior, friday_excerpt, review) != (
        at("2026-11-12T14:41:25"), at("2026-11-13T11:09:54"), at("2026-11-16T11:20:46"),
    ):
        raise ValueError("JD_IBAR_SOURCE_CLOCKS_CHANGED")
    series = {day: read_window(session, market, contract, date(2026, 11, day)) for day in (12, 13, 16)}
    early_price, trigger, lower, top_price = map(Decimal, (3639, 3614, 3582, 3674))
    prices, window_minutes = {}, {}
    for day, periods in series.items():
        cutoff = review if day == 16 else periods[1][-1].end + 2 * US
        rows = [bar for bar in periods[1] if bar.end + US < cutoff]
        window_minutes[day] = rows
        prices[day] = dict(cutoff_exclusive=cutoff, minimum=min(bar.low for bar in rows),
                           maximum=max(bar.high for bar in rows), first_minute=asdict(rows[0]),
                           early_price_range_matches=[bar.end for bar in rows if bar.low <= early_price <= bar.high])

    friday = window_minutes[13]
    pivot = next((bar for bar in friday if bar.high == top_price), None)
    if pivot is None:
        raise ValueError("JD_IBAR_HIGH_PRICE_ANCHOR_NOT_FOUND")
    after_high = [bar for bar in friday if bar.start >= pivot.end]
    first_early = next((bar for bar in after_high if bar.low <= early_price <= bar.high), None)
    first_later_cross = next((bar for previous, bar in zip(after_high, after_high[1:])
                            if previous.end == bar.start and bar.close < trigger <= previous.close), None)
    if first_early is None or first_later_cross is None or first_early.end >= first_later_cross.end:
        raise ValueError("JD_IBAR_PRICE_ORDER_UNVERIFIED")
    after_lower = next((b for b in window_minutes[16] if b.low <= lower <= b.high and b.close < lower), None)
    trigger_known_at = first_later_cross.end + US
    visible_after_excerpt = friday_excerpt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    if not trigger_known_at < visible_after_excerpt < review:
        raise ValueError("JD_IBAR_CONFIRMATION_ORDER_UNVERIFIED")

    branches = {}
    for shape, confirm in VARIANTS:
        by_end = {period: {b.end: b for b in series[13][period]} for period in (shape, confirm)}
        events = geometry_events(series[13], shape, confirm, start=pivot.end + US,
                                 as_of=visible_after_excerpt, side="SHORT")
        early, same_or_later = [], []
        for row in events:
            setup = by_end[shape][row["shape_end"]]
            mother = by_end[shape].get(setup.start)
            confirmation = by_end[confirm][row["confirmed_at"]]
            if not row["ibar"] or mother is None:
                continue
            if row["available_at"] < trigger_known_at:
                early.append(row | dict(confirmation_range_contains_early_price=(
                    confirmation.low <= early_price <= confirmation.high
                )))
            if lower <= row["close"] < trigger and row["available_at"] >= trigger_known_at:
                same_or_later.append(row | dict(shape_starts_after_cross_known=setup.start > trigger_known_at,
                                                confirmation_after_cross_known=row["available_at"] > trigger_known_at))
        branches[f"{shape}m_to_{confirm}m"] = dict(before_break=early, at_or_after_break_in_band=same_or_later)
    return dict(
        version="lms405-jd-early-ibar-vs-break-defense-v1", contract=contract, sources=sources, prices=prices,
        friday_peak_minute=asdict(pivot), first_3639_minute_after_peak=asdict(first_early),
        fresh_down_close_through_3614=asdict(first_later_cross), friday_excerpt_known_after=visible_after_excerpt,
        monday_first_below_far_contact_close=asdict(after_lower) if after_lower else None,
        fixed_periods_retrospective_comparison=branches,
        market={day: {f"{p}m": dict(count=len(bars), sha256=sha(encoded([asdict(b) for b in bars]).encode()))
                      for p, bars in periods.items()} for day, periods in series.items()},
        actual_author_ibar_period=None, actual_author_action=None, admitted_author_action_samples=0,
        admitted_author_bar_samples=0, executable=False, fills=None, pnl=None,
    )


def warning_phase_comparison(series, *, known_after, as_of, bands):
    from lms405_recovery_confirmation_audit import strict_runs
    from lms405_sh_lock_lifecycle import signals

    minutes = [bar for bar in series[1] if known_after < bar.start and bar.end + US < as_of]
    segment_by_end, previous = {}, None
    for bar in minutes:
        if previous is None or previous.end != bar.start:
            segment = bar.start
        segment_by_end[bar.end] = segment
        previous = bar

    availability = dict(start=known_after + US, side="LONG")
    frames = {}
    for shape, confirm in VARIANTS:
        rows = signals(series, shape, confirm, cut=as_of, **availability)
        frames[shape, confirm] = [(row, row["shape_end"] - timedelta(minutes=shape)) for row in rows]

    results = {}
    for role, (near, far) in bands.items():
        overlap = next((bar.end + US for bar in minutes if bar.low <= far and bar.high >= near), None)
        clocks = {"range_overlap": (near, overlap)}
        for edge_name, edge in (("near", near), ("far", far)):
            runs = strict_runs(minutes, edge, "LONG")
            fresh = next((r["fresh_crossing_known_at"] for r in runs.values()
                          if r["fresh_crossing_known_at"] is not None), None)
            clocks[f"strict_fresh_{edge_name}"] = edge, fresh
        phases = {}
        for clock, (edge, known_at) in clocks.items():
            if known_at is None:
                phases[clock] = None
                continue
            segment = segment_by_end[known_at - US]
            prefix = {p: [bar for bar in bars if bar.end + US < known_at] for p, bars in series.items()}
            observations = {}
            for (shape, confirm), rows in frames.items():
                visible = [row for row, _ in rows if row["available_at"] < known_at]
                if visible != signals(prefix, shape, confirm, cut=known_at, **availability):
                    raise ValueError("WARNING_PHASE_PREFIX_DIVERGED")
                eligible = [(row, start) for row, start in rows if row["available_at"] >= known_at
                            and segment_by_end[row["confirmed_at"]] == segment]
                observations[f"{shape}m_to_{confirm}m"] = dict(
                    coincident=next((row for row, _ in eligible if row["available_at"] == known_at), None),
                    confirmed_later=next((row for row, _ in eligible if row["available_at"] > known_at), None),
                    shape_starts_later=next((row for row, start in eligible if start > known_at), None),
                    shape_starts_later_and_confirms_above=next((row for row, start in eligible
                                                               if start > known_at and row["close"] > edge), None),
                    first_later_segment_observation=next((row for row, _ in rows if row["available_at"] > known_at
                                                          and segment_by_end[row["confirmed_at"]] != segment), None),
                )
            phases[clock] = dict(known_at=known_at, edge=edge, observations=observations)
        results[role] = dict(lower=near, upper=far, phases=phases)
    return dict(minute_count=len(minutes), roles=results, as_of=as_of)


def warning_confirmation_study(session, market):
    from lms405_portfolio_replay import ARCHIVE, input_sources
    from lms405_public_plan_roles import load_source

    index = input_sources()
    cases = []
    for contract, day, source_id, role_cue, bands in (
        ("SH2701", "2026-10-26", "WRoqwqpfSc", "第一个弱侧警告", {"FIRST_WARNING": (1546, 1556)}),
        ("JD2612", "2026-10-22", "S5356775440386223", "反弹中断", {
            "RESISTANCE": (3151, 3169), "REBOUND_INTERRUPTION": (3193, 3201), "M": (3239, 3270),
        }),
    ):
        source = load_source(index, source_id)
        body = (ARCHIVE.parent / source["archive_path"]).read_text(encoding="utf-8").replace("—", "–")
        if role_cue not in body or any(f"{lo}–{hi}" not in body for lo, hi in bands.values()):
            raise ValueError("WARNING_PHASE_SOURCE_TEXT_CHANGED")
        published = datetime.fromisoformat(source["published_at"])
        if published.astimezone(at(day).tzinfo).date() != date.fromisoformat(day):
            raise ValueError("WARNING_PHASE_SOURCE_DATE_CHANGED")
        series = read_window(session, market, contract, date.fromisoformat(day))
        cutoff = at(f"{day}T15:00") + 2 * US
        if series[1][-1].end != cutoff - 2 * US:
            raise ValueError("WARNING_PHASE_SESSION_CLOSE_CHANGED")
        known = published.replace(second=0, microsecond=0) + timedelta(minutes=1)
        result = warning_phase_comparison(series, known_after=known, as_of=cutoff,
                                          bands={role: tuple(map(Decimal, band)) for role, band in bands.items()})
        cases.append(result | dict(contract=contract, source=source, known_after=known, trading_day=day,
                                   market_counts={p: len(rows) for p, rows in series.items()},
                                   minute_sha256=sha(encoded([(b.end, *ohlc(b)) for b in series[1]]).encode()),
                                   author_version=None, author_warning_decision=None, author_action=None))
    return dict(version="lms405-warning-confirmation-study-v1", cases=cases, admitted_author_action_samples=0,
                admitted_author_bar_samples=0, executable=False, fills=None, pnl=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--compare-confirmations", action="store_true")
    modes.add_argument("--ur-ibar-source", action="store_true")
    modes.add_argument("--jd-ibar-protection", action="store_true")
    modes.add_argument("--warning-confirmation", action="store_true")
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
            market = build_market_data_service(session)
            if args.ur_ibar_source or args.jd_ibar_protection:
                review = ur_ibar_source_study if args.ur_ibar_source else jd_ibar_protection_study
                report = review(session, market)
            elif args.warning_confirmation:
                report = warning_confirmation_study(session, market)
            else:
                report = study(session, market, compare_confirmations=args.compare_confirmations)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
