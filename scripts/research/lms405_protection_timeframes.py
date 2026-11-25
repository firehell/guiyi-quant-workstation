"""Compare frozen ibar/pinbar geometry across protection observation timeframes."""

import argparse
from datetime import date, timedelta
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


def geometry_events(bars, shape_period, confirmation_period, *, start, as_of, side):
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
            if (following.close > boundary if side == "LONG" else following.close < boundary):
                events.append(dict(
                    shape_end=shape.end, confirmed_at=following.end, available_at=following.end + US,
                    ibar=frame.ibar is True, pinbar=frame.pinbar, boundary=boundary, close=following.close,
                ))
                break
            close_at += close_step
    return events


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


def study(session, market):
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
    return dict(
        version="lms405-protection-timeframe-comparison-v1", cases=cases,
        checkpoints_role="RETROSPECTIVE_INTERVAL_COMPARISON_ONLY",
        admitted_author_action_samples=0, author_matches=None, fills=None, pnl=None, executable=False,
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
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session))
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
