"""Compare fixed, unverified outside-bar interpretations with existing keybar geometry."""

import argparse
from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path

from lms405_protection_lot_timing import verified_json
from lms405_protection_timeframes import VARIANTS, geometry_events, read_window
from lms405_replay import ohlc
from lms405_right_side_study import US, at
from lms_near405_replay import encoded, sha

OUTPUT = Path("output")
REFERENCES = {
    "october": ("lms405-protection-lot-timing-20261125/final.json",
                "6a61d2ea4463ed8b2115ddc59d90a4726f53c23db44970f58c45307eafc925e8"),
    "april": ("lms405-protection-paths-20261125/report.json",
              "5a9f618d990089035ffa9c4c9543c70c3790080a6f36f2589a7048c4d439bfeb"),
    "july": ("lms405-right-side-20261125/report.json",
             "4341b322e096a06734c75f657845fee877e8a3cf58b8ff889c3ff993fc820558"),
}
# cutoffs constrain observations, not trading permissions. Context boundaries
# are historical comparison splits and are never used to generate a signal.
CASES = {
    "I2701": ("2026-10-27", "2026-10-26T21:00", "2026-10-27T11:30:00.000002",
              "LONG", "667 671", "2026-10-26T21:46", "A5358325549629506"),
    "SH2701": ("2026-10-27", "2026-10-26T21:00", "2026-10-27T10:13",
               "LONG", None, "2026-10-26T21:58", "WRouYm67Bc"),
    "JM2509": ("2025-07-28", "2025-07-25T21:00", "2025-07-25T22:12",
               "SHORT", "1285 1303.5", "2025-07-25T21:23", "S5193109300577840"),
    "SA2605": ("2026-04-10", "2026-04-09T21:00", "2026-04-10T15:01",
               "LONG", None, "2026-04-09T22:03", "S5287284540178482"),
    "SH2607": ("2026-04-30", "2026-04-29T21:00", "2026-04-30T15:01",
               "LONG", "2017 2039", "2026-04-30T10:46", "S5293454072479751"),
}


def outside_events(series, shape_period, confirm_period, *, start, as_of, side):
    """Use only completed adjacent bars in one segment and one contract."""
    if (shape_period, confirm_period) not in VARIANTS or side not in ("LONG", "SHORT"):
        raise ValueError("OUTSIDE_SHAPE_VARIANT_UNSUPPORTED")

    def threshold(bar):
        return bar.high if side == "LONG" else bar.low

    def passed(bar, level):
        return bar.close > level if side == "LONG" else bar.close < level

    def result(kind, shape, confirmation, level):
        return dict(kind=kind, shape_end=shape.end, confirmed_at=confirmation.end,
                    available_at=confirmation.end + US, close=confirmation.close, boundary=level)

    shapes = series[shape_period]
    quotes = {bar.start: bar for bar in series[confirm_period] if bar.end + US < as_of}
    step = timedelta(minutes=shape_period)
    confirmation_step = timedelta(minutes=confirm_period)
    events = []
    for parent, shape in zip(shapes, shapes[1:]):
        if shape.end + US >= as_of:
            break
        if (shape.start < start or not (parent.completed and shape.completed)
                or parent.end != shape.start or parent.contract != shape.contract
                or shape.end - shape.start != step or parent.end - parent.start != step
                or not (shape.low < parent.low and shape.high > parent.high)):
            continue
        if passed(shape, threshold(parent)):
            events.append(result("OUTSIDE_OWN_CLOSE", shape, shape, threshold(parent)))
        next_start = shape.end
        while next_start < shape.end + step:
            following = quotes.get(next_start)
            if (following is None or not following.completed or following.contract != shape.contract
                    or following.end != next_start + confirmation_step):
                break
            if passed(following, threshold(shape)):
                events.append(result("OUTSIDE_NEXT_CLOSE", shape, following, threshold(shape)))
                break
            next_start = following.end
    return sorted(events, key=lambda row: (row["available_at"], row["kind"], row["shape_end"]))


def price_digest(rows):
    return [[bar.end.isoformat(), *map(str, ohlc(bar))] for bar in rows]


