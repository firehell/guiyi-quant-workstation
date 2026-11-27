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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--compare-confirmations", action="store_true")
    modes.add_argument("--ur-ibar-source", action="store_true")
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
            report = ur_ibar_source_study(session, market) if args.ur_ibar_source else study(
                session, market, compare_confirmations=args.compare_confirmations,
            )
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