def check_reference(contract, day, series, references):
    one = price_digest(series[1])
    if contract in ("SH2701", "I2701"):
        digest = dict(bars=len(one), ohlc_sha256=sha(json.dumps(one, separators=(",", ":")).encode()))
        if digest != references["october"]["cases"][contract]["market"]:
            raise ValueError("OUTSIDE_SHAPE_OCTOBER_MARKET_CHANGED")
    elif contract == "JM2509":
        ref = references["july"]["cases"]["jm-transition"]["input"]
        for period in (1, 5):
            rows = price_digest(series[period])
            digest = dict(count=len(rows), hash=sha(encoded(rows).encode()))
            if digest != ref[f"{period}m"]:
                raise ValueError("OUTSIDE_SHAPE_JULY_MARKET_CHANGED")
    else:
        ref = references["april"]["cases"][contract]["days"][day]["market"]
        for period, bars in series.items():
            if dict(count=len(bars), sha256=sha(encoded(price_digest(bars)).encode())) != ref[f"{period}m"]:
                raise ValueError("OUTSIDE_SHAPE_APRIL_MARKET_CHANGED")


def analyze(series, start, cutoff, direction, band, context_split, frontier):
    inspection = {}
    for shape, confirmation in VARIANTS:
        inputs = dict(start=start, side=direction)
        identity = f"{shape}m_to_{confirmation}m"
        existing = geometry_events(series, shape, confirmation, as_of=cutoff, **inputs)
        outside = outside_events(series, shape, confirmation, as_of=cutoff, **inputs)
        # Same-bar outside observation depends on shape period only.
        if shape != confirmation:
            outside = [row for row in outside if row["kind"] == "OUTSIDE_NEXT_CLOSE"]
        prefix_times = {context_split, *(row["available_at"] for row in outside)}
        for split in sorted(prefix_times):
            truncated = {period: [bar for bar in bars if bar.end + US < split] for period, bars in series.items()}
            earlier = outside_events(truncated, shape, confirmation, as_of=split, **inputs)
            if shape != confirmation:
                earlier = [row for row in earlier if row["kind"] == "OUTSIDE_NEXT_CLOSE"]
            if earlier != [row for row in outside if row["available_at"] < split]:
                raise ValueError("OUTSIDE_SHAPE_PREFIX_DIVERGED")
        by_end = {bar.end: bar for bar in series[shape]}
        for row in [*existing, *outside]:
            frame = by_end[row["shape_end"]]
            row["shape_in_contact_with_band"] = None if band is None else frame.low <= band[1] and frame.high >= band[0]
            row["shape_started_after_context"] = frame.start > context_split
            # A candidate closing at the frontier may still leave the entire
            # next overlapping minute available under the optimistic envelope.
            row["whole_leg_price_compatible"] = (
                None if frontier is None else row["confirmed_at"] <= frontier
            )
        inspection[identity] = dict(existing=existing, outside=outside)
    return inspection


def study(session, market, references):
    cases = {}
    for contract, (day, start, cutoff, side, band, split, source) in CASES.items():
        series = read_window(session, market, contract, date.fromisoformat(day))
        check_reference(contract, day, series, references)
        opening_bound = references["october"]["cases"].get(contract)
        frontier = opening_bound["optimistic_latest_whole_leg_start"] if opening_bound else None
        cases[contract] = dict(
            day=day, start=at(start), cutoff=at(cutoff), side=side, band=band, context_split=at(split),
            source=source, whole_leg_optimistic_frontier=frontier, author_shape_at=None, author_action_at=None,
            periods={f"{period}m": dict(count=len(rows), sha256=sha(encoded(price_digest(rows)).encode()))
                     for period, rows in series.items()},
            inspections=analyze(series, at(start), at(cutoff), side, tuple(map(Decimal, band.split())) if band else None,
                                at(split), at(frontier) if frontier else None),
        )
    return dict(
        version="lms405-protection-shape-audit-v1", cases=cases,
        references={name: digest for name, (_, digest) in REFERENCES.items()},
        author_ebar_definition=None, author_signal_samples=0, author_matches=None,
        executable=False, fills=None, pnl=None,
    )


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
        inputs = {name: verified_json(OUTPUT / file, digest) for name, (file, digest) in REFERENCES.items()}
        with SessionLocal() as session, readonly_transaction(session, timeout_seconds=45):
            report = study(session, build_market_data_service(session), inputs)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded(report))
    except MarketDataError as exc:
        parser.exit(2, f"MDS_BLOCKED: {exc.code}\n")
    except OperationalError:
        parser.exit(2, "LOCAL_MDS_CONNECTION_UNAVAILABLE\n")
    except (KeyError, OSError, ValueError):
        parser.exit(2, "OUTSIDE_SHAPE_SOURCE_OR_MARKET_UNVERIFIED\n")


if __name__ == "__main__":
    main()
